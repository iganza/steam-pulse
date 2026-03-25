# CLAUDE.md

This file is Claude Code's persistent memory for SteamPulse. Read it fully before touching any code.

## What This Project Is

**SteamPulse** — AI-powered Steam game intelligence platform at **steampulse.io**.

- **Public site**: AI-synthesized review reports for ALL Steam games with any reviews. SEO-driven, cross-linked, no ads.
- **Premium layer**: Developer-focused. Unlocks `dev_priorities`, `churn_triggers`, `player_wishlist` and pro-tier analytics sections. Payment integration is deferred — `/api/validate-key` currently stubs full access (always grants all sections).
- **Pro tier (V2)**: NL chat over full catalog. Feature-flagged behind `PRO_ENABLED=true`.

Full architecture decisions in `steampulse-design.org` at the repo root. Read it for anything not covered here.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Backend API | Python 3.12, FastAPI (JSON API only — no HTML rendering), uvicorn, httpx |
| Frontend | Next.js (React SSR/ISR) in `frontend/`, deployed via OpenNext to Lambda |
| LLM | Haiku 4.5 (chunk pass), Sonnet 4.6 (synthesis). Model IDs via `LLM_MODEL__CHUNKING` / `LLM_MODEL__SUMMARIZER` env vars. AWS Bedrock (`anthropic.AnthropicBedrock()`), Converse API. Batch Inference planned — not yet implemented. |
| DB | PostgreSQL on RDS. All access via Repository classes. Locally use Docker Postgres via `./scripts/dev/start-local.sh` |
| Hosting | AWS Lambda (container image) + CloudFront + Route 53. **No Railway. No Fargate.** |
| Infra | AWS CDK v2 (Python) in `infra/`. CDK Pipelines (self-mutating). |
| Payments | **None currently.** `/api/validate-key` stubs full access — payment integration deferred. |
| Email | Resend |
| Deps | Poetry — `pyproject.toml` is source of truth. No `requirements.txt`. |

---

## Monorepo Structure

```
repo-root/
  src/
    library-layer/      # Shared Lambda layer: httpx, psycopg2, boto3, anthropic + framework code
      library_layer/    # analyzer, storage, steam_source, fetcher, reporter
    lambda-functions/   # All Lambda handlers
      lambda_functions/
        app_crawler/    # Crawls Steam metadata → writes to DB → triggers events
        review_crawler/ # Fetches reviews → writes to DB → triggers Step Functions
        api/            # FastAPI app: all /api/* endpoints
  frontend/             # Next.js app (React)
  infra/                # AWS CDK v2 (Python)
  scripts/
    dev/                # Local dev helpers (start-local.sh, run-api.sh, db-tunnel.sh, push-to-staging.sh)
    seed.py             # Bootstrap top-N games into SQS
    sp.py               # CLI for queueing review crawls, checking status
    aws-costs.sh        # AWS cost report
    prompts/            # Active feature design specs
  main.py               # CLI tool for local LLM testing
  pyproject.toml        # Python deps (main + infra groups)
  cdk.json              # "app": "poetry run python infra/app.py"
  docker-compose.yml    # Local Postgres for dev
  CLAUDE.md
  steampulse-design.org
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

# Frontend local dev
cd frontend && npm install && npm run dev

# Tests
poetry run pytest -v
poetry run ruff check .
poetry run ruff format .

# Seed / queue scripts
export APP_CRAWL_QUEUE_PARAM_NAME="/steampulse/staging/messaging/app-crawl-queue-url"
poetry run python scripts/seed.py --limit 50   # staging
poetry run python scripts/seed.py --dry-run --limit 5   # smoke test
poetry run python scripts/seed.py              # production (full crawl)
poetry run python scripts/sp.py queue reviews --appid 440  # queue single game
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
| `GET /health` | Storage backend + pro_enabled status |
| `POST /api/preview` | Free: triggers analysis, returns `game_name`, `overall_sentiment`, `sentiment_score`, `one_liner`. 1 per IP. |
| `POST /api/validate-key` | **Stubbed** — always returns full report with `activations_remaining: 99`. Payment deferred. |
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
| `POST /api/chat` | V2 only (`PRO_ENABLED=true`): NL → SQL → answer |

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
- **Literals** (`ENVIRONMENT`, `LLM_MODEL__*`, `PRO_ENABLED`) — used directly, no resolution needed.

```
# Literals — in .env, used directly
ENVIRONMENT             # staging | production
DATABASE_URL            # PostgreSQL connection string (local dev only)
AWS_DEFAULT_REGION      # us-west-2
BEDROCK_REGION          # Bedrock region (defaults to AWS_DEFAULT_REGION)
PRO_ENABLED             # 'true' enables /api/chat (V2)
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
- Log with `logging` (stdlib) — not `print()`. Use structured fields: `logger.error("msg", extra={"appid": appid})`.

**General:**
- No mutable default arguments (`def f(x=[])` → use `None` sentinel).
- Prefer `|` dict merge (`{**a, **b}` → `a | b`) in 3.9+.
- `enumerate()` over manual index counters. `zip(strict=True)` when lengths must match.
- Keep functions under 40 lines. Extract helpers rather than nesting.

---

## Data Freshness Strategy

See `steampulse-design.org` for the full tiered strategy. Summary:

**Current implementation:** One weekly EventBridge rule (`CatalogRefreshRule`, disabled until
post-launch) in `compute_stack.py` triggers a full catalog refresh.

**Planned tiered rules** (not yet implemented — design target):

| Rule | Schedule | Scope |
|---|---|---|
| `nightly-top500` | Daily 6am UTC | Top 500 games — metadata + reviews + re-analysis |
| `weekly-mid-tier` | Sundays 8am UTC | review_count 500–5000 |
| `monthly-long-tail` | 1st of month | review_count < 500, metadata only |
| `weekly-discovery` | Mondays 7am UTC | Full Steam app list — finds new games not in DB |

**Staleness signal:** `last_analyzed` is returned in all API responses.
Frontend shows "Analysis from X days ago" and a "Refresh available" badge after 30 days.

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

## Do Not Build

- No user accounts or login system
- No database migrations framework (raw SQL in repositories)
- No CSS frameworks (use Tailwind or plain CSS in Next.js)
- No job queue inside FastAPI (analysis is in Step Functions)
- No payment integration until explicitly planned (validate-key is intentionally stubbed)
- No Terraform (CDK only)
- No separate Railway deployment
- No Jinja2 templates (frontend is Next.js)
- No SQLAlchemy or any ORM — raw psycopg2 in repositories only
- No business logic in repositories, no SQL in services — maintain the layer boundary
