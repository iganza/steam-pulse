#!/usr/bin/env bash
# Deploy SteamPulse to AWS.
#
# Usage:
#   bash scripts/deploy.sh --env staging
#   bash scripts/deploy.sh --env production
#   bash scripts/deploy.sh --env staging --skip-frontend   # skip frontend build
#   bash scripts/deploy.sh --env staging --skip-migrations # skip DB migration step
#
# Prerequisites:
#   - AWS credentials configured (aws sso login or env vars)
#   - Node.js + npm installed (for frontend build)
#   - Poetry installed
#   - Docker running (required for CDK asset bundling)

set -euo pipefail

# ── Argument parsing ──────────────────────────────────────────────────────────
ENV=""
SKIP_FRONTEND=false
SKIP_MIGRATIONS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --env) ENV="$2"; shift 2 ;;
        --skip-frontend) SKIP_FRONTEND=true; shift ;;
        --skip-migrations) SKIP_MIGRATIONS=true; shift ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

if [[ -z "$ENV" ]]; then
    echo "Usage: bash scripts/deploy.sh --env staging|production"
    exit 1
fi

if [[ "$ENV" != "staging" && "$ENV" != "production" ]]; then
    echo "Error: --env must be 'staging' or 'production'"
    exit 1
fi

ENV_CAP="$(tr '[:lower:]' '[:upper:]' <<< "${ENV:0:1}")${ENV:1}"  # "Staging" | "Production"
STACK_PATTERN="SteamPulse-${ENV_CAP}-*"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  SteamPulse deploy → ${ENV}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Step 1: Build frontend ────────────────────────────────────────────────────
if [[ "$SKIP_FRONTEND" == "false" ]]; then
    echo "▶ Step 1/4 — Building Next.js frontend (OpenNext)"
    cd "$REPO_ROOT/frontend"
    npm install --silent
    npx --yes open-next@latest build
    cd "$REPO_ROOT"
    echo "✓ Frontend build complete"
else
    echo "▶ Step 1/4 — Skipping frontend build (--skip-frontend)"
fi

echo ""

# ── Step 2: CDK deploy ────────────────────────────────────────────────────────
echo "▶ Step 2/4 — CDK deploy: ${STACK_PATTERN}"
cd "$REPO_ROOT"
poetry run cdk deploy "$STACK_PATTERN" \
    --require-approval never \
    --concurrency 5 \
    --verbose \
    --progress events \
    --outputs-file /tmp/steampulse-cdk-outputs.json
echo "✓ CDK deploy complete"

echo ""

# ── Step 3: Apply DB migrations ───────────────────────────────────────────────
if [[ "$SKIP_MIGRATIONS" == "false" ]]; then
    echo "▶ Step 3/4 — Applying DB migrations"

    MIGRATION_FN_ARN=$(aws ssm get-parameter \
        --name "/steampulse/${ENV}/compute/migration-fn-arn" \
        --query Parameter.Value \
        --output text 2>/dev/null || echo "")

    if [[ -z "$MIGRATION_FN_ARN" ]]; then
        echo "  ⚠ SSM param /steampulse/${ENV}/compute/migration-fn-arn not found — skipping migrations"
        echo "  (MigrationFn may not be deployed yet)"
    else
        aws lambda invoke \
            --function-name "$MIGRATION_FN_ARN" \
            --invocation-type RequestResponse \
            --log-type Tail \
            --payload '{}' \
            /tmp/steampulse-migrate-out.json \
            --query LogResult \
            --output text | base64 --decode | tail -20 || true

        echo ""
        echo "Migration result:"
        cat /tmp/steampulse-migrate-out.json
        echo ""

        # Fail if Lambda returned a function error
        if grep -q '"FunctionError"' /tmp/steampulse-migrate-out.json 2>/dev/null; then
            echo "✗ Migration Lambda returned an error — deploy aborted"
            exit 1
        fi

        echo "✓ Migrations applied"
    fi
else
    echo "▶ Step 3/4 — Skipping migrations (--skip-migrations)"
fi

echo ""

# ── Step 4: Invalidate CloudFront cache ──────────────────────────────────────
echo "▶ Step 4/4 — Invalidating CloudFront cache"

DIST_ID=$(aws ssm get-parameter \
    --name "/steampulse/${ENV}/delivery/distribution-id" \
    --query Parameter.Value \
    --output text 2>/dev/null || echo "")

if [[ -z "$DIST_ID" ]]; then
    echo "  ⚠ SSM param /steampulse/${ENV}/delivery/distribution-id not found — skipping invalidation"
else
    aws cloudfront create-invalidation \
        --distribution-id "$DIST_ID" \
        --paths "/*" \
        --query Invalidation.Id \
        --output text
    echo "✓ CloudFront cache invalidated"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Deploy complete → ${ENV}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
