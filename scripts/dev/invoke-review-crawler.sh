#!/usr/bin/env bash
# Invoke the review_crawler Lambda handler locally for a given appid.
# Hits real Steam reviews API, writes to local Postgres, triggers staging Step Functions.
#
# Usage:
#   ./scripts/dev/invoke-review-crawler.sh 440
#   ./scripts/dev/invoke-review-crawler.sh 440 730
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 <appid> [appid2 ...]"
  exit 1
fi

export DATABASE_URL="${DATABASE_URL:-postgresql://steampulse:dev@localhost:5432/steampulse}"
export SFN_ARN="${SFN_ARN:-arn:aws:states:us-west-2:052475889199:stateMachine:AnalysisMachine71715F9C-7A0mausNtyJN}"
export DB_SECRET_ARN="${DB_SECRET_ARN:-}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
export PYTHONPATH="$REPO_ROOT/src/library-layer:$REPO_ROOT/src/lambda-functions"

RECORDS=$(python3 - "$@" <<'EOF'
import sys, json
records = [{"messageId": f"local-{a}", "body": json.dumps({"appid": int(a)}), "receiptHandle": "local"} for a in sys.argv[1:]]
print(json.dumps({"Records": records}))
EOF
)

echo "▶ Invoking review_crawler for appids: $*"
poetry run python - <<EOF
import asyncio, json, sys
sys.path.insert(0, "$REPO_ROOT/src/library-layer")
sys.path.insert(0, "$REPO_ROOT/src/lambda-functions")
from lambda_functions.review_crawler.handler import handler
event = $RECORDS
asyncio.run(handler(event, {}))
EOF
echo "✓ Done"
