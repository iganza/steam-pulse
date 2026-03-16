#!/usr/bin/env bash
# Invoke the crawler locally for specific appids.
#
# Usage:
#   ./scripts/dev/invoke-crawler.sh app 440 730 570
#   ./scripts/dev/invoke-crawler.sh reviews 440 730
set -euo pipefail

ACTION="${1:?Usage: $0 <app|reviews> <appid...>}"
shift

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 <app|reviews> <appid...>"
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

export DATABASE_URL="${DATABASE_URL:-postgresql://steampulse:dev@localhost:5432/steampulse}"
export DB_SECRET_ARN="${DB_SECRET_ARN:-}"
export REVIEW_CRAWL_QUEUE_URL="${REVIEW_CRAWL_QUEUE_URL:-}"
export SFN_ARN="${SFN_ARN:-}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
export PYTHONPATH="$REPO_ROOT/src/library-layer:$REPO_ROOT/src/lambda-functions"

if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a; source "$REPO_ROOT/.env"; set +a
fi
export DATABASE_URL="${DATABASE_URL:-postgresql://steampulse:dev@localhost:5432/steampulse}"

echo "▶ Crawling ${ACTION} for appids: $*"

poetry run python - "$ACTION" "$@" << 'PYEOF'
import sys, asyncio
sys.path.insert(0, "src/library-layer")
sys.path.insert(0, "src/lambda-functions")

action = sys.argv[1]
appids = [int(a) for a in sys.argv[2:]]

if action == "app":
    from lambda_functions.crawler.app_crawl import crawl_app
    async def run():
        for appid in appids:
            print(f"  appid={appid}")
            await crawl_app(appid)
    asyncio.run(run())
elif action == "reviews":
    from lambda_functions.crawler.review_crawl import crawl_reviews
    async def run():
        for appid in appids:
            n = await crawl_reviews(appid)
            print(f"  appid={appid} → {n} reviews")
    asyncio.run(run())
else:
    print(f"Unknown action '{action}'. Use: app | reviews", file=sys.stderr)
    sys.exit(1)
PYEOF

echo "✓ Done"
