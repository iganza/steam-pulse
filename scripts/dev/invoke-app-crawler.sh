#!/usr/bin/env bash
# Invoke the app_crawler Lambda handler locally for a given appid.
# Hits real Steam + SteamSpy APIs, writes to local Postgres, pushes to staging SQS.
#
# Usage:
#   ./scripts/dev/invoke-app-crawler.sh 440
#   ./scripts/dev/invoke-app-crawler.sh 440 730 570   # multiple appids
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 <appid> [appid2 ...]"
  exit 1
fi

export DATABASE_URL="${DATABASE_URL:-postgresql://steampulse:dev@localhost:5432/steampulse}"
export REVIEW_CRAWL_QUEUE_URL="${REVIEW_CRAWL_QUEUE_URL:-https://sqs.us-west-2.amazonaws.com/052475889199/Staging-Crawler-ReviewCrawlQueue5BE98814-V3riq1YApkem}"
export DB_SECRET_ARN="${DB_SECRET_ARN:-}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
export PYTHONPATH="$REPO_ROOT/src/library-layer:$REPO_ROOT/src/lambda-functions"

# Build SQS-shaped Records from the appids passed as arguments
RECORDS=$(python3 - "$@" <<'EOF'
import sys, json
records = [{"messageId": f"local-{a}", "body": json.dumps({"appid": int(a)}), "receiptHandle": "local"} for a in sys.argv[1:]]
print(json.dumps({"Records": records}))
EOF
)

echo "▶ Invoking app_crawler for appids: $*"
poetry run python - <<EOF
import asyncio, json, sys
sys.path.insert(0, "$REPO_ROOT/src/library-layer")
sys.path.insert(0, "$REPO_ROOT/src/lambda-functions")
from lambda_functions.app_crawler.handler import handler
event = $RECORDS
asyncio.run(handler(event, {}))
EOF
echo "✓ Done"
