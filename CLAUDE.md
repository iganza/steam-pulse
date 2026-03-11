# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**SteamPulse** — Steam game intelligence platform. Two tiers:
- **V1 (ship immediately):** Pay-per-analysis of Steam game reviews via credit packs (Lemon Squeezy license keys)
- **V2 (feature-flagged):** Natural language chat over the full Steam catalog (Pro subscription)

One codebase, one Railway deployment. Feature flags separate the tiers. Full spec in `steam_analyzer_prompt.md`.

## Tech Stack

- Python 3.10+, FastAPI + uvicorn, httpx (async HTTP)
- Anthropic SDK — `claude-haiku-3-5` (chunk summarization), `claude-sonnet-3-5` (synthesis + chat)
- Poetry for dependency management (`pyproject.toml` is source of truth)
- PostgreSQL via psycopg2-binary (V2 only, app auto-detects via `DATABASE_URL`)
- Jinja2 (HTML report template), Resend (email), Rich (CLI)
- Vanilla JS frontend (no frameworks, inline CSS)

## Common Commands

```bash
# Local development
cp .env.example .env  # fill in keys
poetry install
poetry run uvicorn steampulse.api:app --reload

# CLI
poetry run python steampulse/main.py --appid 440
poetry run python steampulse/main.py --appid 440 --max-reviews 200 --json
poetry run python steampulse/main.py --appid 440 --dry-run  # fetch only, no LLM

# V2 infrastructure
cd infra/
terraform init && terraform apply
```

## Architecture

### Key Design: storage.py

The central abstraction. All data access goes through `BaseStorage`. V1 uses `InMemoryStorage` (in-memory dicts, 24hr TTL, resets on restart). V2 auto-upgrades to `PostgresStorage` when `DATABASE_URL` is set. Nothing in `api.py`, `analyzer.py`, etc. knows which backend is active.

### LLM Two-Pass Analysis (analyzer.py)

1. **Pass 1 (Haiku, cheap):** Batch 50 reviews → extract complaints/praises/requests. Uses Anthropic prompt caching on system prompt.
2. **Pass 2 (Sonnet):** All chunk summaries → structured JSON with `top_praises`, `top_complaints`, `feature_requests`, `refund_risk_signals`, `dev_action_items`, `one_liner`, etc.

### V1/V2 Feature Flag

`PRO_ENABLED` env var gates V2 endpoints (`/chat`). The app is always V1-capable. V2 activates automatically when both `DATABASE_URL` and `PRO_ENABLED=true` are set.

### Frontend States (index.html — vanilla JS)

Single HTML file served by FastAPI. Transitions through: Input → Loading → Free Preview (blurred sections) → Full Report (post license key). License key saved to `localStorage` for reuse.

### Crawler (V2 — separate Lambda deployment)

`crawler/` is NOT part of the FastAPI app. It runs as AWS Lambda triggered by SQS, writes to the same RDS instance. Build the code but deploy separately via Terraform in `infra/`.

## API Endpoints

| Endpoint | Notes |
|---|---|
| `GET /` | Serves `templates/index.html` |
| `POST /preview` | Free tier: returns `game_name`, `overall_sentiment`, `sentiment_score`, `one_liner` only |
| `POST /validate-key` | Validates Lemon Squeezy key, consumes activation, returns full report + sends email |
| `GET /health` | Returns storage backend and `pro_enabled` status |
| `POST /chat` | V2 only (`PRO_ENABLED=true`): NL → SQL → answer |

`/preview` enforces 1 free analysis per IP via `rate_limiter.py`. On limit hit, returns `402 { "error": "free_limit_reached" }`.

## Dependency Groups

```toml
# pyproject.toml
[tool.poetry.group.crawler.dependencies]  # Lambda-only deps

# Dockerfile uses:
poetry install --without crawler

# Lambda layer uses:
poetry export -f requirements.txt --only crawler
```

## Do Not Build

- No user accounts/login
- No database migrations framework (raw SQL in `storage.py`)
- No React/Vue/Angular or CSS frameworks
- No job queue inside FastAPI (crawlers are separate Lambda)
- No subscription management UI (Lemon Squeezy handles it)
