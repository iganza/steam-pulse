# CLAUDE.md

This file is Claude Code's persistent memory for SteamPulse. Read it fully before touching any code.

## Architecture Reference

All component definitions and interaction flows live in **`ARCHITECTURE.org`** at the repo root.
Read it before modifying any handler, service, queue, or SNS topic.
Each flow has an invariant statement and a **drift checklist** — verify those items when implementing or changing a flow.
When adding a new interaction, add its sequence diagram to `ARCHITECTURE.org` first.

## What This Project Is

**SteamPulse** — AI-powered Steam game intelligence platform at **steampulse.io**.

- **Public site**: AI-synthesized review reports for ALL Steam games with any reviews. SEO-driven, cross-linked, no ads.
- **Premium layer**: Developer-focused. Unlocks `dev_priorities`, `churn_triggers`, `player_wishlist` and pro-tier analytics sections. Gated via Auth0 JWT `"pro"` role claim (see `scripts/prompts/auth0-authentication.md`).
- **Pro tier (V2)**: NL chat over full catalog. Not yet available — pending Auth0 integration.

Full architecture decisions in `steampulse-design.org` at the repo root. Read it for anything not covered here.

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
        analyzer.py     # LLM two-pass analysis orchestration (Haiku + Sonnet)
        config.py       # SteamPulseConfig (env var parsing)
        fetcher.py      # HTTP client wrapper
        reporter.py     # Report generation / storage
        schema.py       # PostgreSQL schema reference
        steam_source.py # Steam API abstraction (SteamDataSource)
        models/         # Domain + LLM output models
          analyzer_models.py  # GameReport, ChunkSummary + all LLM output types
          catalog.py    # CatalogEntry
          game.py       # Game, GameSummary
          report.py     # Report (DB wrapper for stored report_json)
          review.py     # Review
          tag.py        # Tag, Genre, Category
        repositories/   # SQL I/O: game_repo, review_repo, report_repo, analytics_repo, etc.
        services/       # Business logic: analysis_service, crawl_service, catalog_service
        utils/          # Shared helpers: db, sqs, ssm, slugify, events, time, steam_metrics
    lambda-functions/   # All Lambda handlers
      lambda_functions/
        analysis/       # LLM two-pass analysis handler
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
  main.py               # CLI tool for local LLM testing
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

# CLI analysis (local LLM testing)
poetry run python main.py --appid 440
poetry run python main.py --appid 440 --max-reviews 200 --json
poetry run python main.py --appid 440 --dry-run  # no LLM

# CDK (infra)
poetry install --with infra
poetry run cdk synth
poetry run cdk deploy  # only needed once to bootstrap pipeline

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
lives in `library_layer/utils/`. Examples: `slugify()`, `send_sqs_batch()`, `row_to_model()`,
timestamp helpers. Import from utils — never duplicate.

### SteamDataSource abstraction (steam_source.py)

All Steam data access goes through `SteamDataSource`. Currently only `DirectSteamSource`
(calls Steam API directly). SteamSpy is NOT used — Steam's own API provides all required fields.

### LLM Two-Pass Analysis (analyzer.py)

**Pass 1 (Haiku — cheap, parallel):** 50-review chunks → extract 11 signal types:
`design_praise`, `gameplay_friction`, `wishlist_items`, `dropout_moments`, `competitor_refs`,
`notable_quotes`, `technical_issues`, `refund_signals`, `community_health`,
`monetization_sentiment`, `content_depth`

**Pass 2 (Sonnet — synthesis):** All chunk signals → structured `GameReport` JSON.
`sentiment_score` and `hidden_gem_score` are computed in Python BEFORE calling Sonnet — never LLM-guessed.

**Execution path:** Real-time only — `AnthropicBedrock` via **Converse API** (`bedrock_runtime.converse()`).
Model-agnostic — swap model ID via env var, zero code changes. Batch Inference path is designed
but not yet implemented (see `scripts/prompts/bedrock-batch-analysis.md`).

**Critical:** Each output section answers a DIFFERENT question. No duplication between sections:
- `gameplay_friction` = what design is broken
- `churn_triggers` = WHEN it causes a player to leave
- `dev_priorities` = the ranked FIX (not a re-description)
- `player_wishlist` = net-new features (not fixes to broken things)

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
| `POST /api/preview` | Free: triggers analysis, returns `game_name`, `overall_sentiment`, `sentiment_score`, `one_liner`. 1 per IP. |
| `GET /api/status/{job_id}` | Step Functions job polling |
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

Rate limit on `/api/preview`: 1 free analysis per IP. Returns `402 {"error": "free_limit_reached"}` on breach.

---

## Report JSON Schema (`GameReport` in `analyzer_models.py`)

```
# Core
game_name, appid, total_reviews_analyzed
overall_sentiment           # "Overwhelmingly Positive" … "Overwhelmingly Negative"
sentiment_score             # float 0.0–1.0, computed in Python
sentiment_trend             # "improving" | "stable" | "declining"
sentiment_trend_note        # narrative explanation
one_liner                   # gamer-facing, max 25 words
hidden_gem_score            # float 0.0–1.0, computed in Python

# Structured objects
audience_profile            # {ideal_player, casual_friendliness, archetypes[], not_for[]}
refund_risk                 # {refund_language_frequency, primary_refund_drivers[], risk_level}
community_health            # {overall, signals[], multiplayer_population}
monetization_sentiment      # {overall, signals[], dlc_sentiment}
content_depth               # {perceived_length, replayability, value_perception, signals[]}

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
  app.py                    # CDK entry point
  pipeline_stack.py         # Self-mutating CDK Pipeline (CodeStar Connection to GitHub)
  application_stage.py
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

CDK rules (mandatory):
- No physical resource names — let CDK generate. Exceptions:
  - `pipeline_name="steampulse"` on the CodePipeline — singleton, no conflict risk, humans need to find it in Console.
  - **Cross-region resources** (S3 buckets, SQS queues referenced by spoke stacks) use deterministic names following `steampulse-{env}-{resource}` — CDK tokens cannot resolve cross-region, so spokes must reference by predictable name.
- No env var lookups inside constructs — pass as props or context
- Secrets in AWS Secrets Manager, referenced by ARN
- `data_stack` has `termination_protection=True`
- Pipeline uses `CodePipelineSource.connection()` — NOT a PAT token
- **Staging environment: CloudFront URL only — no custom domain, no ACM cert, no Route53 records. `steampulse.io` is production only.**
- **Production environment: ACM cert (us-east-1) + CloudFront alias + Route53 A record for `steampulse.io`. Gated by `ManualApprovalStep` in the pipeline.**
- **Monitoring: use `cdk-monitoring-constructs` (npm: `cdk-monitoring-constructs`) — never write raw CloudWatch alarms or dashboards by hand**

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
- Use `dataclasses.dataclass` or `pydantic.BaseModel` for structured data — never plain `dict` for domain objects.
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

**General:**
- No mutable default arguments (`def f(x=[])` → use `None` sentinel).
- Prefer `|` dict merge (`{**a, **b}` → `a | b`) in 3.9+.
- `enumerate()` over manual index counters. `zip(strict=True)` when lengths must match.
- Keep functions under 40 lines. Extract helpers rather than nesting.

---

## Data Freshness Strategy

TBD

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
- No database migrations framework for data access (raw psycopg2 in repositories) — yoyo-migrations is used for schema DDL only (see `src/lambda-functions/migrations/`)
- No CSS frameworks (use Tailwind or plain CSS in Next.js)
- No job queue inside FastAPI (analysis is in Step Functions)
- No payment integration until explicitly planned
- No Terraform (CDK only)
- No separate Railway deployment
- No Jinja2 templates (frontend is Next.js)
- No SQLAlchemy or any ORM — raw psycopg2 in repositories only
- No business logic in repositories, no SQL in services — maintain the layer boundary
- DO NOT ADD __init__.py files, unless they have actual content
