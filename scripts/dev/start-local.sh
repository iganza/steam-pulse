#!/usr/bin/env bash
# Start local Postgres and initialise the DB schema.
# Usage: ./scripts/dev/start-local.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "▶ Starting Postgres..."
docker compose up -d db

echo "⏳ Waiting for Postgres to be ready..."
until docker compose exec -T db pg_isready -U steampulse -q; do
  sleep 1
done
echo "✓ Postgres is up"

echo "▶ Initialising schema..."
export DATABASE_URL="postgresql://steampulse:dev@localhost:5432/steampulse"
export PYTHONPATH="$REPO_ROOT/src/library-layer:$REPO_ROOT/src/lambda-functions"
poetry run python - <<'EOF'
import sys, os
sys.path.insert(0, "src/library-layer")
import psycopg2
from library_layer.schema import create_all
conn = psycopg2.connect(os.environ["DATABASE_URL"])
create_all(conn)
conn.close()
print("✓ Schema ready")
EOF

echo ""
echo "Local DB is ready. Copy this into your shell or .env:"
echo ""
echo "  export DATABASE_URL=postgresql://steampulse:dev@localhost:5432/steampulse"
echo "  export PYTHONPATH=$REPO_ROOT/src/library-layer:$REPO_ROOT/src/lambda-functions"
