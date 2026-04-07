# SteamPulse Review Analysis Pipeline

This document describes how reviews are processed into structured game intelligence reports. Use it to inform prompts, new features, or integrations with the analysis system.

---

## Overview

The pipeline turns raw Steam reviews into a structured `GameReport` using a **two-pass LLM strategy** over AWS Bedrock. The active production path uses **Bedrock Batch Inference** — all LLM calls are asynchronous, run as managed batch jobs, and are coordinated by a Step Functions state machine.

```
Reviews (DB)
    │
    ▼
[PreparePass1]  — chunk reviews → Bedrock Batch Job (Haiku, Pass 1)
                                                │
                              Bedrock writes output JSONL to S3
                                                │
    ▼
[PreparePass2]  — aggregate chunk signals, compute Python scores → Bedrock Batch Job (Sonnet, Pass 2)
                                                │
                              Bedrock writes output JSONL to S3
                                                │
    ▼
[ProcessResults] — parse reports, upsert to DB, publish SNS events
```

---

## Pass 1 — Chunk Signal Extraction (Haiku)

**Purpose:** Extract raw signals from batches of 50 reviews. Cheap, fast, and parallel.

**Input:** Up to 2,000 reviews per game, sorted chronologically, grouped into 50-review chunks.

**Each review is formatted with context before being sent to the LLM:**
```
[POSITIVE, 450h played, 1523 helpful votes, Post-launch, Paid, 2024-06-15]: review text...
```
Playtime, vote counts, EA/post-launch status, and paid/free-key status are all included so the model can weight signals appropriately.

**11 signal types extracted per chunk:**

| Signal                   | What it captures                                                               |
|--------------------------|--------------------------------------------------------------------------------|
| `design_praise`          | Specific design elements praised: mechanics, art, audio, controls, progression |
| `gameplay_friction`      | In-game UX/design problems: balance, pacing, missing UI, difficulty spikes     |
| `wishlist_items`         | Net-new features players want (not fixes to broken things)                     |
| `dropout_moments`        | Moments/stages where players quit — must include timing                        |
| `competitor_refs`        | Named games mentioned, with sentiment and context                              |
| `notable_quotes`         | 0–2 verbatim quotes, under 40 words each                                       |
| `technical_issues`       | Crashes, FPS drops, bugs, save corruption                                      |
| `refund_signals`         | Explicit refund language only ("refunded", "got my money back")                |
| `community_health`       | Multiplayer/community ecosystem signals                                        |
| `monetization_sentiment` | DLC, microtransaction, pay-to-win feelings                                     |
| `content_depth`          | Game length, replayability, value perception                                   |

Plus `batch_stats`: positive/negative counts, average playtime, high-playtime count, EA review count, free-key count.

**Output model:** `ChunkSummary` (Pydantic, in `library_layer/models/analyzer_models.py`). All list fields have empty-list defaults — missing signals are fine; no field is required to be non-empty.

**Key rule:** Extract only what is explicitly stated. No invention, no generalisation. The system prompt enforces this hard.

---

## Between Passes — Python Score Computation

**Sentiment magnitude is owned by Steam, not the LLM and not the analyzer.** Steam's `positive_pct` (0–100) and `review_score_desc` on the `Game` row are the only sentiment numbers shown to users. The analyzer never recomputes them — see `scripts/prompts/data-source-clarity.md` for the rationale and `scripts/prompts/completed/data-source-clarity.md` if it has been moved.

Two derived values are still computed in Python before Pass 2 (never by the LLM — leaving numeric output to the LLM introduces inconsistency and hallucination risk):

### `hidden_gem_score` (float 0.0–1.0)
Rewards high-quality games with low discoverability. Both inputs come from the `Game` row (Steam-sourced), not from the sampled batch:
```
scarcity = 1 - (review_count / 10_000)   # 0 at 10k+, 1 at 0
quality  = (positive_pct - 80) / 20       # 0 at 80%, 1 at 100%
score    = scarcity * quality
```
Games with ≥10,000 reviews score 0.0 (not hidden). Games below 80% positive score 0.0 (not a gem). The signature is `compute_hidden_gem_score(positive_pct, review_count)`.

### `sentiment_trend` (dict)
Compares positive vote ratio of the last 90 days vs. the prior 90 days from the local review sample (a window comparison, not a magnitude). Returns:
```python
{"trend": "improving" | "stable" | "declining",
 "note": str,
 "sample_size": int,    # total reviews across both windows
 "reliable": bool}      # True iff each window has >= 50 reviews
```
Requires at least 10 reviews in each window or it falls back to `"stable"` with an insufficient-volume note. A delta >5pp = improving or declining.

These values, plus Steam's `positive_pct` / `review_score_desc` for narrative context, are passed into the Pass 2 prompt. After the LLM responds, `hidden_gem_score`, `sentiment_trend`, `sentiment_trend_note`, `sentiment_trend_reliable`, and `sentiment_trend_sample_size` are overwritten on the `GameReport` to prevent any LLM substitution.

---

## Pass 2 — Synthesis (Sonnet)

**Purpose:** Synthesize all chunk signals into a complete, structured game intelligence report.

**Input:** Aggregated signals from all Pass 1 chunk summaries (all 11 signal types concatenated), plus the pre-computed scores and temporal context.

**Temporal context** (from `GameTemporalContext`) included in the prompt when available:
- Release date and age bucket
- Review velocity (lifetime and last 30 days)
- Launch trajectory
- Early Access history (fraction of EA reviews, sentiment delta EA vs. post-launch)
- Evergreen status

**The synthesis prompt enforces strict anti-duplication rules** — each section answers exactly one question. An issue about bots, for example, belongs in exactly one of: `gameplay_friction` (the design problem), `churn_triggers` (when it causes dropout), `dev_priorities` (the fix), or `community_health` (if it's a population problem). The LLM is instructed to stop and reassign if it spots duplication.

**Output model:** `GameReport` (Pydantic). Key sections:

| Section                       | Type     | Notes                                                                            |
|-------------------------------|----------|----------------------------------------------------------------------------------|
| `game_name`, `appid`          | str, int |                                                                                  |
| `total_reviews_analyzed`      | int      |                                                                                  |
| `sentiment_trend`             | Literal  | Pre-computed window comparison, overwritten post-LLM                             |
| `sentiment_trend_note`        | str      | Narrative explanation of trend                                                   |
| `sentiment_trend_reliable`    | bool     | True iff each 90-day window has ≥50 reviews                                      |
| `sentiment_trend_sample_size` | int      | Total reviews across both trend windows                                          |
| `hidden_gem_score`            | float    | Pre-computed from Steam's `positive_pct` + `review_count`, overwritten post-LLM  |
| `one_liner`                   | str      | Max 25 words, for gamers deciding to buy                                         |
| `audience_profile`            | object   | `ideal_player`, `casual_friendliness`, `archetypes[]`, `not_for[]`               |
| `design_strengths`            | list     | 2–8 items — what design decisions work                                           |
| `gameplay_friction`           | list     | 1–7 items — in-game UX/design problems only                                      |
| `player_wishlist`             | list     | 1–6 items — net-new features only                                                |
| `churn_triggers`              | list     | 1–4 items — moments causing dropout, with timing                                 |
| `technical_issues`            | list     | 0–6 items — bugs, crashes, performance                                           |
| `refund_signals`              | object   | frequency, primary drivers, risk level (renamed from `refund_risk` — describes language found in reviews, not a prediction) |
| `community_health`            | object   | overall status, signals, multiplayer population                                  |
| `monetization_sentiment`      | object   | overall, signals, DLC sentiment                                                  |
| `content_depth`               | object   | perceived length, replayability, value perception, plus `confidence` and `sample_size` |
| `dev_priorities`              | list     | 3–5 `{action, why_it_matters, frequency, effort}` — ranked by impact × frequency |
| `competitive_context`         | list     | Named competitor references only                                                 |
| `genre_context`               | str      | 1–2 sentence genre benchmark, no named competitors                               |

**Sentiment magnitude is NOT in the report.** `sentiment_score` and `overall_sentiment` were dropped in the data-source-clarity refactor. Steam's `positive_pct` (0–100) and `review_score_desc` live on the `Game` row and are joined at the API/UI layer (e.g. `/api/games/{appid}/report` returns them in the `game` block alongside per-source freshness timestamps).

**Free vs. Pro sections:**
- **Free** (visible to all): `design_strengths`, `gameplay_friction`, `technical_issues`, `genre_context`, `one_liner`, trend fields, hidden_gem_score
- **Pro** (gated): `player_wishlist`, `churn_triggers`, `dev_priorities`, `competitive_context`

---

## Batch Execution Flow (Step Functions)

The state machine orchestrates both passes and handles polling:

```
PreparePass1
    → SubmitBatchJob (pass1, Haiku model)
    → CheckBatchStatus (poll until Completed)
    → PreparePass2
    → SubmitBatchJob (pass2, Sonnet model)
    → CheckBatchStatus (poll until Completed)
    → ProcessResults
```

**S3 layout per execution:**
```
jobs/{execution_id}/
  pass1/
    input.jsonl     ← written by PreparePass1 (one record per chunk)
    output/         ← written by Bedrock (one or more .out JSONL files)
  pass2/
    input.jsonl     ← written by PreparePass2 (one record per game)
    output/         ← written by Bedrock
    scores.json     ← Python-computed scores by appid (written by PreparePass2)
```

**Record ID conventions:**
- Pass 1: `{appid}-chunk-{n}` — used to group chunks back by appid in PreparePass2
- Pass 2: `{appid}-synthesis` — used to identify the game in ProcessResults

**ProcessResults** reads scores.json and overwrites the LLM's numeric fields, then upserts to the `reports` table and publishes `report-ready` (per game) and `batch-complete` (once) to SNS.

---

## Prompt Caching

Both system prompts (`CHUNK_SYSTEM_PROMPT`, `SYNTHESIS_SYSTEM_PROMPT`) are sent with `"cache_control": {"type": "ephemeral"}` in the real-time path. This reduces latency and cost significantly when processing many chunks of the same game — the system prompt is cached across chunk calls.

In the batch path, system prompts are included inline in each JSONL record (Bedrock batch format requires it) so caching operates at Bedrock's level.

---

## Key Files

| File                                      | Role                                                                                                                       |
|-------------------------------------------|----------------------------------------------------------------------------------------------------------------------------|
| `library_layer/analyzer.py`               | Prompts, chunking logic, `_aggregate_chunk_summaries()`, score functions wiring, real-time `analyze_reviews()` entry point |
| `library_layer/models/analyzer_models.py` | `ChunkSummary`, `GameReport`, and all nested Pydantic models                                                               |
| `library_layer/utils/scores.py`           | `compute_hidden_gem_score(positive_pct, review_count)`, `compute_sentiment_trend(reviews) -> SentimentTrend dict`           |
| `library_layer/models/temporal.py`        | `GameTemporalContext` — velocity, EA delta, launch trajectory                                                              |
| `batch_analysis/prepare_pass1.py`         | Reads reviews from DB, builds Pass 1 JSONL, uploads to S3                                                                  |
| `batch_analysis/submit_batch_job.py`      | Creates Bedrock Batch Inference job                                                                                        |
| `batch_analysis/check_batch_status.py`    | Polls Bedrock job status, maps to Running/Completed/Failed                                                                 |
| `batch_analysis/prepare_pass2.py`         | Reads Pass 1 output, aggregates signals, computes scores, builds Pass 2 JSONL                                              |
| `batch_analysis/process_results.py`       | Reads Pass 2 output, overwrites scores, upserts reports, publishes events                                                  |

---

## Constraints and Rules for Extending the Pipeline

- **Never add `min_length` constraints to list fields in `ChunkSummary`.** If a signal is absent from a chunk, an empty list is correct. Validation failures in batch processing crash the entire game's record — use `max_length` only.
- **`min_length` on `GameReport` list fields is intentional** (e.g. `design_strengths` requires 2–8) — these are synthesis-level fields where the LLM has the full picture and an empty result indicates a prompt failure.
- **Numeric values (`hidden_gem_score`, `sentiment_trend*`) must always be computed in Python** and overwritten on the `GameReport` after LLM response. Never rely on LLM-generated values for these fields.
- **Never reintroduce `sentiment_score` or `overall_sentiment` to the `GameReport`.** Sentiment magnitude is owned by Steam — consume `positive_pct` / `review_score_desc` from the `Game` row instead. The LLM is fed Steam's `positive_pct` as canonical context for narrative tone, but never asked to produce a sentiment number.
- **Each section answers exactly one question.** Do not add a field that overlaps semantically with an existing one. Consult the anti-duplication rules in `SYNTHESIS_SYSTEM_PROMPT` before adding sections.
- **The batch path is the active production path.** The real-time path in `analysis/handler.py` is deprecated and not in use — do not add features to it.
- **Temporal context is optional** — `temporal=None` is valid for games missing velocity data. The synthesis prompt omits the temporal block when it's absent.
