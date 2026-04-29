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
#
# ── FIRST-TIME PRODUCTION DEPLOY — manual pre-flight steps ───────────────────
#
# The db-credentials secret is managed outside CDK (no lifecycle coupling).
# Create it once before the first production deploy, then never touch it again:
#
#   aws secretsmanager create-secret \
#     --name "steampulse/production/db-credentials" \
#     --secret-string '{"username":"postgres","password":"STRONG_RANDOM_PASSWORD"}'
#
# Also create the other two secrets if they don't exist:
#
#   aws secretsmanager create-secret \
#     --name "steampulse/production/steam-api-key" \
#     --secret-string '{"api_key":"YOUR_STEAM_API_KEY"}'
#
#   aws secretsmanager create-secret \
#     --name "steampulse/production/resend-api-key" \
#     --secret-string '{"api_key":"YOUR_RESEND_API_KEY"}'
#
# To point steampulse.io at production once ready, set in cdk.json:
#   "domain-live": true
# …then re-run this script.
# ─────────────────────────────────────────────────────────────────────────────

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

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Build ID — passed to CDK as context, used by compute_stack to namespace the
# OpenNext ISR cache prefix (cache/${BUILD_ID}/...). Each deploy writes to a
# fresh prefix so the new Lambda never reads pre-deploy HTML. Old prefixes age
# out via the 7-day S3 lifecycle rule on steampulse-frontend-${ENV}.
BUILD_ID="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || date +%s)"

if [[ "$ENV" == "production" ]]; then
    CURRENT_BRANCH=$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    if [[ "$CURRENT_BRANCH" != "main" ]]; then
        echo "Error: production deploys must be run from the 'main' branch."
        echo "  Current branch: $CURRENT_BRANCH"
        echo "  Run: git checkout main && git pull"
        exit 1
    fi
fi

ENV_CAP="$(tr '[:lower:]' '[:upper:]' <<< "${ENV:0:1}")${ENV:1}"  # "Staging" | "Production"
# Stage stacks use path notation (SteamPulse-Staging/Compute) while standalone
# stacks like Monitoring live at the top level (SteamPulse-Staging-Monitoring).
# Both patterns are required to deploy all stacks.
STAGE_PATTERN="SteamPulse-${ENV_CAP}/*"
STANDALONE_PATTERN="SteamPulse-${ENV_CAP}-Monitoring"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  SteamPulse deploy → ${ENV}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Step 1: Build frontend ────────────────────────────────────────────────────
if [[ "$SKIP_FRONTEND" == "false" ]]; then
    echo "▶ Step 1/4 — Building Next.js frontend (OpenNext)"
    cd "$REPO_ROOT/frontend"
    npm ci --silent
    # Clean prior build artifacts: stale .next can produce confusing
    # "Module not found: @vercel/turbopack-next/internal/font/..." or
    # missing build-manifest.json errors during open-next bundling.
    rm -rf .next .open-next
    # Plausible analytics: production-only, never fire in staging.
    # Always set explicitly so a leaky CI/shell export can't pollute a
    # non-production build.
    if [[ "$ENV" == "production" ]]; then
        export NEXT_PUBLIC_PLAUSIBLE_ENABLED=true
    else
        unset NEXT_PUBLIC_PLAUSIBLE_ENABLED
    fi
    npm run build:open-next
    cd "$REPO_ROOT"
    echo "✓ Frontend build complete"
else
    echo "▶ Step 1/4 — Skipping frontend build (--skip-frontend)"
fi

echo ""

# ── Step 2: CDK deploy ────────────────────────────────────────────────────────
echo "▶ Step 2/4 — CDK deploy: ${STAGE_PATTERN} + ${STANDALONE_PATTERN}"
cd "$REPO_ROOT"
poetry run cdk deploy "$STAGE_PATTERN" "$STANDALONE_PATTERN" \
    --context "build-id=${BUILD_ID}" \
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
            --output json > /tmp/steampulse-migrate-meta.json || true

        # Decode and print Lambda logs from invocation metadata
        python3 - <<'PY' 2>/dev/null || true
import json, base64
with open("/tmp/steampulse-migrate-meta.json") as f:
    meta = json.load(f)
log_b64 = meta.get("LogResult", "")
if log_b64:
    print(base64.b64decode(log_b64).decode("utf-8", errors="replace"))
PY

        echo ""
        echo "Migration result:"
        cat /tmp/steampulse-migrate-out.json
        echo ""

        # Fail if Lambda returned a function error
        python3 - <<'PY'
import json, sys
try:
    with open("/tmp/steampulse-migrate-meta.json") as f:
        meta = json.load(f)
    if meta.get("FunctionError"):
        print(f"✗ FunctionError: {meta['FunctionError']}")
        sys.exit(1)
except Exception as e:
    print(f"✗ Could not parse invocation metadata: {e}")
    sys.exit(1)
PY
        echo "✓ Migrations applied"
    fi
else
    echo "▶ Step 3/4 — Skipping migrations (--skip-migrations)"
fi

echo ""

# ── Step 4: Invalidate HTML in CloudFront ─────────────────────────────────────
# Hashed _next/static/* assets are content-addressed and intentionally omitted.
echo "▶ Step 4/4 — Invalidating HTML paths in CloudFront"
bash "$REPO_ROOT/scripts/invalidate-cdn.sh" --env "$ENV" --paths \
    "/" \
    "/games/*" \
    "/genre/*" \
    "/tag/*" \
    "/developer/*" \
    "/publisher/*" \
    "/reports" \
    "/reports/*" \
    "/about" \
    "/search"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Deploy complete → ${ENV}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Next: warm pages with"
echo "  poetry run python scripts/warm_game_pages.py"
echo ""
