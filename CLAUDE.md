# CLAUDE.md

This file is Claude Code's persistent memory for SteamPulse. Read it fully before touching any code.

## What This Project Is

**SteamPulse** — AI-powered Steam game intelligence platform at **steampulse.io**.

- **Public site**: AI-synthesized review reports for ALL Steam games with any reviews. SEO-driven, cross-linked, no ads.
- **Premium layer**: Developer-focused. Unlocks `dev_priorities`, `churn_triggers`, `player_wishlist` sections via Lemon Squeezy license keys.
- **Pro tier (V2)**: NL chat over full catalog. Feature-flagged behind `PRO_ENABLED=true`.

Full architecture decisions in `steampulse-design.org` at the repo root. Read it for anything not covered here.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Backend API | Python 3.12, FastAPI (JSON API only — no HTML rendering), uvicorn, httpx |
| Frontend | Next.js (React SSR/ISR) in `frontend/`, deployed via OpenNext to Lambda |
| LLM | `claude-3-5-haiku-20241022` (chunk pass), `claude-3-5-sonnet-20241022` (synthesis) |
| DB | PostgreSQL on RDS. `BaseStorage` abstraction — `PostgresStorage` via `DATABASE_URL`. Locally use Docker Postgres via `./scripts/dev/start-local.sh` |
| Hosting | AWS Lambda (container image) + CloudFront + Route 53. **No Railway. No Fargate.** |
| Infra | AWS CDK v2 (Python) in `infra/`. CDK Pipelines (self-mutating). |
| Payments | Lemon Squeezy (license key model, handles VAT) |
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
        app_crawler/    # Crawls Steam metadata → writes to DB → queues review crawl
        review_crawler/ # Fetches reviews → writes to DB → triggers Step Functions
        api/            # FastAPI app: /preview, /validate-key, /health, /chat
  frontend/             # Next.js app (React)
  infra/                # AWS CDK v2 (Python)
  scripts/
    dev/                # Local dev helpers (start-local.sh, invoke-*.sh, run-api.sh)
    seed.py             # Bootstrap top-N games into SQS
    aws-costs.sh        # AWS cost report
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
# Local dev — start DB, run API, invoke crawlers
./scripts/dev/start-local.sh          # start Postgres + init schema
./scripts/dev/run-api.sh              # API at http://localhost:8000
./scripts/dev/invoke-app-crawler.sh 440
./scripts/dev/invoke-review-crawler.sh 440

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

# Seed script
export APP_CRAWL_QUEUE_URL="https://sqs.us-west-2.amazonaws.com/..."
poetry run python scripts/seed.py --limit 50   # staging
poetry run python scripts/seed.py --dry-run --limit 5   # smoke test
poetry run python scripts/seed.py              # production (full crawl)
```

---

## Architecture: Key Patterns

### Storage abstraction (storage.py)

All data access goes through `BaseStorage`. Nothing in `api.py`, `analyzer.py`, etc. knows which backend is active.
- `InMemoryStorage`: local dev, no DATABASE_URL
- `PostgresStorage`: production, auto-activates when `DATABASE_URL` is set

### SteamDataSource abstraction (steam_source.py)

All Steam data access goes through `SteamDataSource`. Currently only `DirectSteamSource` (calls Steam API directly). SteamSpy is NOT used — Steam's own API provides all required fields (genres, categories, review counts, metadata).

### LLM Two-Pass Analysis (analyzer.py)

**Pass 1 (Haiku — cheap, parallel):** 50-review chunks → extract 7 signal types:
`design_praise`, `gameplay_friction`, `wishlist_items`, `dropout_moments`, `competitor_refs`, `notable_quotes`, `batch_stats`

**Pass 2 (Sonnet — synthesis):** All chunk signals → structured report JSON.
`sentiment_score` and `hidden_gem_score` are computed in Python BEFORE calling Sonnet — never LLM-guessed.

**Critical:** Each output section answers a DIFFERENT question. No duplication between sections:
- `gameplay_friction` = what design is broken
- `churn_triggers` = WHEN it causes a player to leave
- `dev_priorities` = the ranked FIX (not a re-description)
- `player_wishlist` = net-new features (not fixes to broken things)

### Lambda Web Adapter (FastAPI on Lambda)

FastAPI runs natively on Lambda via Lambda Web Adapter — zero code changes needed.
The Dockerfile copies the adapter binary. Use Lambda Function URLs, not API Gateway.
Initialize DB connections OUTSIDE the handler for connection reuse on warm invocations.

### Frontend (Next.js via OpenNext)

Next.js is deployed via OpenNext to Lambda. The frontend calls FastAPI at `/api/*`.
CloudFront routes: `/api/*` → FastAPI Lambda, `/*` → Next.js Lambda, `/static/*` → S3.

---

## API Endpoints (FastAPI — all under /api)

| Endpoint | Notes |
|---|---|
| `POST /api/preview` | Free: returns `game_name`, `overall_sentiment`, `sentiment_score`, `one_liner`. 1 per IP limit. |
| `POST /api/validate-key` | Validates Lemon Squeezy key → returns full premium JSON |
| `GET /api/status/{job_id}` | Step Functions job polling (lazy generation) |
| `POST /api/analyze` | Triggers Step Functions for appid (internal/admin) |
| `GET /health` | Storage backend + pro_enabled status |
| `POST /api/chat` | V2 only (`PRO_ENABLED=true`): NL → SQL → answer |

Rate limit on `/api/preview`: 1 free analysis per IP. Returns `402 {"error": "free_limit_reached"}` on breach.

---

## Report JSON Schema (from analyzer.py)

The output of `analyze_reviews()`:

```
game_name, appid, total_reviews_analyzed
overall_sentiment, sentiment_score      # score computed in Python
sentiment_trend, sentiment_trend_note
one_liner                               # gamer-facing, max 25 words
audience_profile                        # ideal_player, casual_friendliness, archetypes, not_for
design_strengths[]                      # what design decisions are working
gameplay_friction[]                     # in-game UX/design problems (no biz complaints here)
player_wishlist[]                       # net-new features only (not fixes)
churn_triggers[]                        # journey moments that cause dropout (with timing)
dev_priorities[]                        # {action, why_it_matters, frequency, effort} — ranked
competitive_context[]                   # {game, comparison_sentiment, note} — named only
genre_context                           # genre benchmark, no named competitors
hidden_gem_score                        # computed in Python before Sonnet call
```

---

## CDK Structure (infra/)

```
infra/
  app.py                  # CDK entry point
  pipeline_stack.py       # Self-mutating CDK Pipeline (CodeStar Connection to GitHub)
  application_stage.py
  stacks/
    common_stack.py       # Lambda layers (LibraryLayer)
    network_stack.py      # VPC
    sqs_stack.py          # SQS queues + DLQs
    lambda_stack.py       # Lambda functions (crawlers) + EventBridge schedules
    data_stack.py         # RDS + S3, termination_protection=True
    analysis_stack.py     # Step Functions state machine
    app_stack.py          # FastAPI Lambda + Function URL + CloudFront + Route53 + ACM
    frontend_stack.py     # Next.js Lambda (OpenNext) + CloudFront behaviour
    monitoring_stack.py   # CloudWatch via cdk-monitoring-constructs
```

CDK rules (mandatory):
- No physical resource names — let CDK generate (exception: `pipeline_name="steampulse"` on the CodePipeline — singleton, no conflict risk, humans need to find it in Console)
- No env var lookups inside constructs — pass as props or context
- Secrets in AWS Secrets Manager, referenced by ARN
- `data_stack` has `termination_protection=True`
- Pipeline uses `CodePipelineSource.connection()` — NOT a PAT token
- **Staging environment: CloudFront URL only — no custom domain, no ACM cert, no Route53 records. `steampulse.io` is production only.**
- **Production environment: ACM cert (us-east-1) + CloudFront alias + Route53 A record for `steampulse.io`. Gated by `ManualApprovalStep` in the pipeline.**
- **Monitoring: use `cdk-monitoring-constructs` (npm: `cdk-monitoring-constructs`) — never write raw CloudWatch alarms or dashboards by hand**

---

## Environment Variables

```
DATABASE_URL            # PostgreSQL. Required for PostgresStorage (no InMemoryStorage fallback in Lambda)
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
- FastAPI endpoints: raise `HTTPException` with appropriate status codes. Never return error dicts with 200.
- Log with `logging` (stdlib) — not `print()`. Use structured fields: `logger.error("msg", extra={"appid": appid})`.

**General:**
- No mutable default arguments (`def f(x=[])` → use `None` sentinel).
- Prefer `|` dict merge (`{**a, **b}` → `a | b`) in 3.9+.
- `enumerate()` over manual index counters. `zip(strict=True)` when lengths must match.
- Keep functions under 40 lines. Extract helpers rather than nesting.

---

## Data Freshness Strategy

Four EventBridge rules in `lambda_stack.py` keep data current. **All rules are deployed
with `enabled=False` — enable manually after the initial seed is complete and site is live.**

| Rule | Schedule | Scope |
|---|---|---|
| `nightly-top500` | Daily 6am UTC | Top 500 games — metadata + reviews + re-analysis |
| `weekly-mid-tier` | Sundays 8am UTC | review_count 500–5000 |
| `monthly-long-tail` | 1st of month | review_count < 500, metadata only |
| `weekly-discovery` | Mondays 7am UTC | Full Steam app list — finds new games not in DB |

**Delta-triggered re-analysis:** `app_crawler.py` only queues `review-crawl-queue`
(which triggers Step Functions) if new reviews since last crawl exceed a tiered absolute
threshold. Never use a flat percentage — large games have stable sentiment and need
far fewer re-analyses than small games.

```python
def _reanalysis_threshold(total_reviews: int) -> int:
    """New reviews needed since last analysis to trigger re-analysis."""
    if total_reviews < 200:
        return 25
    elif total_reviews < 2_000:
        return 150
    elif total_reviews < 20_000:
        return 500
    elif total_reviews < 200_000:
        return 2_000
    else:
        return 10_000
```

TF2 (800k reviews) needs 10k new reviews to re-trigger — maybe twice a year.
A small indie (200 reviews) needs just 25 — maybe monthly. Target: ~$50/month steady state.

**Staleness signal:** `last_analyzed` is returned in all API responses.
Frontend shows "Analysis from X days ago" and a "Refresh available" badge after 30 days.

---

## Do Not Build

- No user accounts or login system
- No database migrations framework (raw SQL in `storage.py`)
- No CSS frameworks (use Tailwind or plain CSS in Next.js)
- No job queue inside FastAPI (analysis is in Step Functions)
- No subscription management UI (Lemon Squeezy handles it)
- No Terraform (CDK only)
- No separate Railway deployment
- No Jinja2 templates (frontend is Next.js)
