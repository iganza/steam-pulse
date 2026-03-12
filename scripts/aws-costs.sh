#!/usr/bin/env bash
# aws-costs.sh — dump current AWS cost/usage summary
# Usage: ./scripts/aws-costs.sh [--mtd | --last-month | --days N]
#
# Requires: aws cli, jq
# Cost Explorer must be enabled in your AWS account (free to enable, $0.01/API call)

set -euo pipefail

command -v jq >/dev/null 2>&1 || { echo "Error: jq is required. brew install jq"; exit 1; }

# --- Date ranges ---
TODAY=$(date +%Y-%m-%d)
FIRST_OF_MONTH=$(date +%Y-%m-01)
LAST_MONTH_START=$(date -v-1m +%Y-%m-01 2>/dev/null || date -d "$(date +%Y-%m-01) -1 month" +%Y-%m-01)
LAST_MONTH_END=$FIRST_OF_MONTH

MODE="mtd"
DAYS=7

while [[ $# -gt 0 ]]; do
  case $1 in
    --mtd)         MODE="mtd" ;;
    --last-month)  MODE="last-month" ;;
    --days)        MODE="days"; DAYS="${2}"; shift ;;
    *) echo "Usage: $0 [--mtd | --last-month | --days N]"; exit 1 ;;
  esac
  shift
done

case $MODE in
  mtd)
    START=$FIRST_OF_MONTH
    END=$TODAY
    LABEL="Month to date (${START} → ${END})"
    ;;
  last-month)
    START=$LAST_MONTH_START
    END=$LAST_MONTH_END
    LABEL="Last month (${START} → ${END})"
    ;;
  days)
    START=$(date -v-${DAYS}d +%Y-%m-%d 2>/dev/null || date -d "${DAYS} days ago" +%Y-%m-%d)
    END=$TODAY
    LABEL="Last ${DAYS} days (${START} → ${END})"
    ;;
esac

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  AWS Cost Report — ${LABEL}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# --- Total cost ---
TOTAL=$(aws ce get-cost-and-usage \
  --time-period Start="${START}",End="${END}" \
  --granularity MONTHLY \
  --metrics "UnblendedCost" \
  --query "ResultsByTime[*].Total.UnblendedCost" \
  --output json | jq '[.[].Amount | tonumber] | add // 0')

printf "  %-30s %s\n" "Total:" "\$$(printf '%.2f' "$TOTAL") USD"
echo ""

# --- By service ---
echo "  By service:"
echo "  ─────────────────────────────────────────────"

aws ce get-cost-and-usage \
  --time-period Start="${START}",End="${END}" \
  --granularity MONTHLY \
  --metrics "UnblendedCost" \
  --group-by Type=DIMENSION,Key=SERVICE \
  --output json | jq -r '
    .ResultsByTime[].Groups[]
    | select((.Metrics.UnblendedCost.Amount | tonumber) > 0.001)
    | [.Keys[0], (.Metrics.UnblendedCost.Amount | tonumber)]
    | @tsv
  ' | sort -k2 -rn | while IFS=$'\t' read -r service amount; do
    printf "  %-40s \$%.2f\n" "$service" "$amount"
  done

echo ""

# --- Daily breakdown for current period ---
if [[ "$MODE" != "last-month" ]]; then
  echo "  Daily trend:"
  echo "  ─────────────────────────────────────────────"

  aws ce get-cost-and-usage \
    --time-period Start="${START}",End="${END}" \
    --granularity DAILY \
    --metrics "UnblendedCost" \
    --output json | jq -r '
      .ResultsByTime[]
      | [.TimePeriod.Start, (.Total.UnblendedCost.Amount | tonumber)]
      | @tsv
    ' | while IFS=$'\t' read -r day amount; do
      bar_len=$(echo "$amount * 40 / 5" | bc 2>/dev/null || echo 0)
      bar=$(printf '█%.0s' $(seq 1 $((bar_len > 0 ? bar_len : 0)) 2>/dev/null) 2>/dev/null || echo "")
      printf "  %s  \$%.3f  %s\n" "$day" "$amount" "$bar"
    done
  echo ""
fi

# --- Forecasted month-end (MTD only) ---
if [[ "$MODE" == "mtd" && "$TODAY" != "$FIRST_OF_MONTH" ]]; then
  NEXT_MONTH=$(date -v+1m +%Y-%m-01 2>/dev/null || date -d "$(date +%Y-%m-01) +1 month" +%Y-%m-01)
  FORECAST=$(aws ce get-cost-forecast \
    --time-period Start="${TODAY}",End="${NEXT_MONTH}" \
    --granularity MONTHLY \
    --metric UNBLENDED_COST \
    --query "Total.Amount" \
    --output text 2>/dev/null || echo "0")

  FORECAST_TOTAL=$(echo "$TOTAL + $FORECAST" | bc)
  printf "  %-30s %s\n" "Forecasted month-end:" "\$$(printf '%.2f' "$FORECAST_TOTAL") USD"
  echo ""
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
