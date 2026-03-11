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
| DB | PostgreSQL on RDS. `BaseStorage` abstraction — `InMemoryStorage` locally, `PostgresStorage` when `DATABASE_URL` is set |
| Hosting | AWS Lambda (container image) + CloudFront + Route 53. **No Railway. No Fargate.** |
| Infra | AWS CDK v2 (Python) in `infra/`. CDK Pipelines (self-mutating). |
| Payments | Lemon Squeezy (license key model, handles VAT) |
| Email | Resend |
| Deps | Poetry — `pyproject.toml` is source of truth. No `requirements.txt`. |

---

## Monorepo Structure

```
repo-root/
  steampulse/       # Python FastAPI — API only, no HTML
  frontend/         # Next.js app (React)
  crawler/          # Python Lambda crawlers (separate Poetry group)
  infra/            # AWS CDK v2 (Python)
  pyproject.toml    # Python deps: main + infra + crawler groups
  cdk.json          # "app": "poetry run python infra/app.py"
  CLAUDE.md
  steampulse-design.org
  steamwebapi-openapi-doc.json  # Reference only — not used in production
```

---

## Common Commands

```bash
# Backend local dev
cp .env.example .env
poetry install
poetry run uvicorn steampulse.api:app --reload

# CDK (infra)
poetry install --with infra
poetry run cdk synth
poetry run cdk deploy  # only needed once to bootstrap pipeline

# Frontend local dev
cd frontend && npm install && npm run dev

# CLI analysis (for testing)
poetry run python steampulse/main.py --appid 440
poetry run python steampulse/main.py --appid 440 --max-reviews 200 --json
poetry run python steampulse/main.py --appid 440 --dry-run  # no LLM
```

---

## Architecture: Key Patterns

### Storage abstraction (storage.py)

All data access goes through `BaseStorage`. Nothing in `api.py`, `analyzer.py`, etc. knows which backend is active.
- `InMemoryStorage`: local dev, no DATABASE_URL
- `PostgresStorage`: production, auto-activates when `DATABASE_URL` is set

### SteamDataSource abstraction (steam_source.py)

All Steam data access goes through `SteamDataSource`. Currently only `DirectSteamSource` (calls Steam + SteamSpy directly).
Add new implementations here if alternative data sources are needed later.

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
    data_stack.py         # RDS + S3, termination_protection=True
    network_stack.py      # VPC
    crawler_stack.py      # SQS + Lambda crawlers
    analysis_stack.py     # Step Functions state machine
    app_stack.py          # FastAPI Lambda + Function URL + CloudFront + Route53 + ACM
    frontend_stack.py     # Next.js Lambda (OpenNext) + CloudFront behaviour
    monitoring_stack.py
```

CDK rules (mandatory):
- No physical resource names — let CDK generate
- No env var lookups inside constructs — pass as props or context
- Secrets in AWS Secrets Manager, referenced by ARN
- `data_stack` has `termination_protection=True`
- Pipeline uses `CodePipelineSource.connection()` — NOT a PAT token

---

## Environment Variables

```
ANTHROPIC_API_KEY       # Required
DATABASE_URL            # PostgreSQL. Absence = InMemoryStorage
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

## Do Not Build

- No user accounts or login system
- No database migrations framework (raw SQL in `storage.py`)
- No CSS frameworks (use Tailwind or plain CSS in Next.js)
- No job queue inside FastAPI (analysis is in Step Functions)
- No subscription management UI (Lemon Squeezy handles it)
- No Terraform (CDK only)
- No separate Railway deployment
- No Jinja2 templates (frontend is Next.js)
