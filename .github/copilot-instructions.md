# SteamPulse — Copilot Coding Agent Instructions

Read this file in full before making any changes. It contains the authoritative
guide for working efficiently on this codebase. The companion file `CLAUDE.md`
at the repo root contains the same information in a slightly different format —
both must stay consistent.

---

## What This Project Is

**SteamPulse** — AI-powered Steam game intelligence platform at **steampulse.io**.

- **Public site**: AI-synthesized review reports for every Steam game that has reviews.
  SEO-driven, cross-linked, no ads.
- **Premium layer**: Developer-facing. Unlocks `dev_priorities`, `churn_triggers`,
  `player_wishlist` sections via a Lemon Squeezy license key.
- **Pro tier (V2)**: Natural-language chat over the full catalogue, feature-flagged
  behind `PRO_ENABLED=true`.

Full design rationale lives in `steampulse-design.org` at the repo root.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Backend API | Python 3.12, FastAPI (JSON only — no HTML rendering), uvicorn, httpx |
| Frontend | Next.js (React SSR/ISR) in `frontend/`, deployed via OpenNext to Lambda |
| LLM | `claude-3-5-haiku-20241022` (chunk pass) · `claude-3-5-sonnet-20241022` (synthesis) |
| DB | PostgreSQL on RDS. `BaseStorage` abstraction — `PostgresStorage` via `DATABASE_URL`. Local dev uses Docker Postgres. |
| Hosting | AWS Lambda (container image) + CloudFront + Route 53. **No Railway. No Fargate.** |
| Infra | AWS CDK v2 (Python) in `infra/`. CDK Pipelines (self-mutating). |
| Payments | Lemon Squeezy (license-key model, handles VAT) |
| Email | Resend |
| Deps | Poetry — `pyproject.toml` is the single source of truth. No `requirements.txt`. |

---

## Monorepo Layout

```
repo-root/
  src/
    library-layer/          # Shared Lambda layer: httpx, psycopg2, boto3, anthropic + framework
      library_layer/        # analyzer, storage, steam_source, fetcher, reporter
    lambda-functions/       # Lambda handlers
      lambda_functions/
        app_crawler/        # Crawls Steam metadata → DB → queues review crawl
        review_crawler/     # Fetches reviews → DB → triggers Step Functions
        api/                # FastAPI app: /preview, /validate-key, /health, /chat
  frontend/                 # Next.js app (React)
  infra/                    # AWS CDK v2 (Python)
    stacks/
      common_stack.py       # LibraryLayer Lambda layer
      network_stack.py      # VPC
      sqs_stack.py          # SQS queues + DLQs
      lambda_stack.py       # Lambda functions (crawlers) + EventBridge schedules
      data_stack.py         # RDS + S3  (termination_protection=True)
      analysis_stack.py     # Step Functions state machine
      app_stack.py          # FastAPI Lambda + Function URL + CloudFront + Route53 + ACM
      frontend_stack.py     # Next.js Lambda (OpenNext) + CloudFront behaviour
      monitoring_stack.py   # CloudWatch via cdk-monitoring-constructs
  scripts/
    dev/                    # start-local.sh, invoke-*.sh, run-api.sh
    seed.py                 # Bootstrap top-N games into SQS
  main.py                   # CLI tool for local LLM testing
  pyproject.toml            # Python deps (main + infra groups)
  cdk.json                  # CDK entry: "app": "poetry run python infra/app.py"
  docker-compose.yml        # Local Postgres for dev
  tests/                    # pytest test suite
```

---

## Essential Commands

```bash
# ── Install dependencies ──────────────────────────────────────────────────────
poetry install                        # main deps
poetry install --with infra           # + CDK deps
poetry install --with crawler         # + boto3

# ── Local dev ─────────────────────────────────────────────────────────────────
./scripts/dev/start-local.sh          # start Postgres + init schema
./scripts/dev/run-api.sh              # FastAPI at http://localhost:8000
./scripts/dev/invoke-app-crawler.sh 440
./scripts/dev/invoke-review-crawler.sh 440

# ── Linting / formatting (ALWAYS run before committing) ──────────────────────
poetry run ruff check .
poetry run ruff format .

# ── Tests ─────────────────────────────────────────────────────────────────────
poetry run pytest -v

# ── CDK (infra) ───────────────────────────────────────────────────────────────
poetry run cdk synth
poetry run cdk deploy   # only needed once to bootstrap the pipeline

# ── Frontend ──────────────────────────────────────────────────────────────────
cd frontend && npm install && npm run dev

# ── CLI analysis (local LLM testing) ─────────────────────────────────────────
poetry run python main.py --appid 440
poetry run python main.py --appid 440 --max-reviews 200 --json
poetry run python main.py --appid 440 --dry-run   # no LLM

# ── Seed script ───────────────────────────────────────────────────────────────
export APP_CRAWL_QUEUE_URL="https://sqs.us-west-2.amazonaws.com/..."
poetry run python scripts/seed.py --dry-run --limit 5   # smoke test
poetry run python scripts/seed.py --limit 50            # staging
poetry run python scripts/seed.py                       # production
```

---

## Architecture: Key Patterns

### Storage abstraction (`storage.py`)

All data access goes through `BaseStorage`. No layer above it knows which
backend is active.

- `InMemoryStorage` — local dev when `DATABASE_URL` is absent.
- `PostgresStorage` — production; auto-activates when `DATABASE_URL` is set.

Raw SQL only — **no** ORM, **no** migrations framework.

### Steam data access (`steam_source.py`)

All Steam API calls go through `SteamDataSource`. Only `DirectSteamSource` exists
today. SteamSpy is **not** used — Steam's own API supplies all required fields.

### LLM two-pass analysis (`analyzer.py`)

**Pass 1 — Haiku (cheap, parallel):** 50-review chunks → 7 signal types:
`design_praise`, `gameplay_friction`, `wishlist_items`, `dropout_moments`,
`competitor_refs`, `notable_quotes`, `batch_stats`.

**Pass 2 — Sonnet (synthesis):** All chunk signals → structured report JSON.
`sentiment_score` and `hidden_gem_score` are computed in Python **before**
calling Sonnet — never guessed by the LLM.

Each output section answers a **distinct** question — no duplication:

| Field | Question answered |
|---|---|
| `gameplay_friction` | What design is broken? |
| `churn_triggers` | **When** does a player quit because of it? |
| `dev_priorities` | The ranked fix (not a re-description) |
| `player_wishlist` | Net-new features only (not fixes to existing problems) |

### Lambda Web Adapter (FastAPI on Lambda)

FastAPI runs on Lambda via the Lambda Web Adapter binary copied by the
`Dockerfile`. Use Lambda Function URLs — **not** API Gateway.
Initialize DB connections and `httpx.AsyncClient` **outside** the handler
for connection reuse on warm invocations.

### Frontend (Next.js via OpenNext)

Deployed to Lambda. Calls FastAPI at `/api/*`.

CloudFront routing:

- `/api/*` → FastAPI Lambda
- `/*` → Next.js Lambda
- `/static/*` → S3

---

## API Endpoints

All endpoints live under `/api` (FastAPI):

| Endpoint | Access | Notes |
|---|---|---|
| `POST /api/preview` | Free | Returns `game_name`, `overall_sentiment`, `sentiment_score`, `one_liner`. 1 per IP. Returns `402 {"error": "free_limit_reached"}` on breach. |
| `POST /api/validate-key` | Premium | Validates Lemon Squeezy key → full premium JSON |
| `GET /api/status/{job_id}` | Internal | Step Functions job polling |
| `POST /api/analyze` | Internal/admin | Triggers Step Functions for an appid |
| `GET /health` | — | Storage backend + `pro_enabled` status |
| `POST /api/chat` | Pro (V2) | `PRO_ENABLED=true` only: NL → SQL → answer |

---

## Report JSON Schema

Output of `analyze_reviews()`:

```
game_name, appid, total_reviews_analyzed
overall_sentiment, sentiment_score      # computed in Python
sentiment_trend, sentiment_trend_note
one_liner                               # gamer-facing, max 25 words
audience_profile                        # ideal_player, casual_friendliness, archetypes, not_for
design_strengths[]
gameplay_friction[]
player_wishlist[]
churn_triggers[]
dev_priorities[]                        # {action, why_it_matters, frequency, effort}
competitive_context[]                   # {game, comparison_sentiment, note}
genre_context
hidden_gem_score                        # computed in Python before Sonnet call
```

---

## Environment Variables

```
DATABASE_URL            # PostgreSQL DSN. Required for PostgresStorage.
AWS_DEFAULT_REGION      # us-west-2
BEDROCK_REGION          # Bedrock region (defaults to AWS_DEFAULT_REGION)
LEMONSQUEEZY_API_KEY    # Payment validation
RESEND_API_KEY          # Email
PRO_ENABLED             # 'true' enables /api/chat (V2)
CF_DISTRIBUTION_ID      # CloudFront distribution ID
CF_KVS_ARN              # CloudFront KeyValueStore ARN (featured spots)
STEP_FUNCTIONS_ARN      # Analysis pipeline state machine ARN
HAIKU_MODEL             # Override: default claude-3-5-haiku-20241022
SONNET_MODEL            # Override: default claude-3-5-sonnet-20241022
```

---

## CDK Rules (Mandatory)

- No physical resource names — let CDK generate them.
  **Exception:** `pipeline_name="steampulse"` on the CodePipeline (singleton, humans
  need to find it in the Console).
- No env-var lookups inside constructs — pass as props or context.
- Secrets in AWS Secrets Manager, referenced by ARN.
- `data_stack` has `termination_protection=True`.
- Pipeline uses `CodePipelineSource.connection()` — **not** a PAT token.
- **Staging:** CloudFront URL only — no custom domain, no ACM cert, no Route53 records.
  `steampulse.io` is production only.
- **Production:** ACM cert (us-east-1) + CloudFront alias + Route53 A record.
  Gated by `ManualApprovalStep`.
- **Monitoring:** use `cdk-monitoring-constructs` — never write raw CloudWatch alarms
  or dashboards by hand.

---

## Python Code Style (Python 3.12+)

Ruff is the linter/formatter (`poetry run ruff check .` / `poetry run ruff format .`).

**Syntax:**
- Union types: `str | None` — never `Optional[str]`. Never import `Optional`.
- Type hints required on **all** parameters and return types, including `-> None`.
- Omit `from __future__ import annotations` — not needed in 3.12.
- Use `match` for multi-branch dispatch over long `if/elif` chains.
- f-strings everywhere — no `%` formatting, no `.format()`.
- `pathlib.Path` over `os.path`.
- `tomllib` (stdlib) for TOML, `json` (stdlib) for JSON.

**Async:**
- All I/O-bound functions must be `async def`.
- No blocking calls (`requests`, `time.sleep`) in async code.
- `asyncio.TaskGroup` instead of `asyncio.gather`.
- `httpx.AsyncClient` for all outbound HTTP — create once, reuse.
- Lambda: module-level init for DB connections and `AsyncClient`.

**Data structures:**
- `dataclasses.dataclass` or `pydantic.BaseModel` for domain objects.
- `TypedDict` only for JSON-serializable shapes without methods.
- Immutable defaults: `tuple` over `list`, `frozenset` over `set`.

**Error handling:**
- Raise specific exceptions — never bare `except:` without re-raise or logging.
- FastAPI: raise `HTTPException` with the right status code; never return error
  dicts with HTTP 200.
- `logging` (stdlib) only — no `print()`. Use structured fields:
  `logger.error("msg", extra={"appid": appid})`.

**General:**
- No mutable default arguments (`None` sentinel instead).
- `|` for dict merge (`a | b`).
- `enumerate()` over manual index counters. `zip(strict=True)` when lengths must match.
- Keep functions under 40 lines.

---

## Data Freshness Strategy

Four EventBridge rules in `lambda_stack.py` (all deployed **disabled**):

| Rule | Schedule | Scope |
|---|---|---|
| `nightly-top500` | Daily 06:00 UTC | Top 500 games — metadata + reviews + re-analysis |
| `weekly-mid-tier` | Sundays 08:00 UTC | review_count 500–5,000 |
| `monthly-long-tail` | 1st of month | review_count < 500, metadata only |
| `weekly-discovery` | Mondays 07:00 UTC | Full Steam app list — finds new games |

Enable them manually after the initial seed completes and the site is live.

**Delta-triggered re-analysis threshold (tiered):**

```python
def _reanalysis_threshold(total_reviews: int) -> int:
    if total_reviews < 200:      return 25
    elif total_reviews < 2_000:  return 150
    elif total_reviews < 20_000: return 500
    elif total_reviews < 200_000: return 2_000
    else:                        return 10_000
```

---

## Do Not Build

- No user accounts or login system.
- No database migrations framework (raw SQL in `storage.py`).
- No CSS frameworks (Tailwind or plain CSS in Next.js).
- No job queue inside FastAPI (analysis runs in Step Functions).
- No subscription management UI (Lemon Squeezy handles it).
- No Terraform (CDK only).
- No separate Railway deployment.
- No Jinja2 templates (frontend is Next.js).
- No SteamSpy integration (Steam's own API is sufficient).

---

## Common Pitfalls

- **Import paths:** Lambda functions import from `library_layer.*` (installed as a
  Lambda layer). Tests bootstrap `sys.path` in `tests/conftest.py` — check it when
  adding new source directories.
- **Async in tests:** `pyproject.toml` sets `asyncio_mode = "auto"`, so test functions
  can be `async def` without extra decorators.
- **No `requirements.txt`:** Poetry is the only dep manager. Never generate or commit
  a `requirements.txt`.
- **Ruff before committing:** Run `poetry run ruff check . && poetry run ruff format .`
  before every commit. CI will fail otherwise.
- **CDK physical names:** Do not add `resource_name=` / `bucket_name=` etc. to CDK
  constructs unless there is an explicit exception documented above.
- **DB in Lambda:** `DATABASE_URL` **must** be set; there is no `InMemoryStorage`
  fallback in Lambda. Missing it causes an immediate cold-start crash.
