# Three-Phase LLM Analysis Pipeline

> **Updated post-data-source-clarity refactor.** Sentiment magnitude is owned by Steam
> (`positive_pct` / `review_score_desc` on the `Game` row). The `GameReport` no longer
> contains `sentiment_score` or `overall_sentiment`. The only Python-computed numeric
> values still overwritten on the report are `hidden_gem_score` (now derived from
> Steam's positive_pct + review_count, not from sampled batch_stats) and the
> `sentiment_trend*` fields (a window comparison, not a magnitude). See
> `scripts/prompts/data-source-clarity.md` for the full rationale.

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

---

## Codebase Orientation

### Files to Modify

- **Models**: `src/library-layer/library_layer/models/analyzer_models.py` — add `TopicSignal`, `ReviewQuote`, `RichChunkSummary`, `MergedSummary`
- **Analyzer**: `src/library-layer/library_layer/analyzer.py` — v2 prompts, new chunk/merge/synthesis functions, `analyze_reviews_v3()` orchestrator
- **Scores**: `src/library-layer/library_layer/utils/scores.py` — no new helpers needed; `compute_hidden_gem_score(positive_pct, review_count)` and `compute_sentiment_trend(reviews) -> dict` already exist post-data-source-clarity
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
- `src/lambda-functions/migrations/0035_chunk_summaries.sql` — new table
- `src/lambda-functions/migrations/0036_merged_summaries.sql` — new table + reports columns
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

The single entry point is `analyze_game()` in `analyzer.py`. It takes an
`AnalysisRequest`, an `LLMBackend`, and the repositories. Plain sync `def` — no async.

```python
def analyze_game(
    request: AnalysisRequest,
    *, backend: LLMBackend,
    chunk_repo: ChunkSummaryRepository,
    merge_repo: MergedSummaryRepository,
    report_repo: ReportRepository,
    game_repo: GameRepository,
    review_repo: ReviewRepository,
) -> GameReport:
    """The one entry point. Identical for realtime and batch.

    Sentiment magnitude is owned by Steam — `positive_pct` / `review_score_desc`
    are read from the `Game` row and NEVER recomputed from merged.total_stats.
    """
    # Short-circuit: if reports.pipeline_version matches and no new reviews,
    # return the stored report without entering the pipeline.
    existing = report_repo.find_by_appid(request.appid)
    if existing and existing.pipeline_version == PIPELINE_VERSION \
            and not review_repo.has_new_reviews_since(request.appid, existing.last_analyzed):
        return existing

    game = game_repo.get(request.appid)
    reviews = review_repo.find_by_appid(request.appid, limit=2000)
    temporal, metadata = build_contexts(game, reviews)

    chunk_summaries = run_chunk_phase(
        appid=request.appid, game=game, reviews=reviews,
        backend=backend, chunk_repo=chunk_repo,
    )
    merged = run_merge_phase(
        appid=request.appid, game=game, chunk_summaries=chunk_summaries,
        backend=backend, merge_repo=merge_repo,
    )
    report = run_synthesis_phase(
        game=game, reviews=reviews, merged=merged,
        temporal=temporal, metadata=metadata, backend=backend,
    )
    report_repo.upsert(report, pipeline_version=PIPELINE_VERSION)
    publish_report_ready(request.appid)
    return report


def run_chunk_phase(
    *, appid, game, reviews, backend, chunk_repo,
) -> list[RichChunkSummary]:
    chunks = stratified_chunk_reviews(reviews, CHUNK_SIZE)
    cached, pending, pending_meta = [], [], []

    for i, chunk in enumerate(chunks):
        h = compute_chunk_hash(chunk)
        row = chunk_repo.find_by_hash(appid, h, CHUNK_PROMPT_VERSION)
        if row:
            cached.append((i, RichChunkSummary.model_validate(row.summary_json)))
        else:
            pending.append(LLMRequest(
                record_id=f"{appid}-chunk-{i}",
                task="chunking",
                system=CHUNK_SYSTEM_PROMPT_V2,
                user=build_chunk_user_message(chunk, game.name, i, len(chunks)),
                max_tokens=1024,
                response_model=RichChunkSummary,
            ))
            pending_meta.append((i, h, len(chunk)))

    fresh = backend.run(pending) if pending else []
    for (i, h, n), summary in zip(pending_meta, fresh, strict=True):
        chunk_repo.insert(appid, i, h, n, summary,
                          model_id=config.model_for("chunking"),
                          prompt_version=CHUNK_PROMPT_VERSION)
        cached.append((i, summary))

    cached.sort(key=lambda t: t[0])
    return [summary for _, summary in cached]


def run_merge_phase(
    *, appid, game, chunk_summaries, backend, merge_repo,
) -> MergedSummary:
    # Hierarchy: 1→promote, 2–5→single, 6–40→two-level, 41+→three-level (max 3).
    # Each level checks merge_repo.find_latest_by_source_ids() for cache hits
    # before calling backend.run(). Persists every level it produces.
    ...


def run_synthesis_phase(
    *, game, reviews, merged, temporal, metadata, backend,
) -> GameReport:
    hidden_gem = compute_hidden_gem_score(game.positive_pct, game.review_count)
    trend = compute_sentiment_trend(reviews)

    [report] = backend.run([LLMRequest(
        record_id=f"{game.appid}-synthesis",
        task="summarizer",
        system=SYNTHESIS_SYSTEM_PROMPT,
        user=build_synthesis_user_message(
            merged=merged, game=game, temporal=temporal, metadata=metadata,
            steam_positive_pct=game.positive_pct,
            steam_review_score_desc=game.review_score_desc,
            hidden_gem_score=hidden_gem,
            sentiment_trend=trend,
        ),
        max_tokens=5000,
        response_model=GameReport,
    )])

    # Defensive overrides — Steam owns sentiment magnitude, Python owns derived scores
    report.hidden_gem_score = hidden_gem
    report.sentiment_trend = trend["trend"]
    report.sentiment_trend_note = trend["note"]
    report.sentiment_trend_reliable = trend["reliable"]
    report.sentiment_trend_sample_size = trend["sample_size"]
    report.appid = game.appid
    return report
```

The realtime Lambda (`lambda_functions/analysis/handler.py`) instantiates
`ConverseBackend` at module level (warm reuse), parses the incoming
`AnalysisRequest` from SQS/Step Functions input, and calls
`analyze_game(request, backend=_converse, ...)`. That's it — the Lambda is a
thin dispatcher.

---

## Step 9: Batch Execution Path

Batch mode runs the **same** `run_chunk_phase` / `run_merge_phase` /
`run_synthesis_phase` helpers as realtime — just driven across multiple Lambda
invocations by Step Functions. Each Prepare/Collect Lambda is a thin wrapper
that instantiates `BatchBackend` and calls the shared helpers. No
exceptions-as-control-flow: job pending vs. complete is Step Functions state.

### Step Functions (STANDARD) state machine

```
StartAnalysis (receives AnalysisRequest with mode="batch")
  ├─ PrepareChunkPhase   → shared run_chunk_phase helpers to build requests,
  │                        filter DB cache hits (insert them immediately),
  │                        BatchBackend.prepare(pending) → s3_uri
  │                        BatchBackend.submit(s3_uri, "chunking") → job_id
  │                        returns {job_id, appid}
  ├─ WaitChunk + CheckChunkStatus → BatchBackend.status(job_id) loop
  ├─ CollectChunkPhase   → BatchBackend.collect(job_id, [RichChunkSummary])
  │                        chunk_repo.insert() for every returned summary
  ├─ PrepareMergePhase   → loads chunk_summaries from DB, calls
  │                        plan_merge_hierarchy(), builds MERGE LLMRequests
  │                        for the current level, checks merge_repo cache,
  │                        BatchBackend.prepare/submit → {job_id, merge_level}
  ├─ WaitMerge/CheckMerge/CollectMergePhase — loop by merge_level
  │   Choice: another level needed? → PrepareMergePhase (increment level)
  │                                 → else continue
  ├─ PrepareSynthesisPhase → loads merged_summaries.find_latest_by_appid(),
  │                          Python scores, build_synthesis_user_message(),
  │                          BatchBackend.prepare/submit → {job_id}
  ├─ WaitSynth/CheckSynth
  └─ CollectSynthAndPersist → BatchBackend.collect() → apply Python overrides →
                              report_repo.upsert(pipeline_version=...)
                              publish_report_ready(appid)
```

### Lambda wrappers

Every batch Lambda is a thin adapter. Key property: **all prompt strings,
chunking, merge hierarchy, synthesis user builder, Python scores, and
persistence are imported from `library_layer/analyzer.py`**. Batch Lambdas
contain zero prompt text of their own — drift between realtime and batch is
impossible.

- `prepare_chunk.py`, `collect_chunk.py`
- `prepare_merge.py`, `collect_merge.py`
- `prepare_synthesis.py`, `collect_synthesis.py` (replaces old `process_results.py`)
- `check_batch_status.py` — single shared status-poller for all three phases

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
| 14 | Batch Lambdas: `prepare_chunk/collect_chunk/prepare_merge/collect_merge/prepare_synthesis/collect_synthesis` — thin wrappers over shared helpers + `BatchBackend` | Steps 10, 11 |
| 15 | CDK: add merge + collect Lambdas, update STANDARD SFN ASL | Step 14 |
| 16 | Remove old two-pass `analyze_reviews()` + legacy `ChunkSummary` | Steps 11, 12 |
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
- `hidden_gem_score` and `sentiment_trend*` are ALWAYS computed in Python and overwritten on the report — never from LLM output
- **Sentiment magnitude is owned by Steam.** `positive_pct` / `review_score_desc` come from the `Game` row and are NEVER recomputed from `merged.total_stats`. Do not reintroduce `sentiment_score` or `overall_sentiment` to `GameReport`. Do not add `compute_sentiment_score_from_counts()`.
- The synthesis prompt receives Steam's `positive_pct` as canonical context (`steam_positive_pct` parameter on the user-message builder) so the LLM frames its narrative consistently
- `GameReport` output schema reflects the post-data-source-clarity shape: `refund_signals` (not `refund_risk`), `ContentDepth` has `confidence` + `sample_size`, `sentiment_trend_reliable` + `sentiment_trend_sample_size` are present
- Hierarchical merge max depth is 3 levels — never deeper
- Legacy `review_summaries` table (appid PK) is unrelated to `chunk_summaries`
- Both real-time and batch paths use the same prompt constants
- No feature flag — the 3-phase pipeline replaces the 2-pass code directly
- `steam_review_id` is included in review text sent to LLM for quote attribution
- Batch path gains merge loop states in Step Functions ASL
- S3 structure gains `merge/level{N}/` directories
- **Single entry point is `analyze_game(request: AnalysisRequest, *, backend, repos)`** — not a mode-specific function per execution mode
- **`LLMBackend.run()` is sync-only** and implemented only by `ConverseBackend`. `BatchBackend` exposes `prepare/submit/status/collect` — it does NOT implement `run()`. Do not add an async `run()` or a "pending" exception — job-pending state lives in Step Functions
- **No `async`/`await` anywhere** in analyzer, backends, handlers, or repos. psycopg2, instructor, and boto3 Bedrock clients are all sync. `ConverseBackend.run()` may use a thread pool for chunk fan-out; that is the only parallelism
- **`/api/preview` is deleted** — analysis is driven by `AnalysisRequest` (SQS/Step Functions), not by an HTTP endpoint. Do not reintroduce preview
- Batch Lambdas import prompts/chunking/merge/synthesis/persistence from `library_layer/analyzer.py` — they contain zero prompt strings of their own
