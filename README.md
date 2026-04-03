# SteamPulse

AI-powered Steam game intelligence platform. LLM-synthesised review analysis for ~6,000 Steam games.

## Local Development

### Prerequisites

- Python 3.12+, Poetry
- Docker Desktop (for local Postgres)
- AWS credentials configured (`aws configure`) with access to the staging account

### First-time setup

```bash
# 1. Install dependencies
poetry install

# 2. Copy env and fill in secrets
cp .env.example .env
# Edit .env — at minimum set LEMONSQUEEZY_API_KEY, RESEND_API_KEY

# 3. Start local Postgres and initialise schema
./scripts/dev/start-local.sh
```

### Running locally

```bash
# API server (hot reload, http://localhost:8000)
./scripts/dev/run-api.sh

# Test app crawler for a specific game (appid 440 = TF2)
./scripts/dev/invoke-app-crawler.sh 440

# Test review crawler (fetches reviews + triggers staging Step Functions)
./scripts/dev/invoke-review-crawler.sh 440

# Multiple appids at once
./scripts/dev/invoke-app-crawler.sh 440 730 570
```

### Running the frontend locally

```bash
cd frontend && npm install

# Option A: frontend + local API (default)
# Requires: ./scripts/dev/run-api.sh running in another terminal
npm run dev

# Option B: frontend pointing at staging API (no local API needed)
API_URL=https://d218hpg56ignkd.cloudfront.net npm run dev
```

Next.js proxies `/api/*` to the API server in dev mode. In staging/production, CloudFront
handles this at the CDN layer — no config change needed.

### AWS services used locally

The crawlers and API connect to real AWS services using your local credentials:

| Service | Used by | Notes |
|---|---|---|
| Bedrock | analyzer | Needs model access enabled in us-west-2 |
| SQS | app_crawler | Pushes to staging review queue |
| Step Functions | review_crawler | Triggers staging analysis state machine |
| RDS | all | Replaced by local Docker Postgres |

### Running tests

```bash
poetry run pytest -v
```

Tests use `moto` to mock AWS and `pytest-httpx` to mock Steam API calls — no real network calls, no real AWS needed.

### Seed staging with games

```bash
export APP_CRAWL_QUEUE_PARAM_NAME="/steampulse/staging/messaging/app-crawl-queue-url"
poetry run python scripts/seed.py --limit 50
```

## Project Layout

```
src/
  library-layer/          # Shared Lambda layer: httpx, psycopg2, boto3, anthropic + framework code
    library_layer/        # analyzer, storage, steam_source, fetcher, reporter
  lambda-functions/       # All Lambda handlers
    lambda_functions/
      app_crawler/        # Crawls Steam metadata → writes to DB → queues review crawl
      review_crawler/     # Fetches reviews → writes to DB → triggers Step Functions
      api/                # FastAPI app: /preview, /validate-key, /health, /chat

infra/                    # AWS CDK (Python)
  stacks/
    common_stack.py       # Lambda layers
    sqs_stack.py          # SQS queues
    lambda_stack.py       # Lambda functions + EventBridge
    app_stack.py          # API + CloudFront
    data_stack.py         # RDS / Aurora
    analysis_stack.py     # Step Functions
    frontend_stack.py     # Next.js via OpenNext
    monitoring_stack.py   # CloudWatch dashboards + alarms

frontend/                 # Next.js app (deployed via OpenNext → CloudFront)
scripts/
  dev/                    # Local development helpers
  seed.py                 # Bootstrap top-N games into SQS
  aws-costs.sh            # AWS cost report
```

## Deployment

Push to `main` → pipeline auto-deploys to staging. Production requires manual approval in CodePipeline.

```bash
# Deploy pipeline changes manually (self-mutating pipeline)
cd infra && poetry run cdk deploy SteamPulsePipeline

# Check staging CloudFront URL
aws cloudformation describe-stacks --stack-name Staging-App \
  --query "Stacks[0].Outputs" --output table
```

