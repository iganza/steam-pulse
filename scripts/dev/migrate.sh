#!/usr/bin/env bash
# Apply pending yoyo migrations to the local dev DB (or staging via tunnel).
#
# Usage:
#   bash scripts/dev/migrate.sh                      # local dev (DATABASE_URL from env or .env)
#   bash scripts/dev/migrate.sh --stage staging      # staging (tunnel must be open on localhost:5433)
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

MIGRATIONS_DIR="src/lambda-functions/migrations"
REGION="${AWS_DEFAULT_REGION:-us-west-2}"

if [[ "${1:-}" == "--stage" ]]; then
  STAGE_NAME="${2:-staging}"
  echo "▶ Fetching DB password from Secrets Manager (${STAGE_NAME})..."
  PGPASSWORD=$(aws secretsmanager get-secret-value \
    --secret-id "steampulse/${STAGE_NAME}/db-credentials" \
    --region "$REGION" \
    --query 'SecretString' \
    --output text \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['password'])")
  export DATABASE_URL="postgresql://postgres:${PGPASSWORD}@localhost:5433/steampulse"
  echo "✓ Using staging tunnel at localhost:5433"
fi

# Load DATABASE_URL from .env if not already set
if [[ -z "${DATABASE_URL:-}" ]] && [[ -f "$REPO_ROOT/.env" ]]; then
  DATABASE_URL=$(grep -E '^DATABASE_URL=' "$REPO_ROOT/.env" | cut -d= -f2-)
  export DATABASE_URL
fi

: "${DATABASE_URL:?DATABASE_URL is not set. Start local DB or open the staging tunnel first.}"

echo "▶ Applying migrations from ${MIGRATIONS_DIR}..."
poetry run yoyo apply --database "$DATABASE_URL" --no-config-file --batch "$MIGRATIONS_DIR"
echo "✓ Migrations applied."
