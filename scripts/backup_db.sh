#!/usr/bin/env bash
# Dump the local SteamPulse dev database to a timestamped file.
# Runs pg_dump inside the Docker container to avoid client/server version mismatch.
# Usage: ./scripts/backup_db.sh [output_dir]
# Default output dir: ./backups/

set -euo pipefail

CONTAINER="${DB_CONTAINER:-steam-pulse-db-1}"
DB_NAME="${DB_NAME:-steampulse}"
DB_USER="${DB_USER:-steampulse}"
OUTPUT_DIR="${1:-$(dirname "$0")/../backups}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
FILENAME="steampulse_${TIMESTAMP}.sql.gz"
FILEPATH="${OUTPUT_DIR}/${FILENAME}"

mkdir -p "$OUTPUT_DIR"

echo "Container: $CONTAINER"
echo "Database:  $DB_NAME"
echo "Destination: $FILEPATH"

docker exec "$CONTAINER" \
  pg_dump -U "$DB_USER" -d "$DB_NAME" --format=plain \
  | gzip > "$FILEPATH"

SIZE=$(du -sh "$FILEPATH" | cut -f1)
echo "Done. $FILENAME ($SIZE)"
