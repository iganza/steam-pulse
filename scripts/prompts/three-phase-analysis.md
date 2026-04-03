# Three-Phase LLM Analysis Pipeline

## Background

The current two-pass analysis pipeline has five structural limitations:

1. **Chunk summaries are ephemeral.** Phase 1 output exists only in memory. Re-running
   Phase 2 with improved prompts requires re-processing every review through Phase 1.

2. **No merge phase.** For games with 100+ chunks (5,000+ reviews), the synthesis prompt
   receives thousands of flat string-list items the LLM must mentally deduplicate. Signal
   quality degrades as context fills with noise.

3. **Flat signal schema loses information.** `ChunkSummary` stores signals as `list[str]`
   with no per-topic sentiment scores, mention counts, or linked quotes. This makes it
   impossible to render a "Topics" sub-tab in the frontend or weight signals during merge.

4. **No incremental re-analysis.** New reviews for a game require re-running the entire
   pipeline. Stored chunk summaries keyed by content hash let Phase 1 skip unchanged chunks.

5. **Sequential chunking ignores review distribution.** Reviews are split by index, so
   chunks can be 90% positive or 90% negative depending on time period, biasing extraction.

### What this upgrade enables

- Re-run Phase 3 without re-running Phase 1 — prompt iteration costs only the synthesis call
- Structured `TopicSignal` objects power the frontend Topics tab, cross-game comparison, and
  topic-level sentiment drilldowns
- Incremental updates: new reviews → new Phase 1 chunks only → re-merge → re-synthesize
- Better signal quality for high-review games via hierarchical merge
- Full audit trail: every stored artifact records model ID and prompt version

---

## Architecture Overview

```
Reviews (DB)
    │
    ▼
┌──────────────────────────────────────────────────┐
│  PHASE 1: CHUNK & SUMMARIZE (map)                │
│  Model: LLM_MODEL__CHUNKING                      │
│  Input: 50-review stratified chunks              │
│  Output: RichChunkSummary per chunk              │
│  Storage: chunk_summaries table                  │
│  Idempotent: skip if chunk_hash + version exists │
└──────────────────┬───────────────────────────────┘
                   │ list[RichChunkSummary]
                   ▼
┌──────────────────────────────────────────────────┐
│  PHASE 2: MERGE SUMMARIES (reduce)               │
│  Model: LLM_MODEL__MERGING                       │
│  ≤5 chunks: single merge pass                    │
│  >5 chunks: hierarchical (groups of 5–8)         │
│  Output: MergedSummary (superset of chunk schema)│
│  Storage: merged_summaries table                 │
└──────────────────┬───────────────────────────────┘
                   │ single MergedSummary
                   ▼
┌──────────────────────────────────────────────────┐
│  PHASE 3: ANALYZE (final synthesis)              │
│  Model: LLM_MODEL__SUMMARIZER                    │
│  Input: MergedSummary + metadata + temporal +    │
│         Python-computed scores                   │
│  Output: GameReport (unchanged schema)           │
│  Storage: reports table (existing)               │
└──────────────────────────────────────────────────┘
```

**Data flow invariant:** Phase 2 NEVER invents information. It consolidates, deduplicates,
reconciles scores, and selects best quotes. All novel extraction happens in Phase 1 (from
raw reviews) and all novel analysis happens in Phase 3 (from merged signals + context).

---

## Goal

Replace the two-pass analysis pipeline with a three-phase pipeline that stores intermediate
artifacts, adds a merge phase, and uses structured topic signals instead of flat string lists.

The `GameReport` output schema is **unchanged** — the frontend does not break.

Both execution paths (real-time Converse API and Bedrock Batch Inference) use the same
prompts and produce identical output.

---

## Codebase Orientation

### Files to Modify

- **Models**: `src/library-layer/library_layer/models/analyzer_models.py` — add `TopicSignal`, `ReviewQuote`, `RichChunkSummary`, `MergedSummary`
- **Analyzer**: `src/library-layer/library_layer/analyzer.py` — v2 prompts, new chunk/merge/synthesis functions, `analyze_reviews_v3()` orchestrator
- **Scores**: `src/library-layer/library_layer/utils/scores.py` — add `compute_sentiment_score_from_counts()`
- **Config**: `src/library-layer/library_layer/config.py` — add `LLM_MODEL__MERGING` task
- **Schema reference**: `src/library-layer/library_layer/schema.py` — add new tables
- **Analysis handler**: `src/lambda-functions/lambda_functions/analysis/handler.py` — switch to `analyze_reviews_v3()`
- **Batch prepare_pass1**: `src/lambda-functions/lambda_functions/batch_analysis/prepare_pass1.py` — stratified chunking + v2 prompts
- **Batch prepare_pass2**: rename to `prepare_pass3.py`, accept MergedSummary input
- **Batch process_results**: `process_results.py` — store pipeline_version in reports
- **CDK**: `infra/stacks/batch_analysis_stack.py` — add merge Lambda + update Step Functions ASL

### Files to Create

- `src/library-layer/library_layer/utils/chunking.py` — stratified chunking + chunk hash
- `src/library-layer/library_layer/repositories/chunk_summary_repo.py` — CRUD for chunk_summaries
- `src/library-layer/library_layer/repositories/merged_summary_repo.py` — CRUD for merged_summaries
- `src/lambda-functions/migrations/0012_chunk_summaries.sql` — new table
- `src/lambda-functions/migrations/0013_merged_summaries.sql` — new table + reports columns
- `src/lambda-functions/lambda_functions/batch_analysis/prepare_merge.py` — batch merge Lambda
- Tests: `tests/utils/test_chunking.py`, `tests/repositories/test_chunk_summary_repo.py`, `tests/repositories/test_merged_summary_repo.py`, `tests/services/test_analyzer_v3.py`

### Existing Patterns to Follow

**LLM model routing** (from `config.py`):
```python
_config.model_for("chunking")    # LLM_MODEL__CHUNKING
_config.model_for("summarizer")  # LLM_MODEL__SUMMARIZER
# New:
_config.model_for("merging")     # LLM_MODEL__MERGING
```

**Repository pattern**: one class per table, pure SQL I/O, returns Pydantic models.

**Prompt constants**: system prompts defined as module-level string constants in `analyzer.py`.

**Scores computed in Python**: `sentiment_score`, `hidden_gem_score`, `sentiment_trend`
are ALWAYS computed in Python and override LLM output. This principle is unchanged.

---

## Step 1: New Pydantic Models

In `src/library-layer/library_layer/models/analyzer_models.py`, add these models. Keep
the existing `ChunkSummary` and `BatchStats` for backward compatibility during migration.

```python
class ReviewQuote(BaseModel):
    """A verbatim quote linked back to its source review."""
    text: str = Field(max_length=200)
    steam_review_id: str | None = None
    voted_up: bool
    playtime_hours: int = 0
    votes_helpful: int = 0


class TopicSignal(BaseModel):
    """A structured topic extracted from a chunk of reviews."""
    topic: str                          # canonical label, e.g. "base building", "matchmaking"
    category: Literal[
        "design_praise", "gameplay_friction", "wishlist_items",
        "dropout_moments", "technical_issues", "refund_signals",
        "community_health", "monetization_sentiment", "content_depth",
    ]
    sentiment: Literal["positive", "negative", "mixed"]
    mention_count: int = Field(ge=1)
    confidence: Literal["low", "medium", "high"]
    summary: str                        # 1–2 sentence distillation
    quotes: list[ReviewQuote] = Field(default_factory=list, max_length=3)
    avg_playtime_hours: float = 0.0
    avg_helpful_votes: float = 0.0


class RichBatchStats(BaseModel):
    positive_count: int = 0
    negative_count: int = 0
    avg_playtime_hours: float = 0.0
    high_playtime_count: int = 0        # 50h+ reviews
    early_access_count: int = 0
    free_key_count: int = 0
    date_range_start: str | None = None # ISO date
    date_range_end: str | None = None


class RichChunkSummary(BaseModel):
    """Phase 1 output — structured topic signals from a chunk of reviews."""
    topics: list[TopicSignal] = Field(default_factory=list)
    competitor_refs: list[CompetitorRef] = Field(default_factory=list)
    notable_quotes: list[ReviewQuote] = Field(default_factory=list, max_length=3)
    batch_stats: RichBatchStats = Field(default_factory=RichBatchStats)


class MergedSummary(BaseModel):
    """Phase 2 output — consolidated topic signals from merging chunk summaries."""
    topics: list[TopicSignal] = Field(default_factory=list)
    competitor_refs: list[CompetitorRef] = Field(default_factory=list)
    notable_quotes: list[ReviewQuote] = Field(default_factory=list, max_length=5)
    total_stats: RichBatchStats = Field(default_factory=RichBatchStats)
    merge_level: int = 0                # 0=no merge (single chunk), 1=first, 2=second
    chunks_merged: int = 1
    source_chunk_ids: list[int] = Field(default_factory=list)
```

---

## Step 2: Stratified Chunking

Create `src/library-layer/library_layer/utils/chunking.py`.

### Algorithm

```
1. Separate reviews into voted_up=True and voted_up=False pools
2. Within each pool, sort by votes_helpful DESC
   - Apply 1.5× multiplier to votes_helpful for reviews from last 90 days
     (sort key only — does not modify actual vote count)
3. Compute target_positive_ratio = len(positive) / len(all_reviews)
4. For each chunk of CHUNK_SIZE (50):
   a. Draw ceil(CHUNK_SIZE × target_positive_ratio) from positive pool
   b. Draw remainder from negative pool
   c. If a pool is exhausted, fill from the other
   d. Ensure at least 1 review from each available playtime bucket:
      <2h, 2–10h, 10–50h, 50–200h, 200h+
      (soft constraint — swap lowest-helpful-vote review if needed)
   e. Shuffle the assembled chunk to avoid ordering bias
5. Return list of chunks
```

### Chunk Hash

```python
def compute_chunk_hash(reviews: list[dict]) -> str:
    """Deterministic hash from sorted steam_review_id values."""
    review_ids = sorted(str(r.get("steam_review_id", "")) for r in reviews)
    return hashlib.sha256("|".join(review_ids).encode()).hexdigest()[:16]
```

Same reviews in any order = same hash. Adding/removing a review changes the hash.

### Exports

```python
def stratified_chunk_reviews(reviews: list[dict], chunk_size: int = 50) -> list[list[dict]]:
def compute_chunk_hash(reviews: list[dict]) -> str:
```

---

## Step 3: Database Migrations

### `0012_chunk_summaries.sql`

```sql
-- depends: 0011_<previous_migration>

CREATE TABLE IF NOT EXISTS chunk_summaries (
    id              BIGSERIAL PRIMARY KEY,
    appid           INTEGER NOT NULL REFERENCES games(appid),
    chunk_index     SMALLINT NOT NULL,
    chunk_hash      TEXT NOT NULL,
    review_count    SMALLINT NOT NULL,
    summary_json    JSONB NOT NULL,
    model_id        TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (appid, chunk_hash, prompt_version)
);

CREATE INDEX IF NOT EXISTS idx_chunk_summaries_appid ON chunk_summaries(appid);
```

### `0013_merged_summaries.sql`

```sql
-- depends: 0012_chunk_summaries

CREATE TABLE IF NOT EXISTS merged_summaries (
    id              BIGSERIAL PRIMARY KEY,
    appid           INTEGER NOT NULL REFERENCES games(appid),
    merge_level     SMALLINT NOT NULL DEFAULT 1,
    summary_json    JSONB NOT NULL,
    source_chunk_ids INTEGER[] NOT NULL,
    chunks_merged   INTEGER NOT NULL,
    model_id        TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_merged_summaries_appid ON merged_summaries(appid);

ALTER TABLE reports ADD COLUMN IF NOT EXISTS pipeline_version TEXT DEFAULT '2.0';
ALTER TABLE reports ADD COLUMN IF NOT EXISTS chunk_count INTEGER;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS merged_summary_id BIGINT;
```

Update `schema.py` with both new table definitions.

---

## Step 4: Repositories

### `chunk_summary_repo.py`

```python
class ChunkSummaryRepository(BaseRepository):
    def find_by_hash(self, appid: int, chunk_hash: str, prompt_version: str) -> Row | None:
    def find_by_appid(self, appid: int, prompt_version: str) -> list[Row]:
    def insert(self, appid: int, chunk_index: int, chunk_hash: str,
               review_count: int, summary: RichChunkSummary,
               model_id: str, prompt_version: str,
               input_tokens: int | None, output_tokens: int | None,
               latency_ms: int | None) -> int:  # returns id
    def delete_by_appid(self, appid: int) -> int:  # for re-analysis
```

### `merged_summary_repo.py`

```python
class MergedSummaryRepository(BaseRepository):
    def find_latest_by_appid(self, appid: int) -> Row | None:
    def insert(self, appid: int, merge_level: int, summary: MergedSummary,
               source_chunk_ids: list[int], chunks_merged: int,
               model_id: str, prompt_version: str,
               input_tokens: int | None, output_tokens: int | None,
               latency_ms: int | None) -> int:
    def delete_by_appid(self, appid: int) -> int:
```

---

## Step 5: Phase 1 Prompt (v2)

### System Prompt (`CHUNK_SYSTEM_PROMPT_V2`)

```
You extract structured topic signals from Steam game reviews for an analytics pipeline.
A later model merges and synthesizes your output — your ONLY job is accurate extraction.

<rules>
- Extract TOPICS, not flat signal strings. Each topic is a named subject
  (e.g. "base building", "matchmaking latency") with a category, sentiment,
  mention count, confidence, and representative quotes.
- Multiple reviews about the same subject = ONE topic with higher mention_count.
- Quotes must be word-for-word from reviews. Include the steam_review_id.
- Counts must be exact for this batch.
- Do not invent, generalize, or embellish.
- confidence: "high" if mention_count >= 5 OR avg_helpful_votes >= 50,
  "medium" if mention_count >= 2, "low" otherwise.
</rules>

<signal_weighting>
- Reviews with more helpful votes = broad community agreement, stronger signal.
- Reviews with 50h+ playtime = informed player, weight friction/wishlist higher.
- Free-key reviews may be biased — note but don't weight equally.
- Early Access reviews reflect prior game state — note in summary.
</signal_weighting>

<category_definitions>
  design_praise: Specific DESIGN elements praised — mechanics, art, audio, controls,
    progression. EXCLUDE: community praise, price, nostalgia.
  gameplay_friction: In-game UX/design friction — balance, pacing, missing UI,
    difficulty spikes. EXCLUDE: pricing, community, platform issues, TECHNICAL BUGS.
  wishlist_items: NET-NEW features players want. EXCLUDE: fixes to broken things.
  dropout_moments: Moments/stages where players stopped or considered quitting.
    Must include timing.
  technical_issues: Crashes, FPS drops, bugs, save corruption, compatibility, loading
    times. EXCLUDE: design problems.
  refund_signals: Explicit refund language only. Include context.
  community_health: Player community / multiplayer ecosystem signals. EXCLUDE:
    single-player design.
  monetization_sentiment: Feelings about DLC, microtransactions, battle passes.
    EXCLUDE: base game price.
  content_depth: Game length, replayability, content volume. Include playtime context.
</category_definitions>

Return ONLY valid JSON matching the schema. No prose, no preamble.
```

### User Message Changes

The review format now includes `[id:{steam_review_id}]` prefix for quote attribution:

```
[id:abc123, POSITIVE, 450h played, 1523 helpful, Post-launch, Paid, 2024-06-15]: {review text}
```

The output format section specifies the `RichChunkSummary` JSON schema with `TopicSignal`
objects instead of flat string lists.

### Prompt Version Constant

```python
CHUNK_PROMPT_VERSION = "chunk-v2.0"
```

---

## Step 6: Phase 2 — Merge Prompt

### Model

Configured via `LLM_MODEL__MERGING` in env config. Add to `.env.staging` and
`.env.production`. Recommend using the same model class as chunking for cost control,
but the choice is independent.

### Merge Strategy

- **1 chunk**: skip merge entirely — convert `RichChunkSummary` → `MergedSummary`
- **2–5 chunks**: single merge pass
- **6–40 chunks**: two-level hierarchy (groups of 5–8, then merge intermediates)
- **41+ chunks**: three-level hierarchy (max depth)

### System Prompt (`MERGE_SYSTEM_PROMPT`)

```
You consolidate structured topic signals from multiple review analysis chunks
into a single unified summary.

<rules>
- MERGE topics about the same subject into ONE topic. Sum mention_counts.
  Reconcile sentiment weighted by mention_count.
- NEVER invent new topics, quotes, or information not in the input chunks.
- Keep the BEST quotes: prioritize by votes_helpful DESC, then playtime DESC.
  Max 3 quotes per topic, max 5 notable_quotes total.
- When merging sentiment: if 80%+ mentions share the same sentiment, use that.
  If mixed, use "mixed".
- Confidence: recompute from merged mention_count (high >= 5, medium >= 2, low < 2).
- Merge batch_stats by summing counts, weighted average for playtime, min/max for dates.
- competitor_refs: deduplicate by game name, keep the most informative context.
</rules>

<topic_dedup_rules>
- "matchmaking is slow" + "matchmaking takes too long" = ONE topic "matchmaking latency"
- "great art style" + "beautiful graphics" = ONE topic "visual design"
- "needs more maps" + "wants new content" = TWO topics (different specificity)
- When in doubt, keep separate. False merges lose information.
</topic_dedup_rules>

Return ONLY valid JSON matching the schema. No prose, no preamble.
```

### User Message (`_build_merge_user_message`)

```
<task>
Merge {n} chunk summaries for "{game_name}" into a single consolidated summary.
Total reviews: {total_reviews} across {date_range_start} – {date_range_end}.
</task>

<chunk_summaries>
{JSON array of RichChunkSummary objects}
</chunk_summaries>

<output_format>
{MergedSummary JSON schema}
</output_format>
```

### Prompt Version Constant

```python
MERGE_PROMPT_VERSION = "merge-v1.0"
```

---

## Step 7: Phase 3 — Updated Synthesis

### What Changes

The synthesis prompt (`SYNTHESIS_SYSTEM_PROMPT`) is largely unchanged. The user message
builder receives a `MergedSummary` instead of a flat aggregated dict.

Key changes in the user message:
- `<aggregated_signals>` becomes `<merged_summary>` containing structured `TopicSignal`
  objects with sentiment scores, mention counts, and confidence levels
- Add instruction: "Use topic mention_count and confidence to prioritize sections.
  Topics with confidence='high' must be addressed. Topics with confidence='low' may be
  noted if unique but should not drive priorities."
- The LLM has cleaner, deduplicated input — expect higher quality synthesis

### GameReport Output Schema

**Unchanged.** Backward compatible with the frontend. Future iterations may add a
`topic_sentiments` field with a default of `[]`.

### Python Score Computation

Unchanged in principle. Add a convenience function:

```python
def compute_sentiment_score_from_counts(positive: int, negative: int) -> float:
    total = positive + negative
    return round(positive / total, 3) if total > 0 else 0.5
```

Called from both the old `compute_sentiment_score(chunk_summaries)` and the new path
using `merged.total_stats.positive_count` / `negative_count`.

### Prompt Version Constant

```python
SYNTHESIS_PROMPT_VERSION = "synthesis-v3.0"
```

---

## Step 8: Real-Time Execution Path

The `analyze_reviews()` function in `analyzer.py` is joined by `analyze_reviews_v3()`:

```python
def analyze_reviews_v3(
    reviews: list[dict],
    game_name: str,
    appid: int,
    conn: psycopg2.extensions.connection,
    temporal: GameTemporalContext | None = None,
    metadata: GameMetadataContext | None = None,
) -> dict:
    """Three-phase LLM analysis pipeline."""
    client = _get_instructor_client()

    # Phase 1: Chunk & Summarize (with idempotency)
    chunks = stratified_chunk_reviews(reviews)
    chunk_repo = ChunkSummaryRepository(conn)
    summaries = []
    chunk_ids = []
    for i, chunk in enumerate(chunks):
        chunk_hash = compute_chunk_hash(chunk)
        existing = chunk_repo.find_by_hash(appid, chunk_hash, CHUNK_PROMPT_VERSION)
        if existing:
            summaries.append(RichChunkSummary.model_validate(existing["summary_json"]))
            chunk_ids.append(existing["id"])
        else:
            summary = _summarize_chunk_v2(client, chunk, i, len(chunks), game_name)
            row_id = chunk_repo.insert(appid, i, chunk_hash, len(chunk), summary, ...)
            summaries.append(summary)
            chunk_ids.append(row_id)

    # Phase 2: Merge
    merged = _merge_chunk_summaries(client, summaries, chunk_ids, game_name, appid)
    merged_repo = MergedSummaryRepository(conn)
    merged_id = merged_repo.insert(appid, merged, ...)

    # Python scores from merged stats
    sentiment_score = compute_sentiment_score_from_counts(
        merged.total_stats.positive_count, merged.total_stats.negative_count
    )
    hidden_gem_score = compute_hidden_gem_score(len(reviews), sentiment_score)
    sentiment_trend, sentiment_trend_note = compute_sentiment_trend(reviews)

    # Phase 3: Synthesize
    report = _synthesize_v3(client, merged, game_name, len(reviews),
                            sentiment_score, hidden_gem_score,
                            sentiment_trend, sentiment_trend_note,
                            temporal=temporal, metadata=metadata)

    # Override with Python-computed values
    report.sentiment_score = sentiment_score
    report.hidden_gem_score = hidden_gem_score
    report.sentiment_trend = sentiment_trend
    report.sentiment_trend_note = sentiment_trend_note
    if appid is not None:
        report.appid = appid

    return report.model_dump()
```

Note: `conn` parameter is new — needed for chunk storage/lookup. The analysis handler
already has `_conn` at module level.

---

## Step 9: Batch Execution Path

### Step Functions Changes

Add merge states between Pass 1 output and Pass 3 input:

```
[PreparePass1] → [SubmitPass1] → [WaitPass1] → [CheckPass1] →
[PrepareMerge] → [SubmitMerge] → [WaitMerge] → [CheckMerge] →
  Choice: needs_another_merge? → yes: [PrepareMerge] (loop)
                                → no:  continue
[PreparePass3] → [SubmitPass3] → [WaitPass3] → [CheckPass3] →
[ProcessResults]
```

### New Lambda: `prepare_merge.py`

- Input: `{execution_id, input_s3_uri (pass1 or prior merge output), merge_level}`
- Groups chunk/merge summaries by appid
- For each game, determines if hierarchical merge is needed
- Writes merge JSONL with `MERGE_SYSTEM_PROMPT`
- Returns: `{input_s3_uri, output_s3_uri, total_records, needs_another_merge: bool}`

### S3 Structure

```
jobs/{execution-id}/
  pass1/input.jsonl, output/
  merge/
    level1/input.jsonl, output/
    level2/input.jsonl, output/
  pass3/input.jsonl, scores.json, output/
```

### CDK Changes

- Add `PrepareMergeFn` Lambda to `batch_analysis_stack.py`
- Update Step Functions state machine ASL with merge loop

---

## Step 10: Replace Old Pipeline

No feature flag — there is no production environment to protect. Replace the old
`analyze_reviews()` call directly.

In `analysis/handler.py`, change the call to:

```python
result = analyze_reviews_v3(reviews_for_llm, name, appid=req.appid,
                            conn=_conn, temporal=temporal, metadata=metadata)
```

Once verified, remove the old `analyze_reviews()` function and the legacy `ChunkSummary`
model (keep `BatchStats` if still referenced elsewhere). Rename `analyze_reviews_v3()`
to `analyze_reviews()` for cleanliness.

---

## Step 11: Incremental Re-Analysis

When new reviews arrive for a game with stored chunk summaries:

1. **Detect delta**: reviews with `crawled_at` > latest `chunk_summaries.created_at`
2. **Create new chunks**: stratified chunking on new reviews only
3. **Phase 1**: run only new chunks (existing chunks loaded from DB by hash)
4. **Phase 2**: merge ALL chunk summaries (old + new) — full picture
5. **Phase 3**: synthesize from fresh merged summary

Cost savings: for a game with 40 existing chunks + 4 new review chunks, only 4 Phase 1
calls instead of 44.

---

## Step 12: Partial Failure Handling

- **Phase 1 chunk fails**: retry up to 2 times. If still failing, log and exclude.
  Merge proceeds with N-1 chunks.
- **Phase 2 merge fails**: fall back to flat aggregation (current `_aggregate_chunk_summaries`
  behavior). Lower quality but pipeline completes.
- **Phase 3 synthesis fails**: retry once. If failing, report error — do not store a
  broken report.
- Never fail an entire game's analysis due to a single chunk failure.

---

## Implementation Order

| Step | What | Dependencies |
|------|------|-------------|
| 1 | New Pydantic models in `analyzer_models.py` | None |
| 2 | `utils/chunking.py` (stratified chunking + hash) | None |
| 3 | Migrations `0012` + `0013` | None |
| 4 | Update `schema.py` | Step 3 |
| 5 | `ChunkSummaryRepository` | Steps 1, 3 |
| 6 | `MergedSummaryRepository` | Steps 1, 3 |
| 7 | Phase 1 v2 prompts + `_summarize_chunk_v2()` | Step 1 |
| 8 | Phase 2 prompts + `_merge_chunk_summaries()` | Steps 1, 5 |
| 9 | Phase 3 updated synthesis | Step 1 |
| 10 | `analyze_reviews_v3()` orchestrator | Steps 7, 8, 9 |
| 11 | Update `analysis/handler.py` to call v3 | Step 10 |
| 12 | `compute_sentiment_score_from_counts()` | None |
| 13 | Batch: `prepare_merge.py` | Steps 7, 8 |
| 14 | Batch: rename `prepare_pass2.py` → `prepare_pass3.py` | Step 9 |
| 15 | CDK: add merge Lambda + update SFN | Steps 13, 14 |
| 16 | Remove old `analyze_reviews()` + legacy models | Steps 10, 11 |
| 17 | Tests | Steps 1–12 |
| 18 | Update `ARCHITECTURE.org` | All |

---

## Verification

### Unit Tests

1. Stratified chunking: sentiment ratio preservation, playtime bucket coverage,
   helpful-vote priority, deterministic chunk hash
2. Repository CRUD: insert, find_by_hash, find_by_appid, find_latest
3. Score computation: `compute_sentiment_score_from_counts` matches existing function
4. Model validation: `RichChunkSummary`, `MergedSummary` round-trip through JSON

### Integration Tests (mocked LLM)

1. Full 3-phase pipeline: inject known chunk data → verify merge consolidation → verify
   GameReport output
2. Idempotency: run Phase 1 twice with same reviews → second run returns cached results
3. Incremental: Phase 1 with 100 reviews, then again with 150 → only 1 new chunk processed
4. Hierarchical merge: 12 chunks → verify two-level merge produces single MergedSummary

### End-to-End

1. Run `analyze_reviews_v3()` against a real game on staging
2. Compare GameReport quality vs v2 for same game
3. Verify frontend renders report identically
4. Verify `chunk_summaries` and `merged_summaries` tables are populated
5. Verify incremental re-analysis works when new reviews are added

---

## Drift Checklist

- Phase 2 model is configured via `LLM_MODEL__MERGING`, NOT hardcoded
- `chunk_summaries` unique key is `(appid, chunk_hash, prompt_version)` — NOT `(appid, chunk_index)`
- `MergedSummary` schema is a superset of `RichChunkSummary` (same topic structure)
- Python scores are ALWAYS computed in Python, never from LLM output
- `GameReport` output schema is UNCHANGED — frontend backward compatibility is mandatory
- Hierarchical merge max depth is 3 levels — never deeper
- Legacy `review_summaries` table (appid PK) is unrelated to `chunk_summaries`
- Both real-time and batch paths use the same prompt constants
- No feature flag — the 3-phase pipeline replaces the 2-pass code directly
- `steam_review_id` is included in review text sent to LLM for quote attribution
- Batch path gains merge loop states in Step Functions ASL
- S3 structure gains `merge/level{N}/` directories
