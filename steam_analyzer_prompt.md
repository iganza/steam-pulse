# SteamPulse — Full Build Specification

> **Before starting any work:** Read `CLAUDE.md` and `steampulse-design.org` in full.
> They are the authoritative source for all architecture decisions.
> The LLM prompts in `steampulse/analyzer.py` are correct — do not modify them.

---

## What This Document Is

A phased build specification for SteamPulse at **steampulse.io** — an AI-powered Steam game
intelligence platform. The repo already has a partial V1 implementation. This spec describes
the full production system.

Work through phases in order. Complete and verify each phase before starting the next.
Never attempt to build multiple phases in a single session.

---

## What Already Exists (Do Not Rewrite)

- `steampulse/analyzer.py` — two-pass LLM pipeline. **Correct. Do not touch.**
- `steampulse/storage.py` — BaseStorage + InMemoryStorage. Extend, don't replace.
- `steampulse/rate_limiter.py` — IP-based rate limiting.
- `steampulse/main.py` — CLI entry point for local testing.
- `pyproject.toml` — Poetry config. Needs updating (see Phase 0).
- `Dockerfile` — needs updating (see Phase 0).

---

## Phase 0: Foundation Cleanup

**Goal:** Make the repo production-ready before building anything new.

### 0.1 — Update pyproject.toml

```toml
[tool.poetry]
name = "steampulse"
version = "0.1.0"
python = "^3.12"

[tool.poetry.dependencies]
python = "^3.12"
fastapi = ">=0.115.0"
uvicorn = {extras = ["standard"], version = ">=0.30.0"}
httpx = ">=0.27.0"
anthropic = ">=0.40.0"
psycopg2-binary = ">=2.9.9"
resend = ">=2.0.0"
python-dotenv = ">=1.0.0"

[tool.poetry.group.infra.dependencies]
aws-cdk-lib = ">=2.180.0"
constructs = ">=10.0.0"

[tool.poetry.group.crawler.dependencies]
boto3 = ">=1.34.0"

[tool.poetry.group.dev.dependencies]
pytest = ">=8.0.0"
pytest-asyncio = ">=0.23.0"
```

### 0.2 — Update Dockerfile

```dockerfile
FROM public.ecr.aws/awsguru/aws-lambda-adapter:0.8.4 AS lambda-adapter
FROM public.ecr.aws/lambda/python:3.12

COPY --from=lambda-adapter /lambda-adapter /opt/extensions/lambda-adapter
ENV PORT=8080

WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN pip install poetry && \
    poetry config virtualenvs.create false && \
    poetry install --without crawler,infra,dev --no-root

COPY steampulse/ ./steampulse/
CMD ["uvicorn", "steampulse.api:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 0.3 — Create .env.example

```
ANTHROPIC_API_KEY=
DATABASE_URL=postgresql://user:pass@localhost:5432/steampulse
LEMONSQUEEZY_API_KEY=
RESEND_API_KEY=
CF_DISTRIBUTION_ID=
CF_KVS_ARN=
STEP_FUNCTIONS_ARN=
PRO_ENABLED=false
HAIKU_MODEL=claude-3-5-haiku-20241022
SONNET_MODEL=claude-3-5-sonnet-20241022
```

### 0.4 — Create cdk.json at repo root

```json
{
  "app": "poetry run python infra/app.py",
  "context": {
    "@aws-cdk/aws-lambda:recognizeLayerVersion": true,
    "@aws-cdk/core:stackRelativeExports": "both",
    "@aws-cdk/aws-ec2:restrictDefaultSecurityGroup": true
  }
}
```

### 0.5 — Verify

```bash
poetry install
poetry run pytest
poetry run python steampulse/main.py --appid 440 --dry-run
```

---

## Phase 1: FastAPI API Layer

**Goal:** Update `api.py` to serve the new report schema. All endpoints are JSON only — no HTML.

### 1.1 — Create steampulse/steam_source.py

```python
from abc import ABC, abstractmethod

class SteamDataSource(ABC):
    @abstractmethod
    async def get_app_list(self) -> list[dict]:
        """Returns [{appid, name}] for all Steam apps."""

    @abstractmethod
    async def get_app_details(self, appid: int) -> dict:
        """Returns game metadata from Steam Store API."""

    @abstractmethod
    async def get_reviews(self, appid: int, max_reviews: int = 500) -> list[dict]:
        """Returns reviews with voted_up, review_text, playtime_at_review."""

    @abstractmethod
    async def get_steamspy_data(self, appid: int) -> dict:
        """Returns SteamSpy data: tags, owner estimates."""


class DirectSteamSource(SteamDataSource):
    """Calls Steam Store API and SteamSpy directly using httpx.

    URLs:
    - App list:    GET https://api.steampowered.com/ISteamApps/GetAppList/v2/
    - App details: GET https://store.steampowered.com/api/appdetails?appids={appid}
    - Reviews:     GET https://store.steampowered.com/appreviews/{appid}?json=1&filter=recent&num_per_page=100
                   Paginate using cursor param until max_reviews reached
    - SteamSpy:    GET https://steamspy.com/api.php?request=appdetails&appid={appid}

    Add jitter (random 0.5-2s sleep) between requests.
    Retry up to 3 times with exponential backoff on 429/503.
    """
```

### 1.2 — Rewrite steampulse/api.py

Keep `BaseStorage` and `rate_limiter` patterns. Update for new schema and endpoints.
Initialize storage at module level (outside handlers) for Lambda connection reuse.

**Endpoints:**

```
POST /api/preview
  Body: {appid: int}
  - Check storage for existing report. If found, return preview fields.
  - If not found, trigger analysis via Step Functions, return 202 with job_id.
  - Rate limit: 1 free per IP. Returns 402 on limit hit.
  - Free fields only: game_name, overall_sentiment, sentiment_score, one_liner, audience_profile

POST /api/validate-key
  Body: {key: str, appid: int}
  - Validate Lemon Squeezy license key (POST https://api.lemonsqueezy.com/v1/licenses/validate)
  - Consume one activation if valid
  - Return full report JSON
  - Send confirmation email via Resend

GET /api/status/{job_id}
  - Check Step Functions execution status via boto3
  - If complete, return full report from storage
  - Returns: {status: "running"|"complete"|"failed", report?: FullReport}

POST /api/analyze  (X-Admin-Key header required)
  Body: {appid: int, force: bool = false}
  - Trigger Step Functions execution
  - Returns: {job_id: str}

GET /health
  Returns: {storage: "memory"|"postgres", pro_enabled: bool, version: str}

POST /api/chat  (PRO_ENABLED=true only)
  Existing chat.py logic, updated for new schema field names.
```

**Step Functions trigger pattern:**
```python
async def _trigger_analysis(appid: int) -> str:
    # If STEP_FUNCTIONS_ARN set: use boto3 sfn client
    # Else: run analyze_reviews() inline (local dev fallback)
    # Returns execution ARN as job_id
```

### 1.3 — Update steampulse/storage.py

Add to BaseStorage and implement in both backends:
```python
async def get_report(self, appid: int) -> dict | None
async def upsert_report(self, appid: int, report: dict) -> None
async def get_game(self, appid: int) -> dict | None
async def upsert_game(self, appid: int, data: dict) -> None
async def get_analysis_job(self, job_id: str) -> dict | None
async def set_analysis_job(self, job_id: str, status: str, appid: int) -> None
```

PostgresStorage creates tables with `CREATE TABLE IF NOT EXISTS` on first connection.

Full schema (implement all tables):
```sql
CREATE TABLE games (
  appid INTEGER PRIMARY KEY, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL,
  developer TEXT, publisher TEXT, release_date DATE, price_usd NUMERIC(8,2),
  review_count INTEGER, positive_pct INTEGER, steamspy_owners TEXT,
  header_image TEXT, short_desc TEXT, crawled_at TIMESTAMPTZ,
  data_source TEXT DEFAULT 'steam_direct'
);
CREATE TABLE tags (id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, slug TEXT UNIQUE NOT NULL);
CREATE TABLE game_tags (appid INTEGER REFERENCES games(appid), tag_id INTEGER REFERENCES tags(id), votes INTEGER DEFAULT 0, PRIMARY KEY (appid, tag_id));
CREATE TABLE genres (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, slug TEXT UNIQUE NOT NULL);
CREATE TABLE game_genres (appid INTEGER REFERENCES games(appid), genre_id INTEGER REFERENCES genres(id), PRIMARY KEY (appid, genre_id));
CREATE TABLE reviews (id BIGSERIAL PRIMARY KEY, appid INTEGER REFERENCES games(appid), steam_review_id TEXT UNIQUE, author_steamid TEXT, voted_up BOOLEAN, playtime_hours INTEGER, body TEXT, posted_at TIMESTAMPTZ, crawled_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE reports (appid INTEGER PRIMARY KEY REFERENCES games(appid), report_json JSONB NOT NULL, reviews_analyzed INTEGER, analysis_version TEXT DEFAULT '1.0', is_public BOOLEAN DEFAULT TRUE, seo_title TEXT, seo_description TEXT, featured_at TIMESTAMPTZ, last_analyzed TIMESTAMPTZ DEFAULT NOW(), created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE game_relations (appid_a INTEGER REFERENCES games(appid), appid_b INTEGER REFERENCES games(appid), relation TEXT DEFAULT 'competitive_mention', PRIMARY KEY (appid_a, appid_b));
CREATE TABLE index_insights (id SERIAL PRIMARY KEY, type TEXT NOT NULL, slug TEXT NOT NULL, insight_json JSONB, computed_at TIMESTAMPTZ DEFAULT NOW(), UNIQUE(type, slug));
CREATE TABLE rate_limits (ip_hash TEXT PRIMARY KEY, count INTEGER DEFAULT 1, window_start TIMESTAMPTZ DEFAULT NOW());
```

### Verify Phase 1

```bash
poetry run uvicorn steampulse.api:app --reload
curl -X POST http://localhost:8000/api/preview -H "Content-Type: application/json" -d '{"appid": 440}'
curl http://localhost:8000/health
```

---

## Phase 2: CDK Infrastructure

**Goal:** Full AWS infrastructure as CDK v2 Python. Run `poetry run cdk synth` after each stack.

### infra/app.py

```python
import aws_cdk as cdk
from pipeline_stack import PipelineStack

app = cdk.App()
PipelineStack(app, "SteamPulsePipeline",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region"),
    )
)
app.synth()
```

### infra/pipeline_stack.py

Self-mutating pipeline via CodeStar Connections to GitHub.

```python
# CodePipelineSource.connection(repo, "main", connection_arn=connection_arn)
# Two stages:
#   - Staging: auto on every push to main
#   - Production: ManualApprovalStep gate
# Synth command: "pip install poetry && poetry install --with infra && poetry run cdk synth"
```

### infra/stacks/data_stack.py

RDS + S3. `termination_protection=True` always on this stack.
- RDS PostgreSQL t3.micro, Secret in Secrets Manager, no physical names
- S3 bucket for static assets (versioned, private, OAC for CloudFront)

### infra/stacks/app_stack.py

FastAPI Lambda + CloudFront + Route53 + ACM.
- Lambda: container image from ECR, 512MB, 30s timeout, Lambda Function URL (not API Gateway)
- CloudFront: two origins — Lambda Function URL for `/*`, S3 for `/static/*`
- Cache policy HTML: `max-age=86400, stale-while-revalidate=86400`
- Cache policy static: `max-age=31536000` (immutable)
- ACM cert in us-east-1 (required for CloudFront)
- Route53 A record: `steampulse.io` → CloudFront distribution
- CloudFront KeyValueStore for featured spots

### infra/stacks/analysis_stack.py

Step Functions Express Workflow:
```
StartAnalysis ({appid, game_name})
  → FetchReviews (Lambda)
  → PrepareChunks (Lambda: split into 50-review batches)
  → Map (MaxConcurrency=5)
      → AnalyzeChunk (Lambda: Haiku per chunk)
  → SynthesizeReport (Lambda: Sonnet synthesis)
  → StoreReport (Lambda: upsert to RDS)
  → InvalidateCache (Lambda: CloudFront invalidation /games/{appid}/*)
```

### infra/stacks/crawler_stack.py

- SQS: `app-crawl-queue` (batch 10, visibility 5min)
- SQS: `review-crawl-queue` (batch 1, visibility 10min)
- Lambda: app-crawler (SQS trigger)
- Lambda: review-crawler (SQS trigger)
- EventBridge: nightly re-crawl of top 500

### infra/stacks/frontend_stack.py

OpenNext deploys Next.js to Lambda. Add `/*` behaviour to existing CloudFront distribution
(lower priority than `/api/*` → FastAPI).
Use `@open-next/aws-cdk-adapter` — docs: https://opennext.js.org/aws/getting_started

### Verify Phase 2

```bash
poetry install --with infra
poetry run cdk synth
# No errors, no hardcoded account IDs, no plaintext secrets
```

---

## Phase 3: Crawler System

### crawler/app_crawler.py

Lambda handler triggered by `app-crawl-queue`. Each message = one appid.
Fetches metadata + SteamSpy. Upserts to `games`, `tags`, `game_tags`, `genres`, `game_genres`.

### crawler/review_crawler.py

Lambda handler triggered by `review-crawl-queue`. Each message = one appid.
Fetches up to 2000 most recent reviews. Upserts to `reviews`.
After upsert, starts Step Functions execution for analysis.

### scripts/seed.py

Bootstrap script for top 500 games. Supports `--dry-run` and `--limit N` flags.
1. Fetch full app list from Steam
2. Push all appids to `app-crawl-queue`
3. After metadata crawl, push top 500 (by review_count desc) to `review-crawl-queue`

### Verify Phase 3

```bash
poetry run python scripts/seed.py --dry-run --limit 5
```

---

## Phase 4: Next.js Frontend

### Initialize

```bash
cd frontend
npx create-next-app@latest . --typescript --tailwind --app --no-src-dir --import-alias "@/*"
npx shadcn@latest init
npx shadcn@latest add card badge button
```

### frontend/lib/types.ts

TypeScript types for all report fields. Must exactly match `steampulse/analyzer.py` schema:
`GameReport`, `AudienceProfile`, `DevPriority`, `CompetitorRef`, `PreviewResponse`, `StatusResponse`

### frontend/lib/api.ts

```typescript
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? '/api'
export async function getPreview(appid: number): Promise<PreviewResponse>
export async function validateKey(key: string, appid: number): Promise<GameReport>
export async function pollStatus(jobId: string): Promise<StatusResponse>
```

### Game report page: frontend/app/games/[appid]/[slug]/page.tsx

SSR. generateMetadata returns title/description/og from report data.

Sections in order:
1. Hero — name, Steam cover image, sentiment badge, hidden_gem_score
2. The Verdict — one_liner, sentiment score bar
3. Quick Stats — reviews, release date, price, developer
4. Design Strengths — green chips (FREE)
5. Gameplay Friction — red chips (FREE)
6. Audience Profile — ideal for / not for cards (FREE)
7. Sentiment Trend — badge + trend_note (FREE)
8. Genre Context — single sentence (FREE)
9. 🔒 Player Wishlist — blurred overlay + CTA if no key (PREMIUM)
10. 🔒 Churn Triggers — blurred overlay + CTA if no key (PREMIUM)
11. 🔒 Developer Priorities — numbered action items with effort/frequency badges (PREMIUM)
12. Competitive Context — named game chips, cross-linked (FREE)
13. Related Games — same genre/tag (FREE)

Premium unlock:
- Blurred frosted glass overlay on sections 9-11
- CTA: "You're a developer doing pre-launch research. Get action items, refund signals, and
  feature gaps your competitors haven't fixed — $7"
- Click → modal with license key input → POST /api/validate-key
- On success: store key in localStorage, re-render premium sections

### Other pages

- `frontend/app/page.tsx` — Home: search, trending, featured (hidden gems), genre grid
- `frontend/app/genre/[slug]/page.tsx` — ISR daily, top 20 games + aggregate insight
- `frontend/app/tag/[slug]/page.tsx` — same structure as genre
- `frontend/app/developer/[slug]/page.tsx` — all games by developer, cross-game comparison
- `frontend/app/sitemap.ts` — all game/genre/tag URLs with lastModified

### Verify Phase 4

```bash
cd frontend && npm run dev
# Check: game page renders, premium sections blurred, unlock flow works
# Check: Lighthouse score > 90 performance + SEO
```

---

## Phase 5: Featured Spots (CloudFront KVS)

### infra/cloudfront_functions/inject_sponsor.js

CloudFront Function that reads from KVS and injects `x-sponsor-data` header:
```javascript
import cf from 'cloudfront';
const kvs = cf.kvs();
async function handler(event) {
  const uri = event.request.uri;
  if (!uri.startsWith('/games/')) return event.request;
  try {
    const appid = uri.split('/')[2];
    const sponsor = await kvs.get(`sponsor_${appid}`, { format: 'json' });
    if (sponsor) event.request.headers['x-sponsor-data'] = { value: JSON.stringify(sponsor) };
  } catch (e) { /* no sponsor */ }
  return event.request;
}
```

### Admin endpoint

`POST /api/admin/feature-spot` (X-Admin-Key required)
Writes sponsor JSON to CloudFront KVS via boto3. Visible globally within seconds.

---

## Phase 6: Pro Chat (V2)

Update `steampulse/chat.py` to use new schema field names:
- `design_strengths` (was `top_praises`)
- `gameplay_friction` (was `top_complaints`)
- `dev_priorities` (was `dev_action_items`)
- `churn_triggers` (was `refund_risk_signals`)

No new infrastructure needed. Gated by `PRO_ENABLED=true`.

---

## Cross-Cutting Rules (Apply Throughout)

- All API errors: `{"error": "...", "code": "..."}` — never expose stack traces
- All FastAPI endpoints: `async def`
- DB connections: initialized at module level outside handlers (Lambda reuse)
- No hardcoded secrets, account IDs, or region strings anywhere
- Admin endpoints: validate `X-Admin-Key` header against env var
- Haiku for chunk processing only. Sonnet for synthesis only (one call per game).

---

## Complete File Structure When Done

```
repo-root/
  CLAUDE.md, steampulse-design.org, steam_analyzer_prompt.md
  cdk.json, pyproject.toml, poetry.lock, Dockerfile, .env.example, .gitignore

  steampulse/
    api.py, analyzer.py (DO NOT MODIFY), storage.py, steam_source.py
    rate_limiter.py, chat.py, main.py

  crawler/
    app_crawler.py, review_crawler.py

  scripts/
    seed.py

  infra/
    app.py, pipeline_stack.py, application_stage.py
    cloudfront_functions/inject_sponsor.js
    stacks/
      data_stack.py, network_stack.py, app_stack.py, frontend_stack.py
      crawler_stack.py, analysis_stack.py, monitoring_stack.py

  frontend/
    app/
      page.tsx
      games/[appid]/[slug]/page.tsx
      genre/[slug]/page.tsx
      tag/[slug]/page.tsx
      developer/[slug]/page.tsx
      sitemap.ts
    lib/types.ts, lib/api.ts
    components/
      ReportHero.tsx, SentimentBar.tsx, ChipList.tsx
      PremiumSection.tsx, UnlockModal.tsx, DevPriorityCard.tsx

  .claude/commands/
    analyze-game.md, check-schema.md, cdk-diff.md, new-stack.md
```

---

## Definition of Done (Each Phase)

- Code runs without errors locally
- All existing tests pass
- No hardcoded secrets or account IDs
- `CLAUDE.md` is still accurate after your changes
