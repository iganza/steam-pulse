#!/usr/bin/env bash
# Invoke the analysis Lambda locally for a single game.
# Usage: ./scripts/dev/invoke-analysis.sh <appid> [game_name]
#
# Reads: reviews table (DB must already be populated via invoke-review-crawler.sh)
# Writes: reports table

set -euo pipefail

APPID="${1:?Usage: $0 <appid> [game_name]}"
GAME_NAME="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Load .env if present
if [[ -f "$ROOT/.env" ]]; then
    set -o allexport
    source "$ROOT/.env"
    set +o allexport
fi

export DATABASE_URL="${DATABASE_URL:-postgresql://steampulse:dev@127.0.0.1:5432/steampulse}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"

cd "$ROOT"

poetry run python - "$APPID" "$GAME_NAME" <<'PYEOF'
import sys, asyncio, json
sys.path.insert(0, "src/lambda-functions")
sys.path.insert(0, "src/library-layer")

class MockContext:
    function_name = "local-analysis"
    memory_limit_in_mb = 1024
    invoked_function_arn = "arn:aws:lambda:us-west-2:123456789012:function:local-analysis"
    aws_request_id = "local-request-id"

appid = int(sys.argv[1])
game_name = sys.argv[2] if len(sys.argv) > 2 else ""

event = {"appid": appid, "game_name": game_name}

from lambda_functions.analysis.handler import handler
result = handler(event, MockContext())
print(json.dumps(result, indent=2))
PYEOF
