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
  echo "▶ Fetching DB credentials from Secrets Manager (${STAGE_NAME})..."
  SECRET_JSON=$(aws secretsmanager get-secret-value \
    --secret-id "steampulse/${STAGE_NAME}/db-credentials" \
    --region "$REGION" \
    --query 'SecretString' \
    --output text)
  DB_USER=$(python3 -c "import sys, json; print(json.load(sys.stdin)['username'])" <<< "$SECRET_JSON")
  DB_PASS=$(python3 -c "import sys, json; print(json.load(sys.stdin)['password'])" <<< "$SECRET_JSON")
  DB_NAME=$(python3 -c "import sys, json; print(json.load(sys.stdin)['dbname'])" <<< "$SECRET_JSON")
  export DATABASE_URL="postgresql://${DB_USER}:${DB_PASS}@localhost:5433/${DB_NAME}"
  echo "✓ Using staging tunnel at localhost:5433 (database: ${DB_NAME})"
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

echo ""
echo "▶ Last 5 applied migrations:"
poetry run python3 - <<'PY'
import os, sys
try:
    import psycopg2
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("""
        SELECT migration_id, applied_at_utc
        FROM _yoyo_migration
        ORDER BY applied_at_utc DESC
        LIMIT 5
    """)
    rows = cur.fetchall()
    conn.close()
    for mid, ts in reversed(rows):
        print(f"  {ts.strftime('%Y-%m-%d %H:%M')}  {mid}")
except Exception as e:
    print(f"  (could not query migration state: {e})", file=sys.stderr)
PY
