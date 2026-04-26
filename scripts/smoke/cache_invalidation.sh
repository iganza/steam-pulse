#!/usr/bin/env bash
# Post-deploy smoke test for the cache-until-changed loop.
#
# Verifies the end-to-end origin-side flow that took five PRs to land:
#   1. Page is cached at the origin (S3 entry exists)
#   2. Synthetic invoke of RevalidateFrontendFn deletes the S3 cache file
#   3. Next visit re-renders and writes a new S3 entry
#
# Catches regressions in BUILD_ID alignment, OpenNext revalidation pipeline
# wiring, route ISR classification, and the S3 file path layout — all of
# which are OpenNext-specific and not covered by unit tests.
#
# Run after every prod deploy:
#   bash scripts/smoke/cache_invalidation.sh
#
# Exit codes: 0 = pass, non-zero = regression (bash -e exits on first failure).

set -euo pipefail

ENV="${ENV:-production}"
API_BASE="${API_BASE:-https://d1mamturmn55fm.cloudfront.net}"
TIMEOUT_RERENDER_SECONDS="${TIMEOUT_RERENDER_SECONDS:-20}"

step() { printf "\n▶ %s\n" "$*"; }
fail() { printf "✗ %s\n" "$*" >&2; exit 1; }
ok()   { printf "✓ %s\n" "$*"; }

command -v aws >/dev/null  || fail "aws CLI required"
command -v jq  >/dev/null  || fail "jq required (brew install jq)"
command -v curl >/dev/null || fail "curl required"

# ── Resolve deployed resources ────────────────────────────────────────────
step "Resolving deployed resources in $ENV"
REVAL_FN=$(aws lambda list-functions --query \
  "Functions[?contains(FunctionName,'RevalidateFrontend')].FunctionName | [0]" \
  --output text)
[ -n "$REVAL_FN" ] && [ "$REVAL_FN" != "None" ] || fail "RevalidateFrontendFn not found"

FRONTEND_FN=$(aws lambda list-functions --query \
  "Functions[?contains(FunctionName,'FrontendFn') && !contains(FunctionName,'Revalidate')].FunctionName | [0]" \
  --output text)
[ -n "$FRONTEND_FN" ] && [ "$FRONTEND_FN" != "None" ] || fail "FrontendFn not found"

FN_URL=$(aws lambda get-function-url-config \
  --function-name "$FRONTEND_FN" --query FunctionUrl --output text)
FN_URL="${FN_URL%/}"

REVAL_ENV=$(aws lambda get-function-configuration --function-name "$REVAL_FN" \
  --query 'Environment.Variables' --output json)
BUCKET=$(echo "$REVAL_ENV" | jq -r '.FRONTEND_BUCKET')
PREFIX=$(echo "$REVAL_ENV" | jq -r '.CACHE_BUCKET_KEY_PREFIX')
BUILD_ID="${PREFIX#cache/}"
BUILD_ID="${BUILD_ID%/}"
[ -n "$BUCKET" ] && [ "$BUCKET" != "null" ] || fail "FRONTEND_BUCKET env missing on RevalidateFrontendFn"
[ -n "$BUILD_ID" ] || fail "could not derive BUILD_ID from CACHE_BUCKET_KEY_PREFIX=$PREFIX"
ok "RevalidateFrontendFn=$REVAL_FN, FrontendFn=$FRONTEND_FN, BUILD_ID=$BUILD_ID"

# ── Pick a recently-analyzed game ──────────────────────────────────────────
step "Picking a recently-analyzed game from $API_BASE"
GAME_JSON=$(curl -fsS "$API_BASE/api/discovery/just_analyzed?limit=1")
APPID=$(echo "$GAME_JSON" | jq -r '.games[0].appid')
SLUG=$(echo "$GAME_JSON" | jq -r '.games[0].slug')
[ "$APPID" != "null" ] && [ -n "$APPID" ] || fail "no analyzed games available"
ok "appid=$APPID slug=$SLUG"

PAGE_URL="$FN_URL/games/$APPID/$SLUG"
S3_PAGE_PREFIX="${PREFIX}${BUILD_ID}/games/$APPID/"

# ── Step 1: prime cache at origin ──────────────────────────────────────────
step "Priming cache (two hits to ensure entry is written)"
curl -fsS -o /dev/null -m 60 "$PAGE_URL"
sleep 2
curl -fsS -o /dev/null -m 60 "$PAGE_URL"
sleep 1

# ── Step 2: confirm S3 cache file exists ───────────────────────────────────
PRE_LASTMOD=$(aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "$S3_PAGE_PREFIX" \
  --query "Contents[?ends_with(Key,'.cache')].LastModified | [0]" --output text)
[ "$PRE_LASTMOD" != "None" ] && [ -n "$PRE_LASTMOD" ] || \
  fail "page cache file not at s3://$BUCKET/$S3_PAGE_PREFIX after priming — route may not be ISR (check generateStaticParams + revalidate export)"
ok "S3 cache file present (LastModified=$PRE_LASTMOD)"

# ── Step 3: synthetic invoke of RevalidateFrontendFn ───────────────────────
step "Invoking RevalidateFrontendFn synthetically"
PAYLOAD_FILE=$(mktemp)
trap 'rm -f "$PAYLOAD_FILE"' EXIT
jq -nc --argjson appid "$APPID" --arg slug "$SLUG" --arg ts "$(date +%s)" '
  {Records: [{
    messageId: ("smoke-\($ts)"),
    receiptHandle: "synthetic",
    body: ({
      Type: "Notification",
      Message: ({
        event_type: "report-ready",
        appid: $appid,
        game_name: $slug,
        slug: $slug
      } | tostring)
    } | tostring)
  }]}' > "$PAYLOAD_FILE"

OUT_FILE=$(mktemp)
trap 'rm -f "$PAYLOAD_FILE" "$OUT_FILE"' EXIT
STATUS=$(aws lambda invoke --function-name "$REVAL_FN" \
  --payload "fileb://$PAYLOAD_FILE" "$OUT_FILE" \
  --cli-binary-format raw-in-base64-out --query StatusCode --output text)
[ "$STATUS" = "200" ] || fail "Lambda invoke returned StatusCode=$STATUS"
FAILURES=$(jq -r '.batchItemFailures | length' "$OUT_FILE")
[ "$FAILURES" = "0" ] || fail "Lambda reported batchItemFailures: $(cat "$OUT_FILE")"
ok "Lambda returned 200 with no batch failures"

# ── Step 4: S3 cache file must be deleted ─────────────────────────────────
sleep 1
POST_LASTMOD=$(aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "$S3_PAGE_PREFIX" \
  --query "Contents[?ends_with(Key,'.cache')].LastModified | [0]" --output text 2>/dev/null || echo "None")
[ "$POST_LASTMOD" = "None" ] || \
  fail "S3 cache file still present after invocation (LastModified=$POST_LASTMOD) — s3:DeleteObject step is broken"
ok "S3 cache file deleted by RevalidateFrontendFn"

# ── Step 5: next visit must re-render and write a fresh entry ──────────────
step "Polling for re-render (up to ${TIMEOUT_RERENDER_SECONDS}s)"
DEADLINE=$(($(date +%s) + TIMEOUT_RERENDER_SECONDS))
NEW_LASTMOD="None"
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  curl -fsS -o /dev/null -m 60 "$PAGE_URL"
  sleep 2
  NEW_LASTMOD=$(aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "$S3_PAGE_PREFIX" \
    --query "Contents[?ends_with(Key,'.cache')].LastModified | [0]" --output text 2>/dev/null || echo "None")
  [ "$NEW_LASTMOD" != "None" ] && [ "$NEW_LASTMOD" != "$PRE_LASTMOD" ] && break
done
[ "$NEW_LASTMOD" != "None" ] && [ "$NEW_LASTMOD" != "$PRE_LASTMOD" ] || \
  fail "page did not re-render within ${TIMEOUT_RERENDER_SECONDS}s (pre=$PRE_LASTMOD post=$NEW_LASTMOD)"
ok "page re-rendered and re-cached (LastModified=$NEW_LASTMOD)"

printf "\n✓ cache-until-changed loop verified end-to-end\n"
