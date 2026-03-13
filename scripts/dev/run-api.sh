#!/usr/bin/env bash
# Run the FastAPI API server locally with hot reload.
# Connects to local Docker Postgres by default.
#
# Usage:
#   ./scripts/dev/run-api.sh
#   DATABASE_URL=postgresql://... ./scripts/dev/run-api.sh   # override (e.g. staging RDS via tunnel)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# Capture any DATABASE_URL set in the caller's shell before sourcing .env
CALLER_DB_URL="${DATABASE_URL:-}"

# Load .env for other vars (API keys etc.) — but don't let placeholder DATABASE_URL win
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

# Restore caller's DATABASE_URL if set, otherwise use local Docker default
if [[ -n "$CALLER_DB_URL" ]]; then
  export DATABASE_URL="$CALLER_DB_URL"
else
  export DATABASE_URL="postgresql://steampulse:dev@localhost:5432/steampulse"
fi

export STEP_FUNCTIONS_ARN="${STEP_FUNCTIONS_ARN:-arn:aws:states:us-west-2:052475889199:stateMachine:AnalysisMachine71715F9C-7A0mausNtyJN}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
export PYTHONPATH="$REPO_ROOT/src/library-layer:$REPO_ROOT/src/lambda-functions"

echo "▶ Starting API server at http://localhost:8000"
echo "  DATABASE_URL=$DATABASE_URL"
echo "  Press Ctrl+C to stop"
echo ""

poetry run uvicorn lambda_functions.api.handler:app \
  --reload \
  --reload-dir "$REPO_ROOT/src" \
  --host 0.0.0.0 \
  --port 8000
