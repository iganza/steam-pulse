# SteamPulse — Claude Code Prompt

Paste this entire prompt into Claude Code to build the project.

---

## Overview

Build **SteamPulse**: a Steam game intelligence platform with two tiers:

- **V1 (ship immediately):** Review analysis for any Steam game — your own or competitors. Pay-per-analysis via credit packs (Lemon Squeezy license keys).
- **V2 (feature-flagged, ships when catalog is indexed):** Natural language chat over the full Steam catalog. Pro subscription tier.

**One codebase. One deployment. Feature flags separate the tiers.**

The FastAPI app runs on Railway. AWS is used only for the V2 data infrastructure (RDS + Lambda crawlers). The app never needs to move.

---

## Tech Stack

- Python 3.10+
- FastAPI + uvicorn (HTTP service + serves frontend)
- httpx (async HTTP)
- anthropic SDK — claude-haiku-3-5 (chunking), claude-sonnet-3-5 (synthesis + chat)
- psycopg2-binary (PostgreSQL, V2 — gracefully absent in V1)
- jinja2 (HTML report template for CLI)
- resend (transactional email)
- python-dotenv
- rich (CLI output)

**Dependency management: use Poetry.**
- `pyproject.toml` is the single source of truth for all deps
- Use optional dependency groups: `[tool.poetry.group.crawler.dependencies]` for crawler-only deps
- Dockerfile uses `poetry install --without crawler` for the app image
- Lambda layer uses `poetry export -f requirements.txt --only crawler`

---

## File Structure

```
steampulse/
  api.py              # FastAPI app — all endpoints, serves frontend
  main.py             # CLI entrypoint (calls core functions directly)
  fetcher.py          # Steam API: reviews + app metadata
  analyzer.py         # LLM two-pass review analysis
  storage.py          # Abstraction: InMemoryStorage (V1) or PostgresStorage (V2)
  rate_limiter.py     # IP-based free tier (1 free analysis per IP)
  chat.py             # V2: natural language → SQL → answer (feature-flagged)
  reporter.py         # Jinja2 HTML report (CLI only)
  templates/
    index.html        # Single-page frontend (vanilla JS, served by FastAPI)
    report.html.j2    # CLI report template
  crawler/
    handler.py        # AWS Lambda handler (V2, separate deployment)
    app_crawler.py    # Crawls Steam appdetails + SteamSpy tags
    review_crawler.py # Crawls review counts for all games
    db.py             # Crawler → PostgreSQL writes
  infra/
    main.tf           # Terraform: RDS + Lambda + SQS (V2)
    variables.tf
    outputs.tf
  .env.example        # All env vars documented
  pyproject.toml      # Poetry — all deps including optional crawler group
  poetry.lock
  Dockerfile          # FROM python:3.10-slim, uses poetry install --without crawler
  README.md
```

---

## Environment Variables (.env.example)

```bash
# V1 — required from day 1
ANTHROPIC_API_KEY=
LEMON_SQUEEZY_API_KEY=              # For validating license keys via LS API
LEMON_SQUEEZY_STORE_ID=             # Your LS store ID
LEMON_SQUEEZY_SINGLE_CHECKOUT_URL=  # $7 single analysis product
LEMON_SQUEEZY_PACK5_CHECKOUT_URL=   # $15 for 5 analyses product
LEMON_SQUEEZY_PRO_CHECKOUT_URL=     # $49/mo Pro subscription (V2)
RESEND_API_KEY=
RESEND_FROM_EMAIL=reports@steampulse.gg

# V2 — add when RDS is provisioned (app auto-detects and upgrades storage backend)
DATABASE_URL=postgresql://user:pass@host:5432/steampulse
PRO_ENABLED=false                   # Flip to true when catalog is indexed

# Crawler (V2, Lambda environment only)
STEAMSPY_API_KEY=                   # Optional — higher rate limits
```

---

## storage.py — The Key Abstraction

This is the most important design decision. All data access goes through this module.
V1 uses in-memory dicts. V2 swaps in PostgreSQL. Nothing else changes.

```python
import os
from abc import ABC, abstractmethod

class BaseStorage(ABC):
    @abstractmethod
    def get_analysis(self, appid: int): ...
    @abstractmethod
    def store_analysis(self, appid: int, result: dict): ...
    # V2 methods (no-op in V1)
    def get_game(self, appid: int): return None
    def store_game(self, appid: int, data: dict): pass
    def query_catalog(self, sql: str, params: tuple = ()): return []

class InMemoryStorage(BaseStorage):
    # Simple dict with 24hr TTL. Resets on restart — acceptable for V1.
    ...

class PostgresStorage(BaseStorage):
    # Full implementation using psycopg2.
    # Schema: games, game_tags, game_genres, game_categories, review_summaries
    ...

def get_storage() -> BaseStorage:
    """Auto-select backend based on DATABASE_URL env var."""
    if os.getenv("DATABASE_URL"):
        return PostgresStorage(os.getenv("DATABASE_URL"))
    return InMemoryStorage()

storage = get_storage()
```

**PostgreSQL schema (create in PostgresStorage.__init__ if tables don't exist):**

```sql
CREATE TABLE IF NOT EXISTS games (
    appid INTEGER PRIMARY KEY,
    name TEXT, type TEXT, release_date DATE,
    price_usd NUMERIC, is_free BOOLEAN,
    metacritic_score INTEGER,
    total_positive INTEGER, total_negative INTEGER,
    review_score_desc TEXT,
    short_description TEXT,
    developers TEXT[], publishers TEXT[],
    platforms JSONB,
    last_crawled TIMESTAMP
);

CREATE TABLE IF NOT EXISTS game_tags (
    appid INTEGER, tag TEXT,
    PRIMARY KEY (appid, tag)
);

CREATE TABLE IF NOT EXISTS game_genres (
    appid INTEGER, genre TEXT,
    PRIMARY KEY (appid, genre)
);

CREATE TABLE IF NOT EXISTS game_categories (
    appid INTEGER, category TEXT,
    PRIMARY KEY (appid, category)
);

CREATE TABLE IF NOT EXISTS review_summaries (
    appid INTEGER PRIMARY KEY,
    summary JSONB,
    last_analyzed TIMESTAMP
);
```

---

## Steam APIs

### Review fetching (V1 core)
```
GET https://store.steampowered.com/appreviews/{appid}
  ?json=1&filter=recent&language=english&num_per_page=100&cursor=*
```
Fetch up to 500 reviews (5 pages). 1 second delay between pages.
Store: review_text, voted_up (bool), playtime_at_review (minutes), timestamp_created.

### App metadata (V1: game name + cover image only; V2 crawler: full data)
```
GET https://store.steampowered.com/api/appdetails?appids={appid}
```

### Review counts only (fast, V2 crawler)
```
GET https://store.steampowered.com/appreviews/{appid}?json=1&num_per_page=0
```
Returns total_positive, total_negative, review_score_desc without fetching review text.

### SteamSpy (tags + owner estimates, V2 crawler)
```
GET https://steamspy.com/api.php?request=appdetails&appid={appid}
```
Rate limit: 1 req/sec (free), ~4/sec with API key.

---

## LLM Analysis (analyzer.py)

Two-pass approach:

**Pass 1 — Chunk summarization (Haiku, cheap):**
- Batch reviews into groups of 50
- Each batch: extract complaints, praises, feature requests
- Use Anthropic prompt caching: add `"cache_control": {"type": "ephemeral"}` to system prompt

**Pass 2 — Final synthesis (Sonnet):**
- Feed all chunk summaries into one prompt
- Return structured JSON:

```json
{
  "game_name": "string",
  "total_reviews_analyzed": 347,
  "overall_sentiment": "Mixed",
  "sentiment_score": 0.52,
  "top_praises": ["art style", "core loop", "music"],
  "top_complaints": ["difficulty spike at level 4", "no save anywhere", "PC performance"],
  "feature_requests": ["difficulty settings", "controller remapping", "New Game+"],
  "refund_risk_signals": ["61% of refunders cite difficulty within first 30min"],
  "competitive_mentions": ["Hades", "Dead Cells"],
  "dev_action_items": [
    "Add difficulty option — in 23% of negative reviews",
    "Add manual save — in 18% of negative reviews",
    "PC performance pass before next update"
  ],
  "one_liner": "Players love the art but are bouncing at hour 3 due to a difficulty spike with no save option."
}
```

**System prompt for synthesis (use exactly):**
> "You are a game analytics expert helping indie game developers understand their Steam reviews. Your analysis must be specific, actionable, and honest — not generic. Developers need to know what to actually fix, not vague summaries. Focus on patterns that appear in multiple reviews, not outliers."

---

## API Endpoints (api.py)

### V1 endpoints (always active)

**GET /**
Serves `templates/index.html`

**POST /preview**
Body: `{ "appid": 440 }`
1. Check IP rate limit — if exhausted, return `402 { "error": "free_limit_reached", "checkout_url": "..." }`
2. Fetch reviews + app metadata
3. Run full LLM analysis, store in storage
4. Return FREE tier only: `{ "game_name", "overall_sentiment", "sentiment_score", "one_liner", "appid" }`

**POST /validate-key**
Body: `{ "license_key": "XXXX-XXXX-XXXX-XXXX", "appid": 440 }`
1. Call Lemon Squeezy License API: `POST https://api.lemonsqueezy.com/v1/licenses/validate` with `{ license_key, instance_id: appid }`
2. If valid and activations_remaining > 0: call `activate` endpoint to consume one activation
3. Run full analysis (or retrieve from storage if already cached), return full report JSON + fire-and-forget email via Resend
4. If invalid or exhausted: return 403 `{ "error": "invalid_key" }` or 402 `{ "error": "no_credits" }`

**GET /health**
Returns `{ "status": "ok", "storage": "memory|postgres", "pro_enabled": false }`

### V2 endpoints (only active when PRO_ENABLED=true)

**POST /chat**
Body: `{ "message": "how many idle games released in 2024 with 100+ positive reviews?", "session_id": "abc" }`
1. Check valid Pro subscription (validate against Lemon Squeezy order, simple for now)
2. Call chat.py to generate + execute SQL
3. Return `{ "answer": "47 games matched your query.", "sql": "SELECT ...", "rows": [...] }`

---

## Frontend (templates/index.html)

Single HTML file, vanilla JS only, inline CSS. Dark game-dev aesthetic.

### Layout states (JS toggles between these)

**State 1 — Input**
- Logo: "SteamPulse"
- Tagline: "Find the gaps in your genre. Understand what players actually want — before you build."
- Input: Steam game URL or App ID
- Button: "Analyze Free"
- Note: "No account needed. First analysis free."

**State 2 — Loading**
- Animated spinner
- Status text cycles: "Fetching reviews..." → "Analyzing with AI..." → "Almost done..."

**State 3 — Free Preview**
- Game header: cover image (from Steam CDN: `https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg`) + name + sentiment badge
- One-liner summary (clearly visible)
- Blurred/locked sections: Top Complaints, Feature Requests, Refund Risk, Action Items
- Two CTA buttons: "Buy 1 analysis — $7" and "5-pack — $15 (best value)" — both link to respective Lemon Squeezy checkout URLs
- Note: "Instant access. Paste your license key below to unlock."
- License key input field + "Unlock" button (calls `/validate-key`)

**State 4 — Full Report (post-key-entry)**
- All sections rendered inline
- "⬇ Download Report" button — generates Blob from page HTML, triggers download as `{game_name}_steampulse.html`
- Note: "A copy has been sent to your email. Remaining credits on your key: N"

**State 5 — Pro Chat (V2, hidden until PRO_ENABLED)**
- Chat input + message history
- Each response shows the answer + optionally the SQL that was run
- "Upgrade to Pro — $49/mo" CTA when not subscribed
### JS behaviour
- On page load: check localStorage for saved license key — if present, show key input pre-filled
- Save license key to localStorage after successful unlock so user doesn't re-enter it for subsequent analyses
- Handle 402 response: show "No credits remaining on this key. Buy more below." with checkout links
- Handle 403 response: show "Invalid license key. Check your purchase email."
- All errors shown inline, no page reloads

---

## rate_limiter.py

```python
# In-memory dict: { "1.2.3.4": { "used": True, "appid": 440 } }
# 1 free full analysis per IP, ever (resets on server restart — fine for POC)
# Return { "allowed": bool, "checkout_url": str }
```

---

## chat.py (V2 — build but only called when PRO_ENABLED=true)

```python
async def answer_query(message: str, storage: BaseStorage) -> dict:
    """
    1. Send message + DB schema to Sonnet with instruction to generate SQL
    2. Parse SQL from response
    3. Execute via storage.query_catalog(sql)
    4. Send results back to Sonnet for natural language formatting
    5. Return { answer, sql, rows }
    """
```

System prompt for SQL generation (include full schema so LLM knows the tables):
> "You are a Steam game market analyst. You have access to a PostgreSQL database of Steam games.
> Generate a single valid SQL SELECT query to answer the user's question.
> Schema: [include full schema here]
> Rules: SELECT only, no INSERT/UPDATE/DELETE, LIMIT 100 max, return only the SQL."

---

## CLI (main.py)

```bash
python main.py --appid 440                    # analyze, save HTML report
python main.py --appid 440 --max-reviews 200
python main.py --appid 440 --output my.html
python main.py --appid 440 --dry-run          # fetch only, no LLM, save cache
python main.py --appid 440 --json             # print raw JSON
```

---

## crawler/ (V2 — build the code, Lambda deployment is separate)

**handler.py** — Lambda entry point, triggered by SQS
**app_crawler.py** — fetches Steam appdetails + SteamSpy tags, writes to PostgreSQL
**review_crawler.py** — fetches review counts only (not full text), writes to games table
**db.py** — PostgreSQL connection + upsert helpers for crawler

The crawler is a separate deployment (Lambda + SQS via Terraform in infra/).
It is NOT part of the FastAPI app — it runs independently and writes to the same RDS instance.

---

## infra/ (V2 Terraform — scaffold the files, leave values as variables)

Resources to define:
- `aws_db_instance` — RDS PostgreSQL t3.micro, single-AZ (cheap)
- `aws_sqs_queue` — steampulse-crawler-queue
- `aws_lambda_function` — steampulse-crawler, triggered by SQS
- `aws_iam_role` — Lambda execution role with RDS + SQS access
- `aws_cloudwatch_event_rule` — daily schedule to seed queue with app IDs

---

## Error Handling

- Invalid appid → 404 with friendly message in frontend
- Game has no English reviews → 422 "No English reviews found for this game"
- Steam API down → 503 "Steam API unavailable, try again shortly"
- Analysis cache hit → return cached result immediately (skip LLM cost)
- All errors display inline in frontend, no page reload

---

## Deployment Notes (include in README)

**V1 — Railway:**
```bash
# Set env vars in Railway dashboard:
# ANTHROPIC_API_KEY, LEMON_SQUEEZY_*, RESEND_API_KEY
git push origin main  # Railway auto-deploys
```

**V2 — Add AWS infrastructure:**
```bash
cd infra/
terraform init && terraform apply
# Copy DATABASE_URL output → add to Railway env vars
# PRO_ENABLED=true once catalog is indexed
```

**Local development:**
```bash
cp .env.example .env  # fill in keys
poetry install
poetry run uvicorn api:app --reload
```

---

## Do Not Build

- No user accounts or login system
- No database migrations framework (raw SQL in storage.py is fine for POC)
- No React/Vue/Angular — vanilla JS only
- No CSS framework — inline styles only
- No job queue inside the FastAPI app (crawlers are separate Lambda)
- No subscription management UI (Lemon Squeezy handles that)

---

## V2 Project Structure (scaffold empty, do not implement yet)

When the V2 crawler work begins, the project will adopt this structure.
Create the directories and empty `__init__.py` files now so the layout is ready.

```
steampulse/
  infra/                        # AWS CDK stack (Python)
    app.py                      # CDK app entry point
    steampulse_stack.py         # RDS + Lambda + SQS + IAM resources
    requirements.txt            # CDK deps (separate from Poetry — CDK needs its own)
  src/
    library_layer/              # Shared code used by both Lambda and the FastAPI app
      __init__.py
      models.py                 # Shared data models (Game, ReviewSummary, etc.)
      db.py                     # PostgreSQL connection + shared queries
    lambda_layer/               # Lambda-only code
      __init__.py
      crawler/
        handler.py              # Lambda entry point (SQS trigger)
        app_crawler.py          # Steam appdetails + SteamSpy
        review_crawler.py       # Review counts
```

Note: `src/library_layer` will eventually replace the inline `storage.py` PostgreSQL
implementation, sharing the DB models and queries between the FastAPI app and the crawlers.
For V1, `storage.py` in the root is fine — the refactor happens when V2 ships.
