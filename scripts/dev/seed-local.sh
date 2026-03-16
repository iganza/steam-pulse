#!/usr/bin/env bash
# End-to-end local pipeline for a small set of games.
# Runs all three stages in order:
#   1. App metadata crawl  → games, tags, genres, game_categories
#   2. Review crawl        → reviews table
#   3. LLM analysis        → reports table
#
# Usage:
#   ./scripts/dev/seed-local.sh                     # default 5 games
#   ./scripts/dev/seed-local.sh 440 730 570         # specific appids
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# Defaults: TF2, CS2, Dota 2, Cyberpunk 2077, Stardew Valley
DEFAULT_APPIDS=(440 730 570 1091500 413150)
if [[ $# -gt 0 ]]; then
  APPIDS=("$@")
else
  APPIDS=("${DEFAULT_APPIDS[@]}")
fi

export DATABASE_URL="postgresql://steampulse:dev@127.0.0.1:5432/steampulse"
export DB_SECRET_ARN=""
export REVIEW_CRAWL_QUEUE_URL=""
export SFN_ARN=""
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"

if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a; source "$REPO_ROOT/.env"; set +a
fi
export DATABASE_URL="postgresql://steampulse:dev@127.0.0.1:5432/steampulse"

echo "================================================"
echo " SteamPulse local seed"
echo " Games: ${APPIDS[*]}"
echo "================================================"
echo ""

echo "▶ Stage 1/3 — App metadata crawl"
bash "$SCRIPT_DIR/invoke-crawler.sh" app "${APPIDS[@]}"
echo "✓ Stage 1 complete"
echo ""

echo "▶ Stage 2/3 — Review crawl"
bash "$SCRIPT_DIR/invoke-crawler.sh" reviews "${APPIDS[@]}"
echo "✓ Stage 2 complete"
echo ""

echo "▶ Stage 3/3 — LLM analysis"
for appid in "${APPIDS[@]}"; do
  echo "  Analyzing appid=${appid}..."
  bash "$SCRIPT_DIR/invoke-analysis.sh" "$appid" 2>&1 \
    | grep -E "(appid|one_liner|overall_sentiment|ERROR|error)" || true
  echo ""
done
echo "✓ Stage 3 complete"

echo ""
echo "================================================"
echo " All done! Query your local DB to verify:"
echo "   SELECT appid, name, review_count FROM games;"
echo "   SELECT appid, last_analyzed FROM reports;"
echo "================================================"
