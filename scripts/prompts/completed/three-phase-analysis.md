# Three-Phase LLM Analysis Pipeline

> **Updated post-data-source-clarity refactor.** Sentiment magnitude is owned by Steam
> (`positive_pct` / `review_score_desc` on the `Game` row). The `GameReport` no longer
> contains `sentiment_score` or `overall_sentiment`. The only Python-computed numeric
> values still overwritten on the report are `hidden_gem_score` (now derived from
> Steam's positive_pct + review_count, not from sampled batch_stats) and the
> `sentiment_trend*` fields (a window comparison, not a magnitude). See
> `scripts/prompts/data-source-clarity.md` for the full rationale.

---

## Errata — bookkeeping races found during PR review

Two concurrency gaps were identified after the initial implementation landed.
Both are corrections to the spec's own "no races on bookkeeping" promise — fix
them in the same branch before merging.

### E1. `run_merge_phase` root verification races with concurrent re-analysis

**Symptom.** At the end of `run_merge_phase` (`library_layer/analyzer.py`,
post-loop verification block) the code re-reads the root via
`merge_repo.find_latest_by_appid(appid)` and asserts the returned row id
equals `last_row_id`. `find_latest_by_appid` orders by
`(merge_level DESC, created_at DESC)` — it returns "the latest row for this
appid", not "the row we just inserted". Any concurrent invocation for the
same appid (admin reanalyze racing bulk seed, SFN retry overlapping a
realtime call) that inserts a merge row between our last insert and this
read flips the assertion into a spurious `RuntimeError` on an otherwise
clean run.

**Fix.**
1. Add `MergedSummaryRepository.find_by_id(merge_id: int) -> dict | None` —
   a plain `SELECT ... WHERE id = %s`. This is the race-free lookup.
2. In `run_merge_phase`, replace the `find_latest_by_appid` + id-equality
   check with `merge_repo.find_by_id(last_row_id)`. If it's `None`, that's
   a real consistency bug and should raise; otherwise return the hydrated
   `MergedSummary` from that exact row.
3. Do **not** trust `last_row_id` without re-reading — we still want the
   canonical server-side shape (with `merge_level`, `chunks_merged`,
   `source_chunk_ids` as the repo stored them) rather than the in-memory
   `response` object we mutated before insert.

**Test.** Add a case to `tests/services/test_analyzer_three_phase.py` that
inserts a higher-`merge_level` row for the SAME appid between the last
per-group insert and the verification read (monkeypatch or a spy on the
repo) and asserts `run_merge_phase` still returns the correct root.

### E2. Batch `collect_phase` recomputes `chunk_count` from live DB

**Symptom.** `lambda_functions/batch_analysis/collect_phase.py::_collect_synthesis`
sets `payload["chunk_count"] = len(_chunk_repo.find_by_appid(appid, CHUNK_PROMPT_VERSION))`.
The spec already threads `merged_summary_id` through SFN state (captured
at prepare-synthesis time) specifically to avoid "the set of persisted
artifacts changed between prepare and collect" races. `chunk_count` has
the identical failure mode: a concurrent re-analyze (or a CHUNK_PROMPT_VERSION
bump landing between prepare and collect) can inflate or shrink the count
so the stored value no longer reflects what the synthesis actually saw.

**Fix.** Thread `chunk_count` through SFN state the same way
`merged_summary_id` is threaded today.

1. In `prepare_phase._prepare_synthesis`: compute `chunk_count` from the
   `_chunk_repo.find_by_appid(appid, CHUNK_PROMPT_VERSION)` result that
   already drives merge-lookup, and return it in the output payload
   alongside `merged_summary_id`.
2. In `collect_phase.handler`: pull `event.get("chunk_count")` the same
   way `merged_summary_id` is pulled.
3. In `collect_phase._collect_synthesis`: accept `chunk_count: int | None`
   as a required parameter (no default), assign it into `payload["chunk_count"]`,
   and **remove the `find_by_appid(...)` re-query entirely**.
4. Update `infra/stacks/batch_analysis_stack.py` so the Step Functions
   state machine passes `chunk_count` through the synthesis prepare →
   collect transition. If `merged_summary_id` is already passed via
   `ResultSelector` / `Parameters`, extend the same path.

**Test.** Update `tests/handlers/test_collect_phase.py` so the synthesis
collect test asserts the stored `chunk_count` came from the event payload,
not from a live repo call. The existing merged_summary_id test is the
template.

### Non-goal

The third PR-review finding (`metadata=None` at both call sites — lost
`store_page_alignment` + metadata context block) is a **missing feature**,
not a race. It is tracked in its own spec at
`scripts/prompts/metadata-context-wiring.md` and must land in this same
branch before merge.

---

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
│  1 chunk:   promotion, no LLM call (persisted)   │
│  ≤N chunks: single merge call (N = config knob)  │
│  >N chunks: hierarchical recursion, source ids   │
│             threaded transitively through levels │
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

Both execution modes (real-time via Converse and batch via Bedrock Batch Inference) run the
**same three phases against the same Postgres tables with the same prompts**. The only
difference between modes is *how* an `LLMRequest` becomes a parsed pydantic response.

### Unified framework design

The entry point is a typed `AnalysisRequest` (new in `library_layer/events.py`):

```python
class AnalysisRequest(BaseSqsMessage):
    message_type: SqsMessageType = "analysis_request"
    appid: int
    mode: Literal["realtime", "batch"] = "realtime"
    reason: str | None = None       # "bulk_seed" | "stale_refresh" | "admin_reanalyze" | ...
```

Triggers (admin re-analyze, bulk seed, scheduled refresh) construct an `AnalysisRequest`
and hand it to the dispatcher. No HTTP endpoint is involved — in particular **`/api/preview`
is deleted** as part of this work (backend handler, rate limiter, frontend form, e2e specs).

Two distinct seams sit under the shared analyzer — **no pretending batch is sync, no
exceptions-as-control-flow**:

```
┌─────────────────── shared pure helpers (analyzer.py) ──────────────────┐
│ stratified_chunk_reviews, compute_chunk_hash,                           │
│ build_chunk_requests, plan_merge_hierarchy, build_synthesis_request,    │
│ prompt constants, prompt versions, pydantic response models,            │
│ ChunkSummaryRepository / MergedSummaryRepository persistence,           │
│ compute_hidden_gem_score, compute_sentiment_trend, Python overrides.    │
└─────────────────────────────────────────────────────────────────────────┘
            │                                        │
            ▼                                        ▼
   ConverseBackend (sync)                  BatchBackend (explicit lifecycle)
   def run(requests) -> list[BaseModel]    def prepare(requests) -> s3_uri
                                            def submit(s3_uri, task) -> job_id
                                            def status(job_id) -> "running"|"completed"|"failed"
                                            def collect(job_id, models) -> list[BaseModel]
```

`ConverseBackend.run()` blocks and returns parsed pydantic objects; used by the realtime
Lambda. `BatchBackend` does **not** implement `run()` — Step Functions Lambdas call
`prepare/submit/status/collect` across multiple invocations, and "job still pending" is
Step Functions state (Wait → Choice loop), never a Python exception.

**All code is plain sync `def`.** No `async`/`await`. psycopg2, instructor, and boto3 are
all sync; async adds no concurrency on Lambda and just clutters signatures. The only
parallelism is a thread pool inside `ConverseBackend.run()` for chunk fan-out.

```python
# library_layer/llm/backend.py
class LLMRequest(BaseModel):
    record_id: str                    # "{appid}-chunk-{i}" | "{appid}-merge-L{n}" | "{appid}-synthesis"
    task: Literal["chunking", "merging", "summarizer"]
    system: str
    user: str
    max_tokens: int
    response_model: type[BaseModel]   # RichChunkSummary | MergedSummary | GameReport

class LLMBackend(Protocol):
    mode: Literal["realtime", "batch"]
```

Models are chosen per request via `config.model_for(request.task)` — one place to swap
Haiku/Sonnet/Opus per phase.

### Tuning knobs: explicit everywhere, no defaults in helpers

**No function in the three-phase pipeline carries default values** for
tuning knobs (chunk size, token budgets, merge group size, thread pool,
shuffle seed, review cap). Every knob lives in exactly one place —
`SteamPulseConfig` — and flows down through an `AnalyzerSettings`
pydantic bundle constructed at the handler:

```python
# library_layer/analyzer.py
class AnalyzerSettings(BaseModel):
    chunk_size: int = Field(gt=0)
    max_chunks_per_merge_call: int = Field(gt=0)   # per-call context bound
    chunk_max_tokens: int = Field(gt=0)
    merge_max_tokens: int = Field(gt=0)
    synthesis_max_tokens: int = Field(gt=0)
    shuffle_seed: int

    @classmethod
    def from_config(cls, config: SteamPulseConfig) -> "AnalyzerSettings": ...
```

Handlers read `SteamPulseConfig` once, build an `AnalyzerSettings`, and
pass it (plus `reference_time`, computed via
`library_layer.utils.chunking.dataset_reference_time(reviews)`) into
`analyze_game`. Every phase helper — `run_chunk_phase`, `run_merge_phase`,
`run_synthesis_phase`, `build_chunk_requests`, `build_merge_request`,
`build_synthesis_request` — takes the relevant knobs as required
keyword arguments. Misconfiguration fails loudly at the handler boundary,
never silently inside a helper.

Config fields (defined in `SteamPulseConfig`):

| Config field                           | Default | Purpose |
|----------------------------------------|---------|---------|
| `ANALYSIS_MAX_REVIEWS`                 | 2000    | reviews loaded per game |
| `ANALYSIS_CHUNK_SIZE`                  | 50      | reviews per Phase 1 chunk |
| `ANALYSIS_MAX_CHUNKS_PER_MERGE_CALL`   | 40      | per-call LLM context-budget limit (NOT a review-count limit — larger counts recurse hierarchically) |
| `ANALYSIS_CHUNK_MAX_TOKENS`            | 1024    | Bedrock max_tokens per chunk call |
| `ANALYSIS_MERGE_MAX_TOKENS`            | 4096    | per merge call |
| `ANALYSIS_SYNTHESIS_MAX_TOKENS`        | 5000    | per synthesis call |
| `ANALYSIS_CONVERSE_MAX_WORKERS`        | 8       | ConverseBackend chunk-phase fan-out thread pool |
| `ANALYSIS_CHUNK_SHUFFLE_SEED`          | 42      | deterministic in-chunk shuffle seed |

All of these are overridable via `.env.{environment}`. No other location
in the codebase hardcodes these values.

---

## Codebase Orientation

### Files to Modify

- **Models**: `src/library-layer/library_layer/models/analyzer_models.py` — adds `TopicSignal`, `ReviewQuote`, `RichBatchStats`, `RichChunkSummary`, `MergedSummary`; deletes legacy `ChunkSummary`/`BatchStats`.
- **Analyzer**: `src/library-layer/library_layer/analyzer.py` — v2 chunk prompt + new merge prompt, `AnalyzerSettings` pydantic bundle, `analyze_game()` single entry point, `run_chunk_phase` / `run_merge_phase` / `run_synthesis_phase`, pure request builders (`build_chunk_requests`, `build_merge_request`, `build_synthesis_request`), `parse_chunk_record_id()` helper for the batch collect path.
- **Scores**: `src/library-layer/library_layer/utils/scores.py` — unchanged; `compute_hidden_gem_score(positive_pct, review_count)` and `compute_sentiment_trend(reviews) -> dict` already exist post-data-source-clarity.
- **Config**: `src/library-layer/library_layer/config.py` — adds `LLM_MODEL__MERGING` plus the `ANALYSIS_*` tuning-knob fields (`ANALYSIS_MAX_REVIEWS`, `ANALYSIS_CHUNK_SIZE`, `ANALYSIS_MAX_CHUNKS_PER_MERGE_CALL`, `ANALYSIS_CHUNK_MAX_TOKENS`, `ANALYSIS_MERGE_MAX_TOKENS`, `ANALYSIS_SYNTHESIS_MAX_TOKENS`, `ANALYSIS_CONVERSE_MAX_WORKERS`, `ANALYSIS_CHUNK_SHUFFLE_SEED`).
- **Schema**: `src/library-layer/library_layer/schema.py` — mirrors the new `chunk_summaries` / `merged_summaries` tables and the three new `reports` bookkeeping columns.
- **ReportRepository**: `src/library-layer/library_layer/repositories/report_repo.py` — `upsert` writes `pipeline_version` / `chunk_count` / `merged_summary_id` to dedicated columns (stripping them from `report_json`), with `COALESCE` on UPDATE so absent keys preserve existing values.
- **Analysis handler**: `src/lambda-functions/lambda_functions/analysis/handler.py` — constructs `AnalyzerSettings.from_config()` + module-level `ConverseBackend`, reads `ANALYSIS_MAX_REVIEWS` per invocation, derives `reference_time` from the dataset, calls `analyze_game()`.
- **Batch handlers**: `src/lambda-functions/lambda_functions/batch_analysis/prepare_phase.py` + `collect_phase.py` (parametrized on `event["phase"]`); `check_batch_status.py` (thinned). Old `prepare_pass1.py`, `prepare_pass2.py`, `process_results.py`, `submit_batch_job.py` are **deleted**.
- **API handler**: `src/lambda-functions/lambda_functions/api/handler.py` — `/api/preview`, `/api/status/{job_id}`, and all job/preview plumbing removed.
- **CDK**: `infra/stacks/batch_analysis_stack.py` — three Lambdas (`PreparePhaseFn`, `CollectPhaseFn`, `CheckBatchStatusFn`) and a Step Functions state machine built from a `_phase_chain(phase, next_step)` helper. No merge loop (merge runs inline via ConverseBackend).

### Files to Create

- `src/library-layer/library_layer/llm/backend.py` — `LLMRequest` + `LLMBackend` protocol
- `src/library-layer/library_layer/llm/converse.py` — `ConverseBackend` (required `max_workers`, `as_completed` fan-out with cancel-on-error)
- `src/library-layer/library_layer/llm/batch.py` — `BatchBackend` with `prepare/submit/status/collect` + `_safe_job_name` (sanitized + SHA1-truncated) + paginated S3 collect
- `src/library-layer/library_layer/utils/chunking.py` — `stratified_chunk_reviews`, `dataset_reference_time`, `compute_chunk_hash` (all required keyword args, no defaults)
- `src/library-layer/library_layer/repositories/chunk_summary_repo.py` — CRUD for `chunk_summaries`
- `src/library-layer/library_layer/repositories/merged_summary_repo.py` — CRUD for `merged_summaries` + `find_latest_by_source_ids`
- `src/lambda-functions/migrations/0035_chunk_summaries.sql` — new table
- `src/lambda-functions/migrations/0036_merged_summaries.sql` — new table + reports bookkeeping columns
- `src/lambda-functions/lambda_functions/batch_analysis/prepare_phase.py` — single parametrized prepare Lambda
- `src/lambda-functions/lambda_functions/batch_analysis/collect_phase.py` — single parametrized collect Lambda
- Tests: `tests/utils/test_chunking.py`, `tests/llm/test_batch_jsonl.py`, `tests/services/test_analyzer_three_phase.py`, plus repository tests under `tests/repositories/`

### Files to Delete

- `src/lambda-functions/lambda_functions/batch_analysis/prepare_pass1.py`
- `src/lambda-functions/lambda_functions/batch_analysis/prepare_pass2.py`
- `src/lambda-functions/lambda_functions/batch_analysis/process_results.py`
- `src/lambda-functions/lambda_functions/batch_analysis/submit_batch_job.py`
- `src/library-layer/library_layer/services/analysis_service.py` (dead wrapper around the legacy two-pass `analyze_reviews()`)
- Legacy `analyze_reviews()`, `_summarize_chunk`, `_synthesize`, `_aggregate_chunk_summaries` in `analyzer.py`
- Legacy `ChunkSummary`/`BatchStats` in `analyzer_models.py`
- `POST /api/preview` + `GET /api/status/{job_id}` + related frontend (`getPreview`, `pollStatus`, `waitForReport`, `PreviewResponse`, `JobStatus`) and e2e mock routes

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

**Scores computed in Python**: `hidden_gem_score` and the `sentiment_trend*` fields are
ALWAYS computed in Python and override LLM output. **Sentiment magnitude
(`positive_pct` / `review_score_desc`) is owned by Steam** and read directly from the
`Game` row — never recomputed from the local review sample. The `GameReport` no longer
contains `sentiment_score` or `overall_sentiment`.

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
    """A structured topic extracted from a chunk of reviews.

    NOTE on `sentiment`: this is a per-TOPIC tag, not a game-wide sentiment score.
    Game-wide sentiment magnitude is owned by Steam (`positive_pct` /
    `review_score_desc` on the Game row) and is never derived from these tags.
    The topic-level tag is only used to render Topic cards in the UI and to
    weight signals during merge.
    """
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
    merge_level: int = 0                # 0=single-chunk promotion, 1+=LLM merge levels
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
   - Apply 1.5x multiplier to votes_helpful for reviews posted within
     90 days of `reference_time` (sort key only — does not modify the
     stored vote count)
3. Compute target_positive_ratio = len(positive) / len(all_reviews)
4. For each chunk of `chunk_size` (passed from config):
   a. Draw ceil(chunk_size * target_positive_ratio) from positive pool
   b. Draw remainder from negative pool
   c. If a pool is exhausted, fill from the other
   d. Drain any leftover reviews into the last chunk (rounding fill)
   e. Shuffle the assembled chunk with the explicit `seed` parameter
5. Return list of chunks

Partition invariant: every input review appears in exactly one output
chunk. The input list is not mutated.

Note: the earlier "playtime bucket coverage" constraint was removed. It
had a correctness bug (could duplicate reviews across chunks) and the
simpler partition-only behavior is correct.
```

### Reference time

The 90-day recency window needs a "now" anchor. `stratified_chunk_reviews`
does NOT call `datetime.now()` — it requires callers to pass a
`reference_time` explicitly so chunk hashes and cache lookups stay
reproducible across wall-clock time.

Callers typically derive it from the dataset itself:

```python
def dataset_reference_time(reviews: list[dict]) -> datetime:
    """Return max(posted_at) across reviews. Raises ValueError if no
    review carries a parseable posted_at — NO silent epoch fallback."""
```

### Chunk Hash

```python
def compute_chunk_hash(reviews: list[dict]) -> str:
    """Deterministic 16-char hex hash over sorted steam_review_id values.

    Raises ValueError if any review is missing `steam_review_id`. We do
    NOT fall back to an empty string placeholder — that would collide
    across different missing-id reviews and cause wrong cache hits.
    """
```

Same reviews in any order = same hash. Adding/removing a review changes the hash.

### Exports

```python
def stratified_chunk_reviews(
    reviews: list[dict],
    *,
    chunk_size: int,           # required — from SteamPulseConfig.ANALYSIS_CHUNK_SIZE
    reference_time: datetime,  # required — from dataset_reference_time(reviews)
    seed: int,                 # required — from SteamPulseConfig.ANALYSIS_CHUNK_SHUFFLE_SEED
) -> list[list[dict]]:
def dataset_reference_time(reviews: list[dict]) -> datetime:
def compute_chunk_hash(reviews: list[dict]) -> str:
```

**No defaults on any parameter.** Callers must pass every value explicitly.

---

## Step 3: Database Migrations

### `0035_chunk_summaries.sql`

```sql
-- depends: 0034_new_releases_matview

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

### `0036_merged_summaries.sql`

```sql
-- depends: 0035_chunk_summaries

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

**Reflects post-data-source-clarity shape.** No `sentiment_score`, no `overall_sentiment`,
`refund_risk` is now `refund_signals`, `ContentDepth` carries `confidence` + `sample_size`,
and `sentiment_trend_reliable` / `sentiment_trend_sample_size` are present. Future
iterations may add a `topic_sentiments` field with a default of `[]` to expose the
merged `TopicSignal` list to the frontend Topics tab. The frontend already consumes
Steam's `positive_pct` / `review_score_desc` from the `Game` row joined at the API
layer — do not reintroduce these into the report.

### Python Score Computation

The synthesis call must be passed Steam's canonical sentiment numbers as context (so
the LLM frames its narrative consistent with Steam's verdict) and the Python-computed
`hidden_gem_score`:

```python
hidden_gem_score = compute_hidden_gem_score(
    positive_pct=game.positive_pct,    # Steam, from games row
    review_count=game.review_count,    # Steam, from games row
)
trend = compute_sentiment_trend(reviews)  # returns dict{trend, note, reliable, sample_size}
```

`merged.total_stats.positive_count` / `negative_count` are kept for diagnostics and to
let the LLM see the local sample distribution, but they MUST NOT be used to compute
any sentiment magnitude shown to the user — Steam's `positive_pct` is the only number.
There is no `compute_sentiment_score_from_counts()` helper and one must not be added.

### Prompt Version Constant

```python
SYNTHESIS_PROMPT_VERSION = "synthesis-v3.0"
```

---

## Step 8: Real-Time Execution Path

The single entry point is `analyze_game()` in `analyzer.py`. Every
tuning knob is required and passed in explicitly — no defaults anywhere.

```python
def analyze_game(
    request: AnalysisRequest,
    *,
    backend: LLMBackend,
    chunk_repo: ChunkSummaryRepository,
    merge_repo: MergedSummaryRepository,
    report_repo: ReportRepository,
    reviews: list[dict],
    game_name: str,
    settings: AnalyzerSettings,
    reference_time: datetime,
    temporal: GameTemporalContext | None,
    metadata: GameMetadataContext | None,
    steam_positive_pct: int | float | None,
    steam_review_count: int | None,
    steam_review_score_desc: str | None,
) -> GameReport:
    """The one entry point. Identical for realtime and batch.

    Sentiment magnitude is owned by Steam — `positive_pct` / `review_score_desc`
    flow from the `Game` row via required params and NEVER get recomputed from
    merged.total_stats. `settings` bundles all tuning knobs from
    `SteamPulseConfig`. `reference_time` is derived by the caller via
    `dataset_reference_time(reviews)`.
    """
```

### Phase helpers — every knob required

```python
def run_chunk_phase(
    *,
    appid: int,
    game_name: str,
    reviews: list[dict],
    backend: LLMBackend,
    chunk_repo: ChunkSummaryRepository,
    chunk_size: int,
    reference_time: datetime,
    shuffle_seed: int,
    chunk_max_tokens: int,
) -> tuple[list[RichChunkSummary], list[int]]:
    """Cache-check via chunk_hash → build LLMRequests for misses →
    backend.run() → persist. Returns (summaries, row_ids) in chunk order."""


def run_merge_phase(
    *,
    appid: int,
    game_name: str,
    chunk_summaries: list[RichChunkSummary],
    chunk_ids: list[int],
    backend: LLMBackend,
    merge_repo: MergedSummaryRepository,
    max_chunks_per_merge_call: int,   # per-call context budget
    merge_max_tokens: int,
) -> tuple[MergedSummary, int | None]:
    """Hierarchical merge. Groups of at most `max_chunks_per_merge_call`
    inputs per LLM call; recurses until one summary remains.

    Single-chunk input → promotion (no LLM call) but STILL persists a
    merge_level=0, model_id="python-promotion" row so downstream
    consumers never see a stale row from a previous analysis run.

    At every level, each group's `source_chunk_ids` is the UNION of
    leaf chunk row ids the group's inputs transitively derive from.
    This is server-computed — the LLM is never trusted for it.
    find_latest_by_source_ids cache-checks at every level.

    Returns (root_merged_summary, root_row_id). row_id is non-None for
    any analysis run that touches the DB (promotion included)."""


def run_synthesis_phase(
    *,
    appid: int,
    game_name: str,
    merged: MergedSummary,
    total_reviews: int,
    reviews: list[dict],
    steam_positive_pct: int | float | None,
    steam_review_count: int | None,
    steam_review_score_desc: str | None,
    temporal: GameTemporalContext | None,
    metadata: GameMetadataContext | None,
    backend: LLMBackend,
    synthesis_max_tokens: int,
) -> GameReport:
    """One backend.run() call. Python computes hidden_gem_score from
    Steam's positive_pct + review_count and overrides the field on the
    LLM output. sentiment_trend fields are similarly overridden. Steam
    owns sentiment magnitude; Python owns derived scores."""
```

### Realtime Lambda wiring

`lambda_functions/analysis/handler.py` reads `SteamPulseConfig` once at
module level, builds the `AnalyzerSettings` bundle + `ConverseBackend`,
then per-invocation loads reviews, computes `reference_time`, and calls
`analyze_game` with every value explicit:

```python
_analyzer_settings = AnalyzerSettings.from_config(_analysis_config)
_backend = ConverseBackend(
    _analysis_config,
    max_workers=_analysis_config.ANALYSIS_CONVERSE_MAX_WORKERS,
)

# inside handler():
max_reviews = _analysis_config.ANALYSIS_MAX_REVIEWS
db_reviews = _review_repo.find_by_appid(req.appid, limit=max_reviews)
reviews_for_llm = [_review_to_dict(r) for r in db_reviews if r.body]
reference_time = dataset_reference_time(reviews_for_llm)

report = analyze_game(
    analysis_req,
    backend=_backend,
    chunk_repo=_chunk_repo,
    merge_repo=_merge_repo,
    report_repo=_report_repo,
    reviews=reviews_for_llm,
    game_name=name,
    settings=_analyzer_settings,
    reference_time=reference_time,
    temporal=temporal,
    metadata=None,
    steam_positive_pct=...,
    steam_review_count=...,
    steam_review_score_desc=...,
)
```

`ConverseBackend.__init__` takes `max_workers` as a **required** keyword
arg — no default. The handler is responsible for reading it from config.

---

## Step 9: Batch Execution Path

Batch mode runs the **same** `run_chunk_phase` / `run_merge_phase` /
`run_synthesis_phase` helpers as realtime — just driven across multiple Lambda
invocations by Step Functions. Each Prepare/Collect Lambda is a thin wrapper
that instantiates `BatchBackend` and calls the shared helpers. No
exceptions-as-control-flow: job pending vs. complete is Step Functions state.

### Step Functions (STANDARD) state machine

```
StartAnalysis (receives AnalysisRequest with mode="batch", per-appid execution)
  ├─ PrepareChunkPhase   → shared run_chunk_phase helpers to build requests,
  │                        filter DB cache hits (insert them immediately),
  │                        BatchBackend.prepare(pending) → s3_uri
  │                        BatchBackend.submit(s3_uri, "chunking") → job_id
  │                        returns {job_id, appid}
  ├─ WaitChunk + CheckChunkStatus → BatchBackend.status(job_id) loop
  ├─ CollectChunkPhase   → BatchBackend.collect(job_id, default_response_model=
  │                        RichChunkSummary) → chunk_repo.insert() for each
  ├─ PrepareMergePhase   → runs merge INLINE via ConverseBackend (see below);
  │                        always returns skip=true, short-circuiting the
  │                        wait/check loop. No batch submission for merge.
  ├─ PrepareSynthesisPhase → loads merged_summaries.find_latest_by_appid(),
  │                          Python scores, build_synthesis_request(),
  │                          BatchBackend.prepare/submit → {job_id}
  ├─ WaitSynth/CheckSynth
  └─ CollectSynthAndPersist → BatchBackend.collect() → apply Python overrides →
                              report_repo.upsert(pipeline_version=..., chunk_count=...,
                                                 merged_summary_id=...)
                              publish_report_ready(appid)
```

### Why merge runs inline via ConverseBackend in the batch path

Bedrock Batch Inference amortizes a fixed per-job cost across many
records; merge has at most a handful (one LLM call per group per level,
bounded by `ANALYSIS_MAX_CHUNKS_PER_MERGE_CALL`). Running merge inline
via `ConverseBackend` from within `prepare_phase.py`:

- Shares the **one** `run_merge_phase` implementation with realtime —
  hierarchical merge behavior and `source_chunk_ids` tracking cannot
  drift between paths.
- Eliminates the need for a per-level Step Functions loop with `level`
  plumbing and per-level source-id sidecar files on S3.
- Runs in seconds per LLM call; even a large game with multi-level
  hierarchy completes well within a Lambda timeout.

The Step Functions state machine therefore treats merge as a phase that
ALWAYS reports `skip=true` and transitions directly to synthesis.

### Lambda wrappers

Every batch Lambda is a thin adapter. Key property: **all prompt strings,
chunking, merge hierarchy, synthesis user builder, Python scores, and
persistence are imported from `library_layer/analyzer.py`**. Batch Lambdas
contain zero prompt text of their own — drift between realtime and batch is
impossible. Every tuning knob is read from `SteamPulseConfig` at module
level into an `AnalyzerSettings` bundle and passed explicitly into every
call; no hardcoded `MAX_REVIEWS = 2000` or similar constants anywhere.

Two parametrized handlers instead of six per-phase Lambdas:

- `prepare_phase.py` — dispatches on `event["phase"]`:
  - `"chunk"`: build chunk requests, submit Bedrock batch job, return job_id
  - `"merge"`: run `run_merge_phase` inline via ConverseBackend, return skip=true
  - `"synthesis"`: build synthesis request, submit Bedrock batch job, return job_id
- `collect_phase.py` — dispatches on `event["phase"]`:
  - `"chunk"`: collect batch output, persist `chunk_summaries` rows
  - `"synthesis"`: collect batch output, apply Python overrides, upsert
    `reports` with `pipeline_version` / `chunk_count` / `merged_summary_id`
  - `"merge"`: never routed here (prepare handles it inline)
- `check_batch_status.py` — thin status-poller shared by all phases

### CDK Changes

- `infra/stacks/batch_analysis_stack.py`: three Lambdas
  (`PreparePhaseFn`, `CollectPhaseFn`, `CheckBatchStatusFn`) and a
  Step Functions state machine built from a `_phase_chain(phase,
  next_step)` helper per phase. Merge's chain short-circuits on
  `skip=true` and never enters its wait/check loop at runtime.

---

## Step 10: Replace Old Pipeline + Delete `/api/preview`

No feature flag — there is no production environment to protect.

1. **Delete `/api/preview`** entirely:
   - `POST /api/preview` handler and `_trigger_analysis` helper in
     `lambda_functions/api/handler.py`
   - Free-preview rate-limit logic (grep first — remove table/row code if
     preview is the only caller)
   - Frontend preview CTA/form/page and related e2e specs
   - `AnalysisMachine` EXPRESS Step Function if it only served preview; if
     it's retained for admin re-analyze, repoint it at the new
     `analyze_game(request, ...)` path
2. In `lambda_functions/analysis/handler.py`, parse the incoming
   `AnalysisRequest` from the event, instantiate `ConverseBackend` at module
   level, and call `analyze_game(request, backend=_converse, ...)`.
3. Remove the old two-pass `analyze_reviews()` function and the legacy
   `ChunkSummary` model (keep `BatchStats` only if referenced elsewhere).

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
| 3 | Migrations `0035` + `0036` | None |
| 4 | Update `schema.py` | Step 3 |
| 5 | `ChunkSummaryRepository` | Steps 1, 3 |
| 6 | `MergedSummaryRepository` | Steps 1, 3 |
| 7 | Phase 1 v2 prompts + `_summarize_chunk_v2()` | Step 1 |
| 8 | Phase 2 prompts + `_merge_chunk_summaries()` | Steps 1, 5 |
| 9 | Phase 3 updated synthesis | Step 1 |
| 10 | `llm/{backend,converse,batch}.py` + `AnalysisRequest` in `events.py` | Step 1 |
| 11 | `analyze_game()` + `run_{chunk,merge,synthesis}_phase()` orchestrator | Steps 7, 8, 9, 10 |
| 12 | Update `analysis/handler.py` to parse `AnalysisRequest` + call `analyze_game` with `ConverseBackend` | Step 11 |
| 13 | Delete `/api/preview` (backend + frontend + e2e specs) | Step 12 |
| 14 | Two parametrized batch Lambdas: `prepare_phase.py` + `collect_phase.py`, dispatched on `event["phase"]`. Thin wrappers over shared analyzer helpers; merge runs inline via module-level ConverseBackend and always returns `skip=true`. | Steps 10, 11 |
| 15 | CDK: `PreparePhaseFn` + `CollectPhaseFn` + `CheckBatchStatusFn` + `_phase_chain` SFN helper (no merge loop). | Step 14 |
| 16 | Remove old two-pass `analyze_reviews()` + legacy `ChunkSummary` | Steps 11, 12 |
| 17 | Tests | Steps 1–12 |
| 18 | Update `ARCHITECTURE.org` | All |

---

## Verification

### Unit Tests

1. Stratified chunking: sentiment ratio preservation, partition invariant (every input review appears in exactly one chunk), deterministic chunk hash (order-insensitive, raises on missing `steam_review_id`), reproducibility with a fixed `reference_time`, and `_sort_key` recency-multiplier guard against future-dated reviews.
2. Repository CRUD: insert, `find_by_hash`, `find_by_appid`, `find_latest_by_source_ids`, `find_latest_by_appid`.
3. `ChunkSummaryRepository.upsert` idempotency (ON CONFLICT returns canonical id).
4. Model validation: `RichChunkSummary`, `MergedSummary`, `GameReport` round-trip through JSON.
5. `AnalyzerSettings.from_config()` exercises every field (cold-start typo guard).

### Integration Tests (mocked LLM)

1. Full 3-phase pipeline: inject known chunk data → verify merge consolidation → verify
   GameReport output
2. Idempotency: run Phase 1 twice with same reviews → second run returns cached results
3. Incremental: Phase 1 with 100 reviews, then again with 150 → only 1 new chunk processed
4. Hierarchical merge: 12 chunks → verify two-level merge produces single MergedSummary

### End-to-End

1. Invoke the realtime `analysis` Lambda with a real appid on staging — this drives the entire `analyze_game()` pipeline end-to-end
2. Compare GameReport quality vs v2 for same game
3. Verify frontend renders report identically
4. Verify `chunk_summaries` and `merged_summaries` tables are populated
5. Verify incremental re-analysis works when new reviews are added

---

## Drift Checklist

- Phase 2 model is configured via `LLM_MODEL__MERGING`, NOT hardcoded
- `chunk_summaries` unique key is `(appid, chunk_hash, prompt_version)` — NOT `(appid, chunk_index)`
- `MergedSummary` schema is a superset of `RichChunkSummary` (same topic structure)
- `hidden_gem_score` and `sentiment_trend*` are ALWAYS computed in Python and overwritten on the report — never from LLM output
- **Sentiment magnitude is owned by Steam.** `positive_pct` / `review_score_desc` come from the `Game` row and are NEVER recomputed from `merged.total_stats`. Do not reintroduce `sentiment_score` or `overall_sentiment` to `GameReport`. Do not add `compute_sentiment_score_from_counts()`.
- The synthesis prompt receives Steam's `positive_pct` as canonical context (`steam_positive_pct` parameter on the user-message builder) so the LLM frames its narrative consistently
- `GameReport` output schema reflects the post-data-source-clarity shape: `refund_signals` (not `refund_risk`), `ContentDepth` has `confidence` + `sample_size`, `sentiment_trend_reliable` + `sentiment_trend_sample_size` are present
- **Hierarchical merge is bounded by `ANALYSIS_MAX_CHUNKS_PER_MERGE_CALL` (a per-call LLM context-budget limit, not a review-count limit).** Any chunk count works — the phase recurses until a single root remains. No hardcoded level cap.
- **`source_chunk_ids` at every merge level is server-computed as the union of the inputs' leaf chunk row ids.** The LLM is NEVER trusted to populate this field. The merge prompt's own `chunks_merged` / `merge_level` are likewise overwritten server-side.
- **Every analysis run persists at least one `merged_summaries` row**, including the single-chunk promotion case (`merge_level=0`, `model_id="python-promotion"`). Without this, batch synthesis would read a stale row from a previous run via `find_latest_by_appid`.
- Legacy `review_summaries` table (appid PK) is unrelated to `chunk_summaries`
- Both real-time and batch paths use the same prompt constants
- No feature flag — the 3-phase pipeline replaces the 2-pass code directly
- `steam_review_id` is **required** on every review — `compute_chunk_hash` raises `ValueError` on missing ids rather than collapsing to an empty-string placeholder
- `stratified_chunk_reviews` takes `reference_time` explicitly (no `datetime.now()` anchor). Callers compute it via `dataset_reference_time(reviews)` which returns `max(posted_at)` or raises — NO silent epoch fallback.
- **Single entry point is `analyze_game(request: AnalysisRequest, *, backend, repos, settings, reference_time, ...)`** — not a mode-specific function per execution mode. Every tuning knob is required explicit.
- **`LLMBackend.run()` is sync-only** and implemented only by `ConverseBackend`. `BatchBackend` exposes `prepare/submit/status/collect` — it does NOT implement `run()`. Do not add an async `run()` or a "pending" exception — job-pending state lives in Step Functions
- **No `async`/`await` anywhere** in analyzer, backends, handlers, or repos. psycopg2, instructor, and boto3 Bedrock clients are all sync. `ConverseBackend.run()` may use a thread pool for chunk fan-out; that is the only parallelism
- **`/api/preview` is deleted** — analysis is driven by `AnalysisRequest` (SQS/Step Functions), not by an HTTP endpoint. Do not reintroduce preview
- Batch Lambdas import prompts/chunking/merge/synthesis/persistence from `library_layer/analyzer.py` — they contain zero prompt strings of their own
- **No defaults in function signatures.** Tuning knobs, bounds, token budgets, max_workers, chunk sizes, seeds — ALL required keyword args. Defaults live in exactly one place: `SteamPulseConfig` (fields prefixed `ANALYSIS_*`). Handlers read config, build `AnalyzerSettings.from_config()`, pass values explicitly down the call chain. See the `Tuning knobs` section for the full list.
- **Batch merge runs inline via `ConverseBackend`**, not Bedrock Batch Inference. `prepare_phase._prepare_merge` always returns `skip=true`; `collect_phase` never routes a merge event. One correct hierarchical implementation shared between realtime and batch — no SFN merge loop, no per-level S3 sidecar plumbing.
- `ReportRepository.upsert` writes `pipeline_version`, `chunk_count`, `merged_summary_id` to dedicated columns (0036 migration); these are stripped from the `report_json` JSONB blob so the JSON stays a pure `GameReport`.
- `BatchBackend.submit` uses `_safe_job_name(execution_id, phase)` — sanitized + SHA-1-truncated to ≤63 chars, passed as both `jobName` and `clientRequestToken` for idempotent retries. No raw `f"sp-{execution_id}-{phase}"`.
- **All imports live at the top of the file.** No inline imports inside functions/methods/branches. The single exception is a genuine circular import that can't be refactored — SteamPulse does not have any.
