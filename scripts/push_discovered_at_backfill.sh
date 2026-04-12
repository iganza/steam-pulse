#!/usr/bin/env bash
set -euo pipefail

# Push locally-backfilled discovered_at dates to staging/production.
#
# Only updates rows where the local date is OLDER than the remote date,
# so it's safe to run repeatedly.
#
# Prerequisites:
#   - Local Postgres running (./scripts/dev/start-local.sh)
#   - SSH tunnel open to target DB (./scripts/dev/db-tunnel.sh)
#   - DATABASE_URL set to the remote DB
#
# Usage:
#   DATABASE_URL=postgresql://steampulse:<pass>@127.0.0.1:5433/production_steampulse \
#       bash scripts/push_discovered_at_backfill.sh
#
#   # Dry run — export only, don't push:
#   bash scripts/push_discovered_at_backfill.sh --dry-run

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
fi

EXPORT_FILE="/tmp/wayback_discovered_at.csv"

echo "=== Push discovered_at backfill ==="
echo "$(date '+%H:%M:%S') Exporting from local DB ..."

# Export rows where discovered_at was moved earlier than our initial catalog seed.
# The backfill sets dates from Wayback (often years ago), while the original
# catalog seed set discovered_at = NOW() for all rows.
ROW_COUNT=$(docker exec steam-pulse-db-1 psql -U steampulse -d steampulse -tA \
    -c "SELECT count(*) FROM app_catalog WHERE discovered_at < '2026-01-01'")

docker exec steam-pulse-db-1 psql -U steampulse -d steampulse \
    -c "\copy (SELECT appid, discovered_at FROM app_catalog WHERE discovered_at < '2026-01-01') TO STDOUT WITH CSV" \
    > "$EXPORT_FILE"

echo "$(date '+%H:%M:%S') Exported ${ROW_COUNT} rows to ${EXPORT_FILE}"

if [[ "$DRY_RUN" == "true" ]]; then
    echo "$(date '+%H:%M:%S') Dry run — showing first 10 rows:"
    head -10 "$EXPORT_FILE"
    echo "$(date '+%H:%M:%S') Done (dry run, nothing pushed)"
    exit 0
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "ERROR: DATABASE_URL not set. Point it at the remote DB via tunnel."
    echo "Example:"
    echo "  DATABASE_URL=postgresql://steampulse:<pass>@127.0.0.1:5433/production_steampulse \\"
    echo "      bash scripts/push_discovered_at_backfill.sh"
    exit 1
fi

echo "$(date '+%H:%M:%S') Pushing to remote DB ..."

UPDATED=$(psql "$DATABASE_URL" -tA <<'SQL'
    CREATE TEMP TABLE _wb(appid INT, discovered_at TIMESTAMPTZ);
    \copy _wb FROM '/tmp/wayback_discovered_at.csv' WITH CSV
    WITH updated AS (
        UPDATE app_catalog ac
        SET discovered_at = _wb.discovered_at
        FROM _wb
        WHERE ac.appid = _wb.appid AND ac.discovered_at > _wb.discovered_at
        RETURNING ac.appid
    )
    SELECT count(*) FROM updated;
SQL
)

echo "$(date '+%H:%M:%S') Updated ${UPDATED} rows on remote (only where remote date was newer)"
echo "$(date '+%H:%M:%S') Done"
