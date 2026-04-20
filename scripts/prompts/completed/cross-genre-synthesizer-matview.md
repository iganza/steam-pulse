# Cross-genre synthesizer matview (Phase 4 LLM)

## Context

This is the architectural backbone of the Wedge Strategy
(`steam-pulse.org` → "Wedge Strategy: Roguelike Deckbuilder Deep
Coverage"). It is the canonical implementation of the
"Synthesize, don't retrieve-raw" principle from `ARCHITECTURE.org`
applied to cross-cutting questions ("what do roguelike-deckbuilder
players want / hate").

A **Phase-4 LLM pass** consumes the existing `GameReport` rows for all
games in a genre/tag and produces a single aggregated synthesis
persisted in `mv_genre_synthesis`. The page reads one row.

The LLM input is `GameReport` rows (~3k tokens each), NOT raw reviews.
This is the load-bearing distinction — synthesizing reports is cheap
(~$1.30 per genre per refresh); synthesizing raw reviews would be
catastrophic (~$50+ per genre per refresh).

## Role in the product (2026-04-17 business-model pivot)

The synthesis output is the **content engine** for three downstream
products (see `project_business_model_2026.md` and
`steam-pulse.org` → Active Launch Plan):

1. **Paid genre market reports** (Phase 1, headline product) — the
   `mv_genre_synthesis` row is the raw material an operator curates
   into a $49-$1499 PDF report. The LLM produces synthesis; the
   operator writes the report. Do NOT try to have Phase-4 produce
   finished report prose.
2. **Free genre insights page** (Phase 1, marketing funnel) —
   `/genre/{slug}/insights` renders a public subset of the synthesis
   (narrative summary, top-5 friction, top-3 wishlist, benchmark
   list). The full depth lives in the paid PDF; the web page is
   the preview.
3. **NL chat + text-to-SQL backing store** (Phase 3, not launch) —
   once Pro subscription ships, the structured `mv_genre_synthesis`
   rows are the aggregation substrate that lets SteamPulse answer
   cross-game quantitative questions LEYWARE's RAG-over-raw
   architecture cannot.

The implication for THIS prompt: no changes to the schema or prompt
on account of reports/chat. Phase-4 stays minimal and focused. The
report PDF is produced by human curation downstream; the chat layer
is a future SQL front-end over the same table. Both consume the
single canonical `mv_genre_synthesis.synthesis` JSONB.

## Naming note

Called `mv_genre_synthesis` to align with the matview vocabulary in
CLAUDE.md and ARCHITECTURE.org, but the actual implementation is a
**regular table** populated by a Lambda. Postgres `MATERIALIZED VIEW`
cannot run an LLM call. Conceptually it serves the same role
(pre-computed, refreshed out-of-band, queried by `SELECT`); the
implementation differs.

## What to do

### 1. Migration: `mv_genre_synthesis` table

```sql
-- depends: <prev>
CREATE TABLE IF NOT EXISTS mv_genre_synthesis (
    slug TEXT PRIMARY KEY,                    -- genre/tag slug
    display_name TEXT NOT NULL,               -- "Roguelike Deckbuilder"
    input_appids INTEGER[] NOT NULL,          -- sorted list of source GameReport appids
    input_count INTEGER NOT NULL,
    prompt_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,                 -- sha256(sorted_appids || prompt_version)
    synthesis JSONB NOT NULL,                 -- structured output (see model below)
    narrative_summary TEXT NOT NULL,          -- 1-paragraph headline
    avg_positive_pct NUMERIC,
    median_review_count INTEGER,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS mv_genre_synthesis_input_hash_idx
    ON mv_genre_synthesis(input_hash);
```

`PRIMARY KEY (slug)` is the natural unique key — one synthesis per
genre/tag.

`input_hash` is the cache key. Re-running on the same input set
(same appids + same prompt version) is a no-op short-circuit.

Mirror in `schema.py`. **Do not** add to `MATERIALIZED_VIEWS` — it
is a regular table, not a Postgres matview.

### 2. Pydantic models

In `library_layer/models/genre_synthesis.py`:

```python
class FrictionPoint(BaseModel):
    title: str                    # "Run length too long for short sessions"
    description: str              # 1-2 sentences
    representative_quote: str
    source_appid: int             # which game's review the quote came from
    mention_count: int            # how many of the input reports mentioned this

class WishlistItem(BaseModel):
    title: str
    description: str
    representative_quote: str
    source_appid: int
    mention_count: int

class BenchmarkGame(BaseModel):
    appid: int
    name: str
    why_benchmark: str            # "Defines the modern deckbuilder pacing"

class ChurnInsight(BaseModel):
    typical_dropout_hour: float
    primary_reason: str           # "Run-to-run repetition without unlock momentum"
    representative_quote: str
    source_appid: int

class DevPriority(BaseModel):
    action: str
    why_it_matters: str
    frequency: int                # mention_count across reports
    effort: str                   # "low" | "medium" | "high"

class GenreSynthesis(BaseModel):
    """Phase-4 LLM output schema. Persisted in mv_genre_synthesis.synthesis."""
    narrative_summary: str
    friction_points: list[FrictionPoint]      # 10 for free tier display
    wishlist_items: list[WishlistItem]        # 5 for free tier display
    benchmark_games: list[BenchmarkGame]      # 5 for free tier display
    churn_insight: ChurnInsight
    dev_priorities: list[DevPriority]         # 5+ for Pro tier
```

Use these for both LLM `tool_use` schema and DB persistence.

### 3. Repository — `GenreSynthesisRepository`

In `library_layer/repositories/genre_synthesis_repo.py`. Extends
`BaseRepository`. Methods:

- `get_by_slug(slug: str) -> GenreSynthesisRow | None` — pure
  `SELECT FROM mv_genre_synthesis WHERE slug = $1`. Returns a pydantic
  model (define `GenreSynthesisRow` in the same module).
- `upsert(row: GenreSynthesisRow) -> None` — `INSERT ... ON CONFLICT
  (slug) DO UPDATE SET ...`. The *only* writer.
- `find_stale(max_age_days: int) -> list[str]` — returns slugs whose
  `computed_at` is older than the threshold. Used by the EventBridge
  trigger to find synth jobs to enqueue.

No business logic. No LLM. SQL only.

### 4. Service — `GenreSynthesisService`

In `library_layer/services/genre_synthesis_service.py`. Coordinates
the synthesis. Constructor takes required deps (no `| None` defaults
per CLAUDE.md): `report_repo`, `tag_repo`, `synthesis_repo`,
`bedrock_client`, `config`.

```python
def synthesize(self, *, slug: str, prompt_version: str) -> GenreSynthesisRow:
    """
    1. Resolve eligible appids for slug (TagRepository.find_eligible_for_synthesis)
       — filter: in this tag, has GameReport, review_count >= MIN_REVIEWS
    2. Compute input_hash from (sorted_appids, prompt_version)
    3. Short-circuit: if a row exists with the same input_hash, return it
    4. Load all GameReport rows (.report_json) for those appids
    5. Build LLM prompt: system prompt cached (Anthropic prompt caching),
       user prompt is the concatenated structured reports
    6. Call Bedrock Sonnet via tool_use with GenreSynthesis as the schema
    7. Persist via synthesis_repo.upsert()
    8. Return the row
    """
```

**Tunable knobs** (required kwargs at the boundary, defaults in
`SteamPulseConfig` / a new `GenreSynthesisSettings` bundle):
- `MIN_REPORTS_PER_GENRE` (default 30) — refuse to synthesize if fewer
- `MAX_REPORTS_PER_GENRE` (default 200) — sample down by review_count desc
  if more
- `GENRE_SYNTHESIS_MAX_TOKENS` (default 8000)
- `GENRE_SYNTHESIS_PROMPT_VERSION` (default "v1") — bump on prompt edits

### 5. The Phase-4 prompt

Lives in `library_layer/prompts/genre_synthesis_v1.py` as a module
constant, mirroring the existing analyzer prompt structure. Single
Sonnet call, NOT batched (one call per genre per week).

Prompt skeleton (iterate after first run):

```
You are analyzing player reviews across {N} {display_name} games on Steam.
Each input is a structured GameReport synthesized from that game's reviews.

Produce a single cross-game synthesis answering: "what do {display_name}
players consistently love, hate, want, and where do they churn?"

Rules:
- Friction points and wishlist items must be SHARED across multiple games
  (mention_count >= 3). Single-game complaints don't belong here.
- Quotes must be verbatim from the source GameReports — do not paraphrase
  or invent.
- source_appid must reference the game whose report contained the quote.
- Be specific. "Bugs" is useless. "Crashes when joining co-op session
  during run 3+" is useful.
- For benchmark_games: select the 5 most frequently mentioned in
  competitive_context across the input reports.
- churn_insight.typical_dropout_hour: median across reports' churn_triggers
  where timing is given.

Input reports follow.
```

System prompt is the rules block (cached). User content is the report
JSON dump.

### 6. Lambda handler — `lambda_functions/genre_synthesis/handler.py`

New Lambda. Decorated with `@logger.inject_lambda_context` and
`@tracer.capture_lambda_handler` (X-Ray ON, per ARCHITECTURE.org
observability rule). Triggered by:

- **EventBridge weekly rule** (Sunday 02:00 UTC): scans
  `find_stale(max_age_days=7)` and enqueues a synthesis job per stale
  slug into a new SQS queue `genre-synthesis-queue`.
- **SQS messages** on that queue: each message = one slug to
  synthesize. Lambda calls `service.synthesize(slug=...)`.
- **On-demand**: admin can publish to the SQS queue directly to force
  a re-synthesis (e.g. after a prompt iteration).

Use the typed events pattern from CLAUDE.md — define
`GenreSynthesisJobMessage` in `library_layer/events.py` with
`message_type: SqsMessageType = "genre_synthesis_job"`.

### 7. CDK wiring — `infra/stacks/compute_stack.py`

- New `PythonFunction` for the synthesizer Lambda. Memory: 1024MB
  (LLM call holds large prompt in memory). Timeout: 5 min.
- New SQS queue `genre-synthesis-queue` + DLQ.
- EventBridge weekly rule pointing at the Lambda with input
  `{"action": "scan_stale"}`.
- IAM grants: Bedrock invoke, SQS send/receive, SSM/Secrets read for
  DB credentials.
- Add SSM param `/steampulse/{env}/messaging/genre-synthesis-queue-url`,
  expose env var `GENRE_SYNTHESIS_QUEUE_PARAM_NAME` to relevant
  Lambdas.

Per CDK rules: no physical names except SSM paths; use
`secret.grant_read(role)` not raw ARNs; use `cdk-monitoring-constructs`
for any alarms.

### 8. API endpoint — `lambda_functions/api/handler.py`

Path is `/api/tags/{slug}/insights`, NOT `/api/genres/...`. The
synthesizer joins `tags`/`game_tags` (see
`TagRepository.find_eligible_for_synthesis`), so the identifier space
is `tags.slug`. The persisted table keeps the `mv_genre_synthesis`
name for historical/marketing reasons, but the web-facing namespace
is tags.

```python
@app.get("/api/tags/{slug}/insights")
def get_tag_insights(slug: str) -> JSONResponse:
    row = genre_synthesis_repo.get_by_slug(slug)
    if row is None:
        raise HTTPException(404, f"No synthesis for {slug}")
    return JSONResponse(
        content=row.model_dump(mode="json"),
        headers={"Cache-Control": "public, s-maxage=3600, stale-while-revalidate=86400"},
    )
```

Long s-maxage (1h) + SWR (1d) — synthesis only changes weekly, so the
CDN should hold.

### 9. Refresh cadence — weekly, NOT 6h

Genre-level synthesis does not shift fast (durable themes, not
breaking news). Refreshing every 6h would cost ~$90/month per genre =
unaffordable at any catalog scale. Weekly = ~$5/month per genre. The
matview-refresh Lambda does not touch this table — it has its own
EventBridge rule.

If a synthesis goes stale faster than that for a specific genre
(unlikely), the admin can publish to `genre-synthesis-queue` to force
a refresh.

### 10. API boundary — all fields free

`/api/tags/{slug}/insights` returns the **full** `GenreSynthesis`
payload to any caller. No auth, no tiering, no trimming. Under the
two-tier catalog model (`project_business_model_2026.md`) every
on-site surface is free forever — the paid product is the
self-serve PDF report, not a gated view of this data. Do not add
`pro: bool` flags, `trim_for_free` helpers, or any gating at the API
boundary.

## Verification

1. **Migration applies**: `bash scripts/dev/migrate.sh` then
   `\d mv_genre_synthesis` shows the expected schema.
2. **Service unit test**: mock the Bedrock client to return a
   canned `GenreSynthesis`, run `service.synthesize(slug="test")`,
   assert the row is upserted with the right `input_hash`, and
   running it a second time short-circuits (no Bedrock call).
3. **Cache idempotency**: same appid set + same `prompt_version` =
   no LLM call on re-run. Different `prompt_version` = new LLM call.
4. **Real synthesis on roguelike-deckbuilder**: after the 141 RDB
   games are analyzed, run `service.synthesize(slug="roguelike-
   deckbuilder", prompt_version="v1")` from a local Python REPL
   pointed at staging. Inspect the row. Sanity-check:
   - Are quotes actually verbatim from source `GameReport`s?
   - Are friction points genuinely shared (mention_count >= 3)?
   - Are benchmark games the obvious ones (Slay the Spire, Balatro,
     Inscryption, etc.)?
   - Is the narrative summary readable in one paragraph?
5. **Cost tracking**: capture token counts from the Bedrock response.
   Log via Powertools. Per-synthesis cost should land near $1–2 for
   ~140 reports.
6. **API smoke test**: `GET /api/tags/roguelike-deckbuilder/insights`
   returns 200 with the full payload. Add to `tests/smoke/`.
7. **EventBridge dry-run**: invoke the handler with
   `{"action": "scan_stale"}` and verify it enqueues SQS messages
   for every stale slug.
8. `poetry run pytest -v && poetry run ruff check .`

## Out of scope (separate prompts later)

- **Cross-genre comparison endpoint** ("compare RDB vs broader roguelike")
  — a Pro feature that needs two synthesis rows joined and a delta
  computed. Build after auth.
- **Filtering on the synthesis** (price tier, EA status, etc.) — a
  Pro feature that needs filtered variants of the synthesis (e.g.
  `mv_genre_synthesis_filtered` keyed by `(slug, filter_key)`).
  Defer until V1 demo lands.
- **Email digest** (weekly per-genre intelligence newsletter) —
  consumes the matview, sends via Resend. Separate prompt.
- **Lifetime-sample crawl** (the open question in `ARCHITECTURE.org`).

## Rollout

- One migration. One Lambda. One SQS queue. One EventBridge rule.
- No deploy from Claude — user runs `bash scripts/deploy.sh` themselves.
- After deploy, manually publish a job for `roguelike-deckbuilder`
  to populate the first row. Inspect, iterate prompt, re-run via
  bumping `prompt_version` to `"v2"` etc.
