# Chunk-phase validation hardening (chunk prompt v2.1)

## Context

The batch analysis pipeline's chunk phase is failing ~25% of per-game
runs in production. Every failure is a pydantic `RichChunkSummary`
validation error in `src/library-layer/library_layer/llm/anthropic_batch.py`,
caught at `collect_phase.py:234` which then raises `RuntimeError` and
fails the whole per-game state machine.

Looking at a sample of 5 failures from orchestrator run
`batch-20260422-223021` (all 5 failed games in that batch hit the
same two root causes):

**Type A — model emits out-of-enum values (2/5):**
- `topics[N].sentiment = 'neutral'` — `TopicSignal.sentiment` enum
  is `positive|negative|mixed` only.
- `topics[N].category = 'competitor_ref'` — `TopicCategory` enum is
  the 9 defined categories (design_praise, gameplay_friction,
  wishlist_items, dropout_moments, technical_issues, refund_signals,
  community_health, monetization_sentiment, content_depth).

**Type B — model returns `topics` as a JSON-serialized string (3/5):**
Instead of `input.topics = [{...}, {...}]` inside the tool_use block,
the model returns `input.topics = '[\n  {\n    "topic": ...'`.
There's already a `_coerce_json_array` field validator
(`analyzer_models.py:146`) that `json.loads()` the string — but it
fails because the string itself is invalid JSON. The string appears
truncated mid-array.

**Why Type B happens:** `ANALYSIS_CHUNK_MAX_TOKENS = 1024`
(`config.py:211`) is too tight. A `RichChunkSummary` with up to 12
topics × (summary + 2-3 quotes at up to 400 chars + category +
sentiment + confidence + counts + competitor_refs + notable_quotes +
batch_stats) routinely exceeds 1024 output tokens on review-dense
games. Anthropic truncates the response mid-array, the resulting
string is unparsable, and the validator can't recover.

**Why Type A happens:** the prompt states the enum inline
(`analyzer.py:451`) but doesn't negatively instruct. The model picks
"neutral" because it's a natural English sentiment word *and* because
the same file has `neutral` as a valid value on other sentiment
fields (`analyzer_models.py:39, 201`). For category, the model
invented `competitor_ref` because competitor references are a real
pattern in reviews and the prompt doesn't tell the model they belong
in the dedicated `competitor_refs` field instead of as a topic.

Don't fix this with recovery hacks (e.g. mapping `neutral → mixed`,
dropping unknown categories). Both would corrupt downstream analysis
— `mixed` is a polarization signal and dropping out-of-enum topics
silently loses information. Fix the root causes.

## What to do

### 1. Raise chunk max_tokens

In `src/library-layer/library_layer/config.py:211`:

```python
ANALYSIS_CHUNK_MAX_TOKENS: int = 4096  # was 1024
```

Give the model enough output budget to emit a full `RichChunkSummary`
(12 topics with quotes and nested fields) without truncation. 4096 is
conservative — the typical response is ~1500–2500 tokens, so 4096
leaves headroom for the worst case without much billing impact (we
only pay for tokens actually generated).

### 2. Update the chunk prompt — `CHUNK_SYSTEM_PROMPT_V2`

In `src/library-layer/library_layer/analyzer.py` (the multi-line
string beginning at line 336), make three additions:

**In `<rules>`:**

- Add: `"sentiment values are strictly 'positive', 'negative', or
  'mixed'. Do NOT emit 'neutral'. If a topic has no clear valence
  (descriptive mentions only), OMIT it — do not pad the list with
  low-signal topics."`
- Add: `"Competitor mentions do NOT belong in topics. If reviewers
  compare this game to another (by name), put those in the
  competitor_refs field, not as a topic. The 9 listed categories
  are exhaustive — do not invent new ones."`

**In `<category_definitions>`:** add a one-line preamble above the
list:

```
The 9 categories below are the complete set. If a signal doesn't fit,
DROP IT — do not invent a 10th category. Competitor comparisons go in
the separate competitor_refs field, not here.
```

**In the user-message output-format block** (`_build_chunk_user_message_v2`
at `analyzer.py:447-455`): change the sentiment line to make the
"no neutral" rule redundant-but-visible right next to the schema:

```
    sentiment ("positive" | "negative" | "mixed" — never "neutral";
               drop topics with no clear valence),
```

### 3. Normalize `sentiment` enums across `analyzer_models.py`

Right now the file is self-contradicting: `neutral` is allowed on
some sentiment fields and not others, which is what gives the model
cover to emit it.

Pick one: `positive | negative | mixed` everywhere. Remove `"neutral"`
from:

- `analyzer_models.py:39` — the bare `sentiment` Literal (verify what
  model owns this before removing; if it's no longer used, delete the
  field entirely).
- `analyzer_models.py:201` — `CompetitiveRef.comparison_sentiment`.

Check there are no repository rows in prod that currently store
`"neutral"` before merging — if there are, they'll fail re-parse on
read. Grep `reports` JSON and `merged_summaries` JSON for the literal
string `"neutral"` in a sentiment field. (If any exist, the cleanup
is: write the pydantic models with a `mode='before'` validator that
maps stored `"neutral" → "mixed"` on READ only, not on write. But
only add that shim if the grep turns up hits — don't add it
speculatively.)

### 4. Do NOT bump `CHUNK_PROMPT_VERSION`

Leave it at `"chunk-v2.0"` (`analyzer.py:330`). Bumping it would
invalidate every already-cached chunk across all ~15 successfully-
analyzed games in the current wedge batch, forcing a full re-run at
~$1/game for zero benefit — those games succeeded precisely because
they didn't hit the validation issues this prompt is fixing.

Keeping the version the same means:
- Successful games: untouched. Their cached chunks under `chunk-v2.0`
  are valid and downstream merge/synthesis keeps using them.
- Failed games (the 5 above): `chunk_repo.find_by_appid` (see
  `analyzer.py:849`) finds their partial chunk set (the 39-of-40
  that persisted). On re-trigger, `build_chunk_requests` sends only
  the DB-missing chunks to the backend — i.e. the single record
  that failed before, now with the new prompt.
- New games: pick up the new prompt text naturally on first
  analysis.

Trade-off we're accepting: downstream merge for a re-run failed game
will mix chunks produced by old-prompt-text and new-prompt-text at
the same `chunk-v2.0` version label. That's fine here because both
prompt revisions target the same `RichChunkSummary` schema and the
changes are restrictive (fewer allowed values, clearer routing of
competitor talk) — they don't alter the topic extraction contract.

## Verification

1. **Local unit tests first.** Run:
   ```
   poetry run pytest -v tests/
   poetry run ruff check .
   ```
   Any test that asserts `sentiment == "neutral"` on a `TopicSignal`
   or `CompetitiveRef` fixture needs updating — that value is no
   longer valid.

2. **Realtime single-game smoke.** Pick one of the failed appids
   (e.g. `2742830`, `456670`, `1108370`, `2501600`, `2289750`) and
   run a single-game realtime analysis locally to confirm the new
   prompt produces valid output end-to-end.

3. **Production dry-run.** After the user deploys, re-trigger those
   same 5 appids via `scripts/trigger_batch_analysis.py --env
   production --appids 2742830 456670 1108370 2501600 2289750`.
   All 5 should now complete. Check CloudWatch
   `/steampulse/production/batch-collect-phase` for any
   `batch_record_validation_error` entries in the run — should be
   zero.

4. **Cost check.** Raising max_tokens to 4096 doesn't change input
   cost, and output cost only changes if responses actually get
   longer. Compare `batch_executions.estimated_cost_usd` on a
   before/after pair of games of similar chunk count — the delta
   should be within noise (< 10%).

## Rollout

- Single deploy. `chunk-v2.0` cached chunks continue to be read (we
  intentionally didn't bump the version, see step 4). Existing
  `reports` are not touched. Failed-game re-triggers fill in only
  the missing chunks under the same version label using the new
  prompt text.
- The user runs `bash scripts/deploy.sh` — do not deploy from
  Claude.
- After deploy, the user re-triggers the 141-game wedge batch. Any
  remaining chunk-phase failures (if ~<1% residual noise slips
  through) are now tolerable and the rest of the batch completes
  independently (per the 100% tolerated_failure_percentage fix
  already deployed).

## Out of scope

- Soft chunk-failure threshold in `collect_phase.py` (the "95%
  persisted → continue" policy). That's a separate, orthogonal
  change — worth doing as a belt-and-suspenders layer once this
  lands, but keep it out of this prompt so the root-cause fix is
  measurable on its own.
- Inline realtime retry of failed batch records. Same reasoning —
  separate lever.
