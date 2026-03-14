#!/usr/bin/env bash
# End-to-end local pipeline for a small set of games.
# Runs all three stages in order:
#   1. App metadata crawl  → games, tags, genres, game_categories
#   2. Review crawl        → reviews table
#   3. LLM analysis        → reports table
#
# Usage:
#   ./scripts/dev/seed-local.sh                     # default 5 games
#   ./scripts/dev/seed-local.sh 440 730 570         # specific appids
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# Defaults: TF2, CS2, Dota 2, Cyberpunk 2077, Stardew Valley
DEFAULT_APPIDS=(440 730 570 1091500 413150)

if [[ $# -gt 0 ]]; then
  APPIDS=("$@")
else
  APPIDS=("${DEFAULT_APPIDS[@]}")
fi

export DATABASE_URL="postgresql://steampulse:dev@127.0.0.1:5432/steampulse"
export PYTHONPATH="$REPO_ROOT/src/library-layer:$REPO_ROOT/src/lambda-functions"
export DB_SECRET_ARN=""
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"

# Load .env for ANTHROPIC_API_KEY and STEAM_API_KEY
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a; source "$REPO_ROOT/.env"; set +a
fi
# Override DATABASE_URL — .env may have a placeholder
export DATABASE_URL="postgresql://steampulse:dev@127.0.0.1:5432/steampulse"

APPIDS_STR="${APPIDS[*]}"

echo "================================================"
echo " SteamPulse local seed"
echo " Games: $APPIDS_STR"
echo "================================================"
echo ""

# ---------------------------------------------------------------------------
# Stage 1: App metadata crawl
# ---------------------------------------------------------------------------
echo "▶ Stage 1/3 — App metadata crawl"

RECORDS=$(python3 - "${APPIDS[@]}" <<'PYEOF'
import sys, json
records = [
    {"messageId": f"local-{a}", "body": json.dumps({"appid": int(a)}), "receiptHandle": "local"}
    for a in sys.argv[1:]
]
print(json.dumps({"Records": records}))
PYEOF
)

poetry run python - <<PYEOF
import json, sys
sys.path.insert(0, "$REPO_ROOT/src/library-layer")
sys.path.insert(0, "$REPO_ROOT/src/lambda-functions")
from lambda_functions.app_crawler.handler import handler

class MockContext:
    function_name = "local-app-crawler"
    memory_limit_in_mb = 512
    invoked_function_arn = "arn:aws:lambda:us-east-1:000000000000:function:local"
    aws_request_id = "local-request"

result = handler($RECORDS, MockContext())
failures = result.get("batchItemFailures", [])
print(f"  Done — {len(failures)} failures")
if failures:
    print("  Failures:", failures)
PYEOF

echo "✓ Stage 1 complete"
echo ""

# ---------------------------------------------------------------------------
# Stage 2: Review crawl
# ---------------------------------------------------------------------------
echo "▶ Stage 2/3 — Review crawl"

# Disable SFN trigger locally — we'll run analysis manually in stage 3
export SFN_ARN=""

APPIDS_JSON=$(python3 -c "import sys,json; print(json.dumps([int(x) for x in sys.argv[1:]]))" "${APPIDS[@]}")

poetry run python - <<PYEOF
import json, sys, os
sys.path.insert(0, "$REPO_ROOT/src/library-layer")
sys.path.insert(0, "$REPO_ROOT/src/lambda-functions")

class MockContext:
    function_name = "local-review-crawler"
    memory_limit_in_mb = 512
    invoked_function_arn = "arn:aws:lambda:us-east-1:000000000000:function:local"
    aws_request_id = "local-request"

appids = $APPIDS_JSON
records = [
    {"messageId": f"local-{a}", "body": json.dumps({"appid": a}), "receiptHandle": "local"}
    for a in appids
]
event = {"Records": records}

from lambda_functions.review_crawler.handler import handler
result = handler(event, MockContext())
failures = result.get("batchItemFailures", [])
print(f"  Done — {len(appids)} processed, {len(failures)} failures")
if failures:
    print("  Failures:", failures)
PYEOF

echo "✓ Stage 2 complete"
echo ""

# ---------------------------------------------------------------------------
# Stage 3: LLM analysis
# ---------------------------------------------------------------------------
echo "▶ Stage 3/3 — LLM analysis"

for appid in "${APPIDS[@]}"; do
    echo "  Analyzing appid=${appid}..."
    PYTHONPATH="$REPO_ROOT/src/library-layer:$REPO_ROOT/src/lambda-functions" \
      poetry run python main.py --appid "$appid" --max-reviews 500 2>&1 \
        | grep -E "^(✓|✗|Error|appid|one_liner|overall|WARNING|ERROR)" || true
    echo ""
done

echo "✓ Stage 3 complete"
echo ""
echo "================================================"
echo " All done! Query your local DB to verify:"
echo "   SELECT appid, name, review_count FROM games;"
echo "   SELECT appid, last_analyzed FROM reports;"
echo "================================================"
