# CLAUDE.md

This file is Claude Code's persistent memory for SteamPulse. Read it fully before touching any code.

## Architecture Reference

All component definitions and interaction flows live in **`ARCHITECTURE.org`** at the repo root.
Read it before modifying any handler, service, queue, or SNS topic.
Each flow has an invariant statement and a **drift checklist** — verify those items when implementing or changing a flow.
When adding a new interaction, add its sequence diagram to `ARCHITECTURE.org` first.

## What This Project Is

**SteamPulse** — AI-powered Steam game intelligence platform at **steampulse.io**.

- **Public site**:  (Free)
    Public site where users can browse the entire steam game catalog.  
    An "Analysis" section with various tabs showing information available from the games catalog.
    AI-synthesized review reports for ALL Steam games with any reviews. SEO-driven, cross-linked, no ads.
    
- **Pro section**: (Paid Subscription model)
    Allows more detailed drilling into, and manipulation of feature of the "Analysis" section.  Charts allow drilling in and modification of many more parameters and sections.
    Cross analysis for game/section/genre/tag and LLM assisted analysis of data cutting across many more elements of the data.


---

## Tech Stack

| Layer       | Choice                                                                                                               |
|-------------|----------------------------------------------------------------------------------------------------------------------|
| Backend API | Python 3.12, FastAPI (JSON API only — no HTML rendering), uvicorn, httpx                                             |
| Frontend    | Next.js (React SSR/ISR) in `frontend/`, deployed via OpenNext to Lambda                                              |
| LLM         | Amazon Bedrock with 2 pass / map-reduce                                                                              |
| DB          | PostgreSQL on RDS. All access via Repository classes. Locally use Docker Postgres via `./scripts/dev/start-local.sh` |
| Hosting     | AWS Lambda (container image) + CloudFront + Route 53. **No Railway. No Fargate.**                                    |
| Infra       | AWS CDK v2 (Python) in `infra/`. CDK Pipelines (self-mutating).                                                      |
| Payments    | **None currently.**                                                                                                  |
| Email       | Resend                                                                                                               |
| Deps        | Poetry — `pyproject.toml` is source of truth. No `requirements.txt`.                                                 |

---

## Monorepo Structure

```
repo-root/
  src/
    library-layer/      # Shared Lambda layer: httpx, psycopg2, boto3, anthropic + framework code
      library_layer/
        analyzer.py     # Three-phase LLM analysis (chunk → merge → synthesize)
        config.py       # SteamPulseConfig (env var parsing)
        fetcher.py      # HTTP client wrapper
        reporter.py     # Report generation / storage
        schema.py       # PostgreSQL schema reference
        steam_source.py # Steam API abstraction (SteamDataSource)
        models/         # Domain + LLM output models
          analyzer_models.py  # GameReport, RichChunkSummary, MergedSummary, TopicSignal + all LLM output types
          catalog.py    # CatalogEntry
          game.py       # Game, GameSummary
          report.py     # Report (DB wrapper for stored report_json)
          review.py     # Review
          tag.py        # Tag, Genre, Category
        repositories/   # SQL I/O: game_repo, review_repo, report_repo, analytics_repo, etc.
        services/       # Business logic: crawl_service, catalog_service
        utils/          # Shared helpers: db, sqs, ssm, slugify, events, time, steam_metrics
    lambda-functions/   # All Lambda handlers
      lambda_functions/
        analysis/       # Three-phase LLM analysis handler (realtime entry point)
        batch_analysis/ # Batch Step Functions prepare/collect Lambdas (chunk/merge/synthesis)
        api/            # FastAPI app: all /api/* endpoints
        crawler/        # App + review crawler, spoke, ingest handlers
        admin/          # Admin ops + migrate handler (no X-Ray — intentional)
        db_loader/      # DB initialization handler
      migrations/       # yoyo-migrations DDL: 0001–0005_*.sql
  frontend/             # Next.js 13+ App Router (React SSR/ISR)
    app/                # Pages: home, games/[appid]/[slug], genre, search, tag, trending, pro
    components/         # game/, layout/, ui/ component groups
    lib/                # api.ts, types.ts, utils.ts
    tests/              # Playwright E2E tests + fixtures/
  infra/                # AWS CDK v2 (Python)
    app.py              # CDK entry point
    pipeline_stack.py
    application_stage.py
    stacks/             # network, data, messaging, compute, delivery, certificate, frontend, spoke, monitoring
  tests/                # Python unit tests (pytest)
    handlers/           # Handler tests
    repositories/       # Repository tests (steampulse_test DB)
    services/           # Service tests (incl. test_analyzer.py)
    infra/              # CDK stack tests
    utils/              # Utility tests
  scripts/
    dev/                # start-local.sh, run-api.sh, db-tunnel.sh, push-to-staging.sh, migrate.sh
    prompts/            # Active feature design specs (completed/ subdir for done specs)
    seed.py             # Bootstrap top-N games into SQS
    sp.py               # CLI: queue reviews, check status
    tail.py             # CloudWatch Logs tail
    trigger_crawl.py    # Trigger crawl manually
    migrate_slugs.py    # One-off slug migration
    aws-costs.sh        # AWS cost report
  doc/                  # Architecture diagrams, sequence diagrams, prompt strategy
  Dockerfile            # Lambda container image
  docker-compose.yml    # Local Postgres for dev
  pyproject.toml        # Python deps (main + infra groups)
  cdk.json              # "app": "poetry run python infra/app.py"
  CLAUDE.md
  ARCHITECTURE.org      # Full component & interaction flow reference
  steampulse-design.org # Architecture decisions
```

---

## Common Commands

```bash
# Local dev — start DB, run API
./scripts/dev/start-local.sh          # start Postgres + init schema
./scripts/dev/run-api.sh              # API at http://localhost:8000
./scripts/dev/db-tunnel.sh            # SSH tunnel to RDS (staging/prod)

# CLI analysis (local LLM testing) — incremental, per-phase
# Each phase persists its output (chunk_summaries → merged_summaries → reports)
# and the next phase short-circuits on cache hits. Safe to re-run.
poetry run python scripts/dev/run_phase.py --appid 440 --phase chunk
poetry run python scripts/dev/run_phase.py --appid 440 --phase merge
poetry run python scripts/dev/run_phase.py --appid 440 --phase synthesis

# Deploy (no pipeline — deploy runs locally)
bash scripts/deploy.sh --env staging        # build frontend + cdk deploy + migrate + cdn invalidate
bash scripts/deploy.sh --env staging --skip-frontend   # skip frontend rebuild (faster)
bash scripts/deploy.sh --env production     # production deploy

# CDK (direct — for individual stack work)
poetry install --with infra
poetry run cdk synth
poetry run cdk deploy 'SteamPulse-Staging-*' --require-approval never

# Lambda layer deps — IMPORTANT: after adding/removing deps in src/library-layer/pyproject.toml,
# regenerate its lock file or the new package won't be installed in the Lambda layer:
cd src/library-layer && poetry lock && cd ../..
# Then commit poetry.lock alongside your pyproject.toml change.

# Frontend local dev
cd frontend && npm install && npm run dev

# Tests
poetry run pytest -v
poetry run ruff check .
poetry run ruff format .

# Migrations
bash scripts/dev/migrate.sh                       # apply pending migrations (local)
bash scripts/dev/migrate.sh --stage staging       # staging (tunnel must be open)

# Seed / queue scripts
export APP_CRAWL_QUEUE_URL="<SQS queue URL from AWS Console or SSM>"
poetry run python scripts/seed.py --limit 50     # staging
poetry run python scripts/seed.py --dry-run --limit 5   # smoke test
poetry run python scripts/seed.py               # production (full crawl)
poetry run python scripts/sp.py queue reviews 440  # queue single game

# Log tailing (Lambda CloudWatch logs)
poetry run python scripts/tail.py crawler        # tail crawler logs
poetry run python scripts/tail.py all --env staging   # all Lambdas on staging
# services: crawler | spoke | ingest | api | analysis | all
# options:  --env staging|production  --since 5m|1h|2h|1d
```

---

## Architecture: Key Patterns

### Repository → Service → Handler (mandatory)

Every data access follows a strict three-layer pattern. **Nothing outside a Repository ever touches SQL.**

```
Handler (Lambda / FastAPI route)
  └── calls Service methods (business logic only)
        └── calls Repository methods (SQL only)
```

- **Repository** (`library_layer/repositories/`): pure SQL I/O. One class per domain entity
  (`GameRepository`, `ReviewRepository`, `ReportRepository`, etc.). No business logic,
  no HTTP calls, no LLM calls. Methods return domain models or raise exceptions.
- **Service** (`library_layer/services/`): business logic only. Coordinates repositories,
  calls external APIs (Steam, Bedrock), makes decisions. No raw SQL — if you need data,
  call a repository method.
- **Handler** (`lambda_functions/*/handler.py`): thin dispatcher. Parse input → call service →
  return output. No SQL, no business logic.

**DRY across repos and services:** Any logic needed by more than one repository or service
lives in `library_layer/` in an appropriate directory for it. 

Examples: `slugify()`, `send_sqs_batch()`, `row_to_model()`,

timestamp helpers. Import from utils — never duplicate.

SQS common code can be in library_layer/sqs_util
SNS common code in library_layer/sns_util
and so on...

### Read path: UI is fed by materialized views + pre-computed data (mandatory)

**Every page, feed, listing, dashboard tile, headline count, and filter dropdown on the
site is served from a materialized view (or equivalent pre-computed artifact) — never
from a live scan/join/aggregate against base tables at request time.**

This is a hard rule. The project already runs on this pattern (`mv_genre_counts`,
`mv_tag_counts`, `mv_genre_games`, `mv_tag_games`, `mv_price_positioning`, `mv_release_timing`,
`mv_platform_distribution`, `mv_tag_trend`, `mv_price_summary`, `mv_review_counts`,
`mv_trend_catalog`, `mv_trend_by_genre`, `mv_trend_by_tag`, `mv_new_releases`, plus
denormalized columns on `games` like `positive_pct`, `review_velocity_lifetime`,
`estimated_owners`, `estimated_revenue_usd`). New read paths extend it — they don't
invent new ones.

#### Why

- **Latency**: CDN → Next.js ISR → matview is a three-layer cache. A `COUNT(*) ... GROUP BY`
  across `games`/`reviews`/`game_tags` at request time is unacceptable at our traffic shape.
- **Consistency**: the matview is the single source of truth for a given view/page, so
  every tile on a dashboard agrees. Computing the same aggregate two different ways in two
  different places drifts.
- **Query simplicity**: repositories become thin `SELECT ... FROM mv_foo WHERE ...` that
  any reader can verify at a glance.
- **Correctness**: the hard join/aggregate logic lives in one place (the matview DDL),
  reviewed once, instead of scattered across ad-hoc repo methods.

#### The pattern

When adding a new read path (a page, a tile, a filter facet, a count, a list), ask in order:

1. **Can an existing matview serve it?** Read `MATVIEW_NAMES` in
   `library_layer/repositories/matview_repo.py` first. If yes, add a `SELECT` method to
   `MatviewRepository` (or a dedicated repo that reads the same matview) — done.
2. **Can an existing matview be *extended*?** Prefer adding a column (e.g. a new array,
   a new denormalized field) to an existing matview over creating a new one. Drop + recreate
   the matview in a new migration — see the drop-before-create pattern in
   `migrations/0034_new_releases_matview.sql` and `schema.py::create_matviews()`. Update
   `schema.py` to mirror.
3. **Does it need a new matview?** Create one only if the existing ones can't cover it.
   Follow the full recipe below.
4. **Can a denormalized column on `games` (or another base entity) serve it instead?**
   For simple per-row values that the write path can maintain (e.g. `positive_pct`,
   `review_velocity_lifetime`, revenue estimate fields), a denormalized column is simpler
   than a matview and has zero refresh lag. Use this for write-time-computable scalars,
   not for aggregates/joins/filters.

If none of those work (rare), explain why in the PR description — expect pushback.

#### Full recipe for a new matview

1. **Migration** (`migrations/00NN_<name>_matview.sql`):
   - `DROP MATERIALIZED VIEW IF EXISTS mv_foo;` before the `CREATE` (self-heals stale
     shapes on persistent dev/staging DBs).
   - `CREATE MATERIALIZED VIEW mv_foo AS SELECT ...` bounded to the smallest window that
     serves the feature (e.g. `mv_new_releases` is bounded to 365d released / 90d
     discovered). Never unbounded scans of `games` if you can avoid it.
   - **`CREATE UNIQUE INDEX mv_foo_pk_idx ON mv_foo(...)` is mandatory** — required for
     `REFRESH MATERIALIZED VIEW CONCURRENTLY`. No unique index = blocking refresh = outage.
   - Partial b-tree indexes matching the primary WHERE/ORDER BY of the repo methods.
   - **GIN indexes on any `text[]` filter columns** when the repository filters use
     array operators Postgres can index with GIN — typically `@>` or `&&`, e.g.
     `col @> ARRAY[slug]::text[]`. Do **not** assume `slug = ANY(col)` is index-backed;
     it isn't — Postgres only uses GIN for the `@>` / `&&` operator classes. See
     `mv_new_releases_genre_slugs_gin` for an example.
2. **Mirror in `schema.py`**: append the DDL to `MATERIALIZED_VIEWS` and add the matview
   name to the drop-before-rebuild list in `create_matviews()` so test DBs pick up future
   shape changes automatically.
3. **Register for refresh**: add the matview name to `MATVIEW_NAMES` in
   `library_layer/repositories/matview_repo.py`. **Do not write a new refresh path.** The
   existing `lambda_functions/admin/matview_refresh_handler.py` Lambda picks it up
   automatically — it's triggered by SQS (report-ready, catalog-refresh-complete) and by
   EventBridge (every 6h) with a 5-minute debounce, and logs to `matview_refresh_log`.
4. **Repository**: a thin class extending `BaseRepository`, constructed with `get_conn`,
   whose methods are pure `SELECT ... FROM mv_foo WHERE ...`. Return Pydantic models, never
   dicts. No business logic, no window math, no filter-clause composition beyond tiny
   `_filter_clause()` helpers for dynamic `WHERE`s.
5. **Service** owns all derived logic: window→datetime translation, page clamping, bucketing,
   headline-count fan-out, filter passthrough. Calls the repository only.
6. **API handler** is thin: parse query params → call service → `JSONResponse` with
   `Cache-Control: public, s-maxage=300, stale-while-revalidate=600` (or tighter if the
   data changes faster).

#### Terminology (use these exact words)

- **Materialized view (matview)** — a Postgres `MATERIALIZED VIEW`, refreshed out-of-band.
  The workhorse for aggregates, joins, and filter facets.
- **Denormalized column** — a scalar column on a base entity (e.g. `games.positive_pct`)
  populated by the write path. Use for per-row values, not aggregates.
- **Bounded window** — matviews should be scoped to the smallest time range / row set that
  serves the feature (e.g. "last 365d" for a new-releases feed). Unbounded matviews over
  `games` or `reviews` are a smell.
- **Refresh cadence** — how stale the data can be. The existing pipeline gives you
  ~5min-after-write via SQS triggers plus a 6h EventBridge fallback, debounced at 5min.
  Don't build a second refresh path.
- **Pre-computed** — umbrella term covering both matviews and denormalized columns. When
  you write "pre-computed" in a PR, mean one of those two concretely.

#### Anti-patterns (do not do)

- Running `COUNT(*)`/`GROUP BY`/multi-table `JOIN` against `games`/`reviews`/`game_tags`
  inside a FastAPI request handler path.
- Adding a new matview with no unique index — breaks `REFRESH CONCURRENTLY`.
- Writing a new refresh Lambda or cron instead of extending `MATVIEW_NAMES`.
- Computing a headline count or facet count with a second API roundtrip — return it in the
  same response envelope the list endpoint already serves.
- Caching *in application memory* as a substitute for a matview. The matview IS the cache.
- Iterating over a matview in Python to filter/group — push the predicate into SQL.

### SNS Events and SQS Messages — typed Pydantic models (events.py)

All inter-service messages — both SNS events and SQS queue messages — are defined as typed
Pydantic models in **`src/library-layer/library_layer/events.py`**. This is the single source
of truth for everything that flows on queues or topics.

**Two base classes:**

- `BaseEvent` — for SNS events (published to a topic, routed via MessageAttribute filters).
  Subclasses set `event_type: EventType = "my-event"`.
- `BaseSqsMessage` — for SQS messages (sent directly to a queue, routed by `message_type`
  in the consumer Lambda). Subclasses set `message_type: SqsMessageType = "my-message"`.

**Conventions:**
- Add new event/message types to `EventType` or `SqsMessageType` literals first, then define the model.
- Subclass discriminator fields use the declared base type with a default — `field: EventType = "my-event"` —
  **not** ad-hoc `Literal["my-event"]` narrowing (see feedback memory).
- All new fields on existing events/messages **must have defaults** (`= None` or a sensible value) so
  old consumers don't fail validation on messages produced by new producers before they've deployed.
- Serialize with `.model_dump_json()` when enqueuing; deserialize with `.model_validate(json.loads(body))`
  in the consumer.
- Never use raw dicts with a string `"type"` key — always a typed model.

**Example — enqueue (producer):**
```python
from library_layer.events import WaitlistConfirmationMessage

msg = WaitlistConfirmationMessage(email=email)
sqs.send_message(QueueUrl=queue_url, MessageBody=msg.model_dump_json())
```

**Example — consume (consumer):**
```python
from library_layer.events import WaitlistConfirmationMessage

body = json.loads(record["body"])
match body.get("message_type"):
    case "waitlist_confirmation":
        msg = WaitlistConfirmationMessage.model_validate(body)
    case _:
        logger.warning("Unknown message type", extra={"message_type": body.get("message_type")})
```

### SteamDataSource abstraction (steam_source.py)

All Steam data access goes through `SteamDataSource`. Currently only `DirectSteamSource`
(calls Steam API directly). SteamSpy is NOT used. Player tags come from parsing the Steam
store page HTML — the `InitAppTagModal()` JS call embeds up to 20 tags per game with vote
counts. Age-gated games require bypass cookies (handled in `_get_store_page()`).

### LLM Three-Phase Analysis (analyzer.py)

See `scripts/prompts/three-phase-analysis.md` for the full design.

**Phase 1 — CHUNK (LLM_MODEL__CHUNKING, map, parallel):**
Stratified 50-review chunks → `RichChunkSummary`. Each chunk extracts structured
`TopicSignal` objects (topic, category, sentiment, mention_count, confidence,
quotes) across nine categories: `design_praise`, `gameplay_friction`,
`wishlist_items`, `dropout_moments`, `technical_issues`, `refund_signals`,
`community_health`, `monetization_sentiment`, `content_depth`.
Persisted in `chunk_summaries`, idempotent on `(appid, chunk_hash, prompt_version)`.

**Phase 2 — MERGE (LLM_MODEL__MERGING, reduce):** Hierarchical merge of chunk
summaries into a single `MergedSummary`. One-chunk → Python promotion, no LLM call.
≤ N chunks → single merge call. > N → hierarchical recursion with leaf `chunk_summaries.id`s
threaded transitively through every level so each merge row is cache-keyed by the exact
set of primary chunks it derives from. Persisted in `merged_summaries`.

**Phase 3 — SYNTHESIZE (LLM_MODEL__SUMMARIZER):** `MergedSummary` + game metadata +
temporal context + store description → `GameReport` JSON. `hidden_gem_score`,
`sentiment_trend`, `sentiment_trend_sample_size`, and `sentiment_trend_reliable` are
computed in Python BEFORE calling the LLM and defensively overridden on the response —
never LLM-guessed. Persisted in `reports`.

**Sentiment magnitude is owned by Steam, not the LLM.** The `GameReport` does NOT contain
`sentiment_score` or `overall_sentiment`. Steam's `positive_pct` (0–100) and `review_score_desc`
on the `Game` row are the only sentiment numbers shown to users. The LLM produces narrative
sections only; the synthesis prompt receives Steam's positive_pct as canonical context.
See `scripts/prompts/data-source-clarity.md` for the rationale.

**Execution modes:** Both realtime (`ConverseBackend`, used by `analysis/handler.py`)
and batch (`BatchBackend`, driven by the Step Functions state machine in
`infra/stacks/batch_analysis_stack.py` via `batch_analysis/prepare_phase.py` and
`collect_phase.py`) call the SAME `analyze_game()` entry point. Editing a prompt or
a phase helper in `analyzer.py` propagates to both modes. All code is plain sync `def` —
no asyncio. The only parallelism is a thread pool inside `ConverseBackend.run()` for
chunk fan-out.

**Tuning knobs** (all defined in `SteamPulseConfig`, bundled into `AnalyzerSettings`,
passed explicitly down the call chain — no hardcoded defaults in helpers):
`ANALYSIS_MAX_REVIEWS`, `ANALYSIS_CHUNK_SIZE`, `ANALYSIS_MAX_CHUNKS_PER_MERGE_CALL`,
`ANALYSIS_CHUNK_MAX_TOKENS`, `ANALYSIS_MERGE_MAX_TOKENS`, `ANALYSIS_SYNTHESIS_MAX_TOKENS`,
`ANALYSIS_CONVERSE_MAX_WORKERS`, `ANALYSIS_CHUNK_SHUFFLE_SEED`.

**Local per-phase dev loop:** `scripts/dev/run_phase.py --appid <id> --phase chunk|merge|synthesis`
runs the three-phase pipeline against your local Postgres + live Bedrock, stopping
after the requested phase. Idempotent — re-running `--phase synthesis` after `--phase chunk`
skips Phase 1 entirely via the chunk_hash cache.

**Critical:** Each output section answers a DIFFERENT question. No duplication between sections:
- `gameplay_friction` = what design is broken
- `churn_triggers` = WHEN it causes a player to leave
- `dev_priorities` = the ranked FIX (not a re-description)
- `player_wishlist` = net-new features (not fixes to broken things)

### Streaming persistence in fan-out phases (mandatory)

Any phase that fans out N independent LLM calls in parallel MUST persist
each result as soon as its future completes — not after the whole batch
returns. A failure on call N should NOT throw away the 0..N-1 successful
responses: they're already paid for in tokens, and the next run will skip
them via the cache.

The canonical implementation:

1. `ConverseBackend.run()` takes an optional `on_result: LLMResultCallback`
   (`Callable[[int, BaseModel], None]`). It's invoked from inside the
   `as_completed` loop as each future resolves, BEFORE the remaining
   futures finish.
2. Phase helpers (`run_chunk_phase` today; any future "map" phase the
   same way) define a nested `_persist(idx, response)` that writes the
   row via the repository and updates the local order-preserving dict.
   Pass this to `backend.run(pending, on_result=_persist)`.
3. The fan-out is cache-idempotent: `(appid, chunk_hash, prompt_version)`
   for chunks, `(appid, source_chunk_ids, prompt_version)` for merges.
   Re-running after a crash skips anything already persisted.

Anti-pattern to avoid:

```python
# DON'T — partial progress is lost on any failure
fresh = backend.run(pending)
for meta, response in zip(meta_list, fresh):
    repo.insert(..., response, ...)
```

The rule applies to Phase 1 (chunks) today. Phase 2's hierarchical merge
persists per-level inside the loop for the same reason. Phase 3 is a
single call — nothing to stream. Any NEW map-style phase (e.g. a future
per-genre fan-out) must follow this pattern.

Callback exceptions propagate and cancel the remaining futures — that's
intentional. Raising from the callback means "abort, you've got enough
partial progress persisted already." The outer cache-idempotent loop
handles the retry.

### Async — use it correctly

FastAPI routes are `async def`. The httpx Steam API calls are genuinely async (`httpx.AsyncClient`).
**psycopg2 is synchronous** — any repository method that runs SQL blocks the event loop. This is
acceptable for Lambda (one request at a time on a warm container) but means async provides no
concurrency benefit for DB-heavy operations. Never `await` a repository call — they are plain `def`.

Use `asyncio.TaskGroup` when parallelizing genuinely async work (e.g., multiple concurrent Steam
API fetches). Do not wrap sync repository calls in `asyncio.gather` expecting speedup.

### Lambda Web Adapter (FastAPI on Lambda)

FastAPI runs natively on Lambda via Lambda Web Adapter — zero code changes needed.
The Dockerfile copies the adapter binary. Use Lambda Function URLs, not API Gateway.
Initialize DB connections OUTSIDE the handler for connection reuse on warm invocations.

### Frontend (Next.js via OpenNext)

Next.js is deployed via OpenNext to Lambda. The frontend calls FastAPI at `/api/*`.
CloudFront routes: `/api/*` → FastAPI Lambda, `/*` → Next.js Lambda, `/static/*` → S3.

---

## API Endpoints (FastAPI)

| Endpoint | Notes |
|---|---|
| `GET /health` | Storage backend + version |
| `GET /api/games` | List games with filters (genre, tag, sentiment, etc.) |
| `GET /api/games/{appid}/report` | Full report + game metadata |
| `GET /api/games/{appid}/review-stats` | Weekly sentiment timeline + playtime buckets + velocity |
| `GET /api/games/{appid}/benchmarks` | Genre/tag benchmarks for this game |
| `GET /api/games/{appid}/audience-overlap` | Competitor overlap analysis |
| `GET /api/games/{appid}/playtime-sentiment` | Fine-grained playtime × sentiment + churn wall |
| `GET /api/games/{appid}/early-access-impact` | EA-era vs post-launch sentiment comparison |
| `GET /api/games/{appid}/review-velocity` | Monthly review volume trend (24 months) |
| `GET /api/games/{appid}/top-reviews` | Top reviews by helpfulness or humor votes |
| `GET /api/genres` | Genre list with game counts |
| `GET /api/tags/top` | Top tags by game count |
| `GET /api/tags/{slug}/trend` | Tag sentiment trend over time |
| `GET /api/analytics/price-positioning` | Price vs sentiment vs review count scatter |
| `GET /api/analytics/release-timing` | Release timing patterns |
| `GET /api/analytics/platform-gaps` | Platform coverage gaps |
| `GET /api/developers/{slug}/analytics` | Developer-level analytics |
| `POST /api/chat` | V2 only (pending Auth0 integration): NL → SQL → answer |

Analysis is NOT triggered via the API. Bulk/re-analysis is driven by the batch
Step Functions state machine in `infra/stacks/batch_analysis_stack.py`
(one execution per appid, three phases, idempotent caches). Admin re-analyze
goes through the same machine via a direct `StartExecution`.

---

## Report JSON Schema (`GameReport` in `analyzer_models.py`)

```
# Core — narrative only. Sentiment magnitude lives on the Game row (Steam's
# positive_pct / review_score_desc), NOT here. Joined at the API/UI layer.
game_name, appid, total_reviews_analyzed
sentiment_trend             # "improving" | "stable" | "declining" (Python-computed, window comparison)
sentiment_trend_note        # narrative explanation
sentiment_trend_reliable    # bool — True when each window has >= 50 reviews
sentiment_trend_sample_size # int  — total reviews across both trend windows
one_liner                   # gamer-facing, max 25 words
hidden_gem_score            # float 0.0-1.0, computed in Python from Steam's positive_pct + review_count

# Structured objects
audience_profile            # {ideal_player, casual_friendliness, archetypes[], not_for[]}
refund_signals              # {refund_language_frequency, primary_refund_drivers[], risk_level}
community_health            # {overall, signals[], multiplayer_population}
monetization_sentiment      # {overall, signals[], dlc_sentiment}
content_depth               # {perceived_length, replayability, value_perception, signals[], confidence, sample_size}

# Free sections
design_strengths[]          # what design decisions are working
gameplay_friction[]         # in-game UX/design problems (no biz complaints here)
technical_issues[]          # bugs, crashes, performance problems
genre_context               # genre benchmark, no named competitors

# Pro sections
player_wishlist[]           # net-new features only (not fixes)
churn_triggers[]            # journey moments that cause dropout (with timing)
dev_priorities[]            # [{action, why_it_matters, frequency, effort}] — ranked
competitive_context[]       # [{game, comparison_sentiment, note}] — named games only
```

---

## CDK Structure (infra/)

```
infra/
  app.py                    # CDK entry point — instantiates ApplicationStage directly (no pipeline)
  application_stage.py      # Wires all stacks in dependency order
  pipeline_stack.py         # ARCHIVED — kept for reference only, not used
  stacks/
    network_stack.py        # VPC
    data_stack.py           # RDS + S3, termination_protection=True
    messaging_stack.py      # SQS queues + DLQs + SNS topics
    compute_stack.py        # All Lambdas (crawlers, API, analyzer) + Step Functions + EventBridge
    delivery_stack.py       # CloudFront distributions + Route 53 + ACM (production)
    certificate_stack.py    # ACM cert (us-east-1) for production CloudFront alias
    frontend_stack.py       # Next.js Lambda (OpenNext) + CloudFront behaviour
    spoke_stack.py          # Cross-region spoke crawler Lambdas
    monitoring_stack.py     # CloudWatch via cdk-monitoring-constructs
```

Deploy command: `bash scripts/deploy.sh --env staging` (or `--env production`).
Do NOT re-add CodePipeline — it costs ~$10/month for no benefit during solo development.

CDK rules (mandatory):
- No physical resource names — let CDK generate. Exceptions:
  - **Cross-region resources** (S3 buckets, SQS queues referenced by spoke stacks) use deterministic names following `steampulse-{env}-{resource}` — CDK tokens cannot resolve cross-region, so spokes must reference by predictable name.
- No env var lookups inside constructs — pass as props or context
- Secrets in AWS Secrets Manager, referenced by ARN
- `data_stack` has `termination_protection=True`
- **Staging environment: CloudFront URL only — no custom domain, no ACM cert, no Route53 records. `steampulse.io` is production only.**
- **Production environment: ACM cert (us-east-1) + CloudFront alias + Route53 A record for `steampulse.io`.**
- **Monitoring: use `cdk-monitoring-constructs` (npm: `cdk-monitoring-constructs`) — never write raw CloudWatch alarms or dashboards by hand**
- **Secrets Manager grants:** use `secret.grant_read(role)` — never manual `add_to_policy` with raw secret ARNs. CDK's `grant_read` handles the 6-char random suffix that Secrets Manager appends to ARNs; raw ARN references miss it and cause `AccessDeniedException` at runtime.

---

## Environment Variables

### SSM-backed config (`_PARAM_NAME` convention)

Infrastructure resource identifiers (ARNs, URLs, bucket names) are **not** passed
directly as env vars. Instead, CDK publishes them to SSM Parameter Store and the
Lambda env var holds the **SSM parameter name**. Each Lambda resolves only the
params it needs at cold start via Powertools `get_parameter()` (cached 5 min).

**Three kinds of infrastructure env vars — clear naming conventions:**

- **`_SECRET_NAME` fields** — hold a Secrets Manager **name**. Lambda calls `get_secret_value(SecretId=name)` directly (one hop). Set in `.env`. `db.py` already implements this correctly for `DB_SECRET_NAME`.
- **`_PARAM_NAME` fields** — hold an SSM Parameter Store **path**. Lambda calls `get_parameter(path)` at cold start via Powertools (cached 5 min). Set in `.env`.
- **Literals** (`ENVIRONMENT`, `LLM_MODEL__*`) — used directly, no resolution needed.

```
# Literals — in .env, used directly
ENVIRONMENT             # staging | production
DATABASE_URL            # PostgreSQL connection string (local dev only)
AWS_DEFAULT_REGION      # us-west-2
BEDROCK_REGION          # Bedrock region (defaults to AWS_DEFAULT_REGION)
LLM_MODEL__CHUNKING     # Bedrock model ID for Haiku pass
LLM_MODEL__SUMMARIZER   # Bedrock model ID for Sonnet pass

# Secrets Manager names — in .env, Lambda calls get_secret_value(SecretId=name)
DB_SECRET_NAME                # steampulse/{env}/db-credentials
STEAM_API_KEY_SECRET_NAME     # steampulse/{env}/steam-api-key

# SSM parameter names — in .env, resolved at cold start via get_parameter()
SFN_PARAM_NAME                    # /steampulse/{env}/compute/sfn-arn
STEP_FUNCTIONS_PARAM_NAME         # /steampulse/{env}/compute/sfn-arn (alias)
APP_CRAWL_QUEUE_PARAM_NAME        # /steampulse/{env}/messaging/app-crawl-queue-url
REVIEW_CRAWL_QUEUE_PARAM_NAME     # /steampulse/{env}/messaging/review-crawl-queue-url
ASSETS_BUCKET_PARAM_NAME          # /steampulse/{env}/data/assets-bucket-name
GAME_EVENTS_TOPIC_PARAM_NAME      # /steampulse/{env}/messaging/game-events-topic-arn
CONTENT_EVENTS_TOPIC_PARAM_NAME   # /steampulse/{env}/messaging/content-events-topic-arn
SYSTEM_EVENTS_TOPIC_PARAM_NAME    # /steampulse/{env}/messaging/system-events-topic-arn

# Non-config overrides (per-Lambda in CDK only)
POWERTOOLS_SERVICE_NAME            # e.g., "crawler", "api"
POWERTOOLS_METRICS_NAMESPACE       # "SteamPulse"
PORT                               # 8080 for FastAPI Lambda
RESEND_API_KEY                     # Email
```

**CDK pattern — `to_lambda_env()` needs only `POWERTOOLS_*` overrides:**
```python
environment=config.to_lambda_env(
    POWERTOOLS_SERVICE_NAME="crawler",
    POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
)
```

Everything else comes from `.env`. No CDK token overrides. No ARN passing. The RDS secret must use `credentials=rds.Credentials.from_generated_secret("postgres", secret_name=f"steampulse/{env}/db-credentials")` to get a deterministic name.

**Spoke exception:** cross-region spoke Lambdas can't resolve SSM from the primary
region, so `_PARAM_NAME` fields hold actual values in the spoke stack's inline env dict.
The spoke handler uses them directly without `get_parameter()`.

---

## Python Code Style (Python 3.12+)

Ruff is configured in `pyproject.toml`. Run `poetry run ruff check .` and `poetry run ruff format .` before committing.

**Syntax — always use modern Python 3.12 forms:**
- Union types: `str | None` not `Optional[str]`. Never import `Optional`.
- Type hints: required on ALL function parameters and return types, including `-> None`.
- `from __future__ import annotations` is NOT needed in 3.12 — omit it.
- Use `match` statements for multi-branch dispatch over long `if/elif` chains.
- f-strings everywhere — no `%` formatting, no `.format()`.
- `pathlib.Path` over `os.path` for all filesystem operations.
- `tomllib` (stdlib) for TOML, `json` (stdlib) for JSON — no third-party parsers.

**Async — FastAPI context:**
- All I/O-bound functions must be `async def`. Never use blocking calls (`requests`, `time.sleep`) in async code.
- Use `asyncio.TaskGroup` (3.11+) instead of `asyncio.gather` for structured concurrency.
- `httpx.AsyncClient` for all outbound HTTP — create once, reuse via dependency injection.
- Lambda: initialize DB connections and `httpx.AsyncClient` at module level (outside handler) for warm reuse.

**Data structures:**
- Use `pydantic.BaseModel` for all domain objects and structured data — never plain `dict`, never `dataclasses.dataclass`. Pydantic is the project standard: it validates on construction, serializes with `.model_dump()`, and is consistent with every other model in `library_layer/models/`.
- Use `TypedDict` only for JSON-serializable shapes that don't need methods.
- Prefer immutable defaults: `tuple` over `list` for fixed collections, `frozenset` for sets.

**Error handling:**
- Raise specific exceptions — never bare `except:` or `except Exception:` without re-raise or logging.
- **No silent failure on init.** Lambda module-level initialization (DB connections, boto3 clients,
  `SteamPulseConfig()`) must run without `try/except`. If it fails, the cold start crashes — that's
  correct. Never swallow init errors with `except Exception: pass` or fall back to `None`.
- **No default values for infrastructure config.** All ARNs, URLs, and bucket names in `SteamPulseConfig`
  are required fields with no defaults. Every Lambda gets every env var set by CDK. If a field is missing,
  `ValidationError` at cold start is the correct behavior — never use `= ""` or `= None` as a silent fallback.
- Service constructors: required dependencies (`sns_client`, `config`, repos) are **not optional**.
  Type them as required params, not `| None`. If a caller can't provide them, that's a bug.
- FastAPI endpoints: raise `HTTPException` with appropriate status codes. Never return error dicts with 200.
- Use Powertools `Logger` — not stdlib `logging`, not `print()`. Use structured fields via `extra={}`: `logger.error("msg", extra={"appid": appid})`.

**Imports — ALL at the top of the file:**
Every `import` / `from ... import ...` goes in the module header block at
the top of the file. No imports inside functions, methods, `if`/`else`
branches, or `try` blocks. This is non-negotiable:

- Inline imports hide the module's true dependency graph, making it
  impossible to see what a file needs at a glance.
- They defer failure until the first call site executes, so an import
  error that would have been caught at cold-start surfaces deep inside a
  request handler instead.
- Ruff's import-sorter can't order them; circular-import detection can't
  see them; test collection can't pre-import them.
- "I only need it in one branch" is not a justification — a single
  top-level import costs nothing at runtime after the module is loaded.

The narrow, named exceptions:
- **Genuine circular import** that cannot be broken by refactoring. Rare
  and should be fixed, not worked around.
- **Truly optional dependencies** gated behind a feature flag (e.g.
  `if USE_OPTIONAL_LIB: import optional_lib`). SteamPulse does not have
  any of these today.
- **Lazy loading of something huge** at cold-start-sensitive paths, with
  a comment explaining the measured cost. Does not apply to normal
  library imports.

If you find yourself reaching for an inline import because you added a
helper in the middle of a function: stop, scroll to the top, add it
there, then go back and finish the helper.

**No defaults in function signatures — pass values explicitly from the entry point:**
Tuning knobs, bounds, token budgets, timeouts, retry counts, thread pool
sizes, chunk sizes, magic constants — none of these belong as default
parameter values in helper functions. Every function that depends on a
knob takes it as a **required** (keyword-only) argument. The default
lives in **exactly one place**: `SteamPulseConfig` (or another
config-layer pydantic model). The handler reads config once and passes
values explicitly down the call chain.

Rationale:
- A default buried in a helper is an **assumption** that cannot be
  seen from the call site. Two callers can disagree about what the
  "right" value is and silently use different ones.
- When the config changes, every hardcoded default must be hunted down
  and updated. Explicit passing makes the data flow searchable.
- Tests must pass explicit values, so test fixtures document the
  operating conditions rather than relying on whatever default the
  code currently happens to carry.
- Misconfiguration fails loudly at the handler boundary instead of
  silently producing degraded output.

Examples:

```python
# ❌ BAD — default hides the assumption, two callers drift apart
def run_merge(summaries, max_per_call=40):
    ...

# ❌ BAD — module constant is still an assumption, just hoisted up
MAX_PER_CALL = 40
def run_merge(summaries):
    for group in chunks_of(summaries, MAX_PER_CALL):
        ...

# ✅ GOOD — required keyword arg, value flows from config
def run_merge(summaries, *, max_chunks_per_merge_call: int):
    if max_chunks_per_merge_call <= 0:
        raise ValueError(...)
    ...

# Handler (the ONE place config is read):
settings = AnalyzerSettings.from_config(config)
run_merge(summaries, max_chunks_per_merge_call=settings.max_chunks_per_merge_call)
```

For a bundle of related knobs that flow together, define a pydantic
model (e.g. `AnalyzerSettings`) and pass the bundle. See
`library_layer/analyzer.py::AnalyzerSettings` for the canonical pattern.

Optional values (e.g. `temporal`, `metadata`, unknown-at-call-site
fields) are still passed explicitly — the parameter is typed
`T | None` with NO default, and the caller writes `temporal=None` at
the call site if they genuinely have nothing. This forces every caller
to consciously decide whether they have the value, rather than
inheriting a silent `None` from the signature.

Exceptions (narrow and named):
- **Test seams** (e.g. `s3_client: object | None = None` on a backend
  constructor so tests can inject a mock) — acceptable because the
  default is a dependency-injection slot, not a tuning knob.

**General:**
- No mutable default arguments (`def f(x=[])` → use `None` sentinel).
- Prefer `|` dict merge (`{**a, **b}` → `a | b`) in 3.9+.
- `enumerate()` over manual index counters. `zip(strict=True)` when lengths must match.
- Keep functions under 40 lines. Extract helpers rather than nesting.

---

## Data Freshness Strategy

Two EventBridge rules on the crawler Lambda keep `app_catalog` and game metadata current:

**1. Hourly catalog refresh** (`CatalogRefreshRule`)
- Fires `CatalogService.refresh()`: pulls Steam `IStoreService/GetAppList`, `bulk_upsert` into `app_catalog` (`ON CONFLICT DO NOTHING` — new rows default to `meta_status='pending'`), then `enqueue_pending()` sends `task=metadata` SQS messages for every pending appid.
- Net effect: new Steam releases appear and start crawling within ~1h.

**2. Daily stale re-crawl** (`StaleMetaRefreshRule` → `{"action": "stale_refresh"}`)
- Fires `CatalogService.enqueue_stale(limit=2000)` → `CatalogRepository.find_stale_meta()`.
- Tiered staleness (priority order):
  | Tier | Criteria | Refresh after |
  |---|---|---|
  | 1 | `coming_soon=TRUE` OR has genre 70 (Early Access) | 7 days |
  | 2 | `review_count >= 1000` (popular) | 7 days |
  | 3 | Everything else with `meta_status='done'` | 30 days |
- `NULLS FIRST` so legacy rows (pre-`meta_crawled_at`) refresh first.
- Enqueues **both** `task=metadata` and `task=tags` per appid so `meta_crawled_at` and `tags_crawled_at` advance together. The ingest path is identical to a fresh crawl.

**Delete-and-replace invariant for associations**
- `tag_repo.upsert_genres / upsert_categories / upsert_tags` delete any existing rows for the appid that are NOT in the incoming set, then insert. This is required so that genres/categories/tags removed on Steam's side (e.g. genre 70 disappearing when a game leaves Early Access) actually disappear from our DB. Never use `INSERT ... ON CONFLICT DO NOTHING` for associations — that path leaks stale rows forever.

**Review re-crawl** is handled by the separate review pipeline with cursor-based continuation — not in scope for these rules.

---

## Frontend Testing

Playwright E2E tests live in `frontend/tests/`. Run with:

```bash
cd frontend
npm run test:e2e          # all tests (headless, starts prod build)
npm run test:e2e:ui       # interactive Playwright UI
PLAYWRIGHT_BASE_URL=https://staging.steampulse.io npm run test:e2e  # against staging
```

**Rule: any frontend change that alters user-visible behaviour must include test updates in the same PR.**

When making frontend changes, always:
1. Check `frontend/tests/` for existing tests covering the area you're changing
2. Update tests that would fail due to your change — don't delete, update
3. Add new tests for new user-facing behaviour
4. Mock data is in `frontend/tests/fixtures/mock-data.ts` — update if you add API response fields
5. API mocking is in `frontend/tests/fixtures/api-mock.ts` — update if endpoints change

Tests are excluded from the Next.js build (`tests/` in `tsconfig.json` exclude array). Never import from `tests/` inside `app/` or `components/`.

---

## Database Migrations (yoyo)

Schema DDL is managed by yoyo-migrations in `src/lambda-functions/migrations/`. The `MigrationFn` Lambda applies pending migrations post-deployment (after code is live). Migrations are **idempotent** — safe to run multiple times.

### Backwards-compatibility rules (mandatory)

Migrations run after the new Lambda code is already live. New code must work with the old schema for the brief window between deploy and migration apply.

- New columns must have a `DEFAULT` value or be nullable — never `NOT NULL` without a default on an existing table
- Never rename or drop a column/table in a single deploy; use two phases:
  1. Deploy: add the new column/table (migration + code that writes both old and new)
  2. Deploy: remove the old path once no code references it
- Index additions are always safe (read-only improvement, no query breakage)

### How to add a new migration

**1. Name the file** — use the next number in sequence, with a short snake_case description:
```
src/lambda-functions/migrations/0007_add_some_column.sql
```

**2. Add the yoyo header** — the first line must declare the dependency:
```sql
-- depends: 0006_add_analytics_indexes
```
Chain to the immediately preceding migration (check the directory for the current highest number).

**3. Write idempotent SQL** — always use guards:
```sql
ALTER TABLE games ADD COLUMN IF NOT EXISTS new_col TEXT;
CREATE TABLE IF NOT EXISTS new_table (...);
DROP INDEX IF EXISTS old_idx;
```

**4. For new indexes — use `CONCURRENTLY` and mark non-transactional:**
```sql
-- depends: 0006_add_analytics_indexes
-- transactional: false

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_name ON table(col);
```
`CONCURRENTLY` avoids write-blocking locks on large tables. Postgres requires it to run outside a transaction; `-- transactional: false` tells yoyo not to wrap the file in `BEGIN/COMMIT`.

**5. Test locally:**
```bash
bash scripts/dev/migrate.sh
```
For staging (tunnel must be open): `bash scripts/dev/migrate.sh --stage staging`

**6. Also update `schema.py`** — keep it in sync as a human-readable reference. Add new columns to the relevant `CREATE TABLE` block and note them in a comment. Do not add ALTER TABLE entries — those are legacy stubs kept for test-suite idempotency only.

### Never
- Call `create_all()` or `create_indexes()` from Lambda handlers — test-suite only
- Use plain `CREATE INDEX` on large tables in production migrations — always `CONCURRENTLY`
- Add a `NOT NULL` column without a `DEFAULT` to an existing table

---

## Observability (Logging + X-Ray)

### Logging

Every Lambda handler and library layer service uses **AWS Lambda Powertools `Logger`** — never stdlib `logging`, never `print()`.

**Handler pattern:**
```python
from aws_lambda_powertools import Logger
logger = Logger(service="analysis")   # explicit service name
```

**Library layer pattern:**
```python
from aws_lambda_powertools import Logger
logger = Logger()   # inherits service from POWERTOOLS_SERVICE_NAME env var
```

**Structured fields — always use `extra={}`:**
```python
logger.info("Reviews upserted", extra={"appid": appid, "upserted": upserted})
logger.error("Steam API error", extra={"appid": appid, "error": str(exc)})
```
No `%` formatting, no f-strings embedding data in the message string. Powertools serializes `extra={}` keys as top-level JSON, making them queryable in CloudWatch Logs Insights: `filter appid = 440`.

**Appid context — `append_keys()`:**
Call `logger.append_keys(appid=appid)` at the top of any handler branch or FastAPI route that processes a specific appid. All subsequent log calls in that invocation will carry the appid automatically.

`append_keys()` context is **per Logger instance** — it does NOT propagate to separate `Logger()` instances in library layer services. Library layer code must include appid explicitly in every `extra={}` call.

**Lambda context injection:**
Add `@logger.inject_lambda_context` to handlers that accept a `LambdaContext` object. Tests must pass a mock context (not `None`) when the handler has this decorator — `inject_lambda_context` reads `context.function_name` etc.

**Reserved LogRecord fields — do not use in `extra={}`:**
`name`, `message`, `levelname`, `pathname`, `lineno`, `funcName`, `created`, `thread`, `process` are Python `logging.LogRecord` attributes. Passing any of these in `extra={}` raises `KeyError` at runtime. Use `game_name` instead of `name`, etc.

---

### X-Ray Tracing

Every **production** Lambda handler requires X-Ray to be enabled in **two places** — missing either half silently drops traces:

1. **Code** — import `Tracer` and decorate the handler:
```python
from aws_lambda_powertools import Tracer
tracer = Tracer(service="crawler")

@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    ...
```

2. **CDK** — set `tracing=lambda_.Tracing.ACTIVE` on the `PythonFunction` construct:
```python
crawler_fn = PythonFunction(
    ...
    tracing=lambda_.Tracing.ACTIVE,   # required — also grants AWSXRayDaemonWriteAccess automatically
)
```
CDK automatically adds `AWSXRayDaemonWriteAccess` to the Lambda role when this is set — no manual IAM policy needed.

**FastAPI / Mangum special case:**
`handler = Mangum(app)` is an assignment, not a function, so `@tracer.capture_lambda_handler` cannot be applied directly. Wrap it explicitly:
```python
_mangum = Mangum(app, lifespan="off")

@tracer.capture_lambda_handler
def handler(event: dict, context: object) -> dict:
    return _mangum(event, context)
```

**Do NOT add `@tracer.capture_method`** to service layer methods — structured logs already provide that observability; X-Ray overhead on DB calls adds noise without insight.

**Intentionally excluded from X-Ray** (internal tools, not on any critical path):
- `admin/handler.py`
- `admin/migrate_handler.py`

**Current tracing coverage:**

| Lambda        | Logger | Tracer (code) | Tracer (CDK)     |
|---------------|--------|---------------|------------------|
| analysis      | ✅     | ✅            | ✅               |
| api           | ✅     | ✅            | ✅               |
| crawler       | ✅     | ✅            | ✅               |
| spoke-ingest  | ✅     | ✅            | ✅               |
| crawler-spoke | ✅     | ✅            | ✅ (spoke_stack) |
| admin         | ✅     | — intentional | — intentional    |
| migration     | ✅     | — intentional | — intentional    |

**X-Ray cost note:** Default sampling traces the first request per second plus 5% of additional requests — $5/million traces after the first 100k/month free. Cost is negligible at current scale.

---

## Do Not Build

- No user accounts or login system
- No CSS frameworks (use Tailwind or plain CSS in Next.js)
- No job queue inside FastAPI (analysis is in Step Functions)
- No payment integration until explicitly planned
- No Terraform (CDK only)
- No separate Railway deployment
- No Jinja2 templates (frontend is Next.js)
- No SQLAlchemy or any ORM — raw psycopg2 in repositories only
- No business logic in repositories, no SQL in services — maintain the layer boundary
- DO NOT ADD __init__.py files, unless they have actual content
