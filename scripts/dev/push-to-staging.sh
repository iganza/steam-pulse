#!/usr/bin/env bash
# Push local Postgres DB to a target Aurora environment via S3 + loader Lambda.
#
# Usage:
#   bash scripts/dev/push-to-staging.sh                        # dump local → staging (transient)
#   bash scripts/dev/push-to-staging.sh --save seed-v1         # dump local → staging + save named snapshot
#   bash scripts/dev/push-to-staging.sh --from seed-v1         # load existing snapshot → staging (no dump)
#   bash scripts/dev/push-to-staging.sh --list                 # list available snapshots
#   bash scripts/dev/push-to-staging.sh --stage prod --from seed-v1  # promote snapshot to prod
#
# Requires: pg_dump, aws cli

set -euo pipefail

STAGE="staging"
SNAPSHOT_NAME=""
FROM_SNAPSHOT=""
LIST_ONLY=false
LOCAL_DB="postgresql://steampulse:dev@127.0.0.1:5432/steampulse"
REGION="us-west-2"

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --stage)    STAGE="$2";          shift 2 ;;
    --save)     SNAPSHOT_NAME="$2";  shift 2 ;;
    --from)     FROM_SNAPSHOT="$2";  shift 2 ;;
    --list)     LIST_ONLY=true;      shift   ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# Normalize stage aliases so CDK stack names resolve correctly.
# CDK uses the capitalized full word: Staging, Production.
case "$STAGE" in
  prod)                STAGE="production" ;;
  staging|production)  ;;
  *) echo "ERROR: --stage must be staging or production (got: $STAGE)"; exit 1 ;;
esac

echo "==> Fetching ${STAGE} resources..."
STAGE_CAP="$(tr '[:lower:]' '[:upper:]' <<< "${STAGE:0:1}")${STAGE:1}"
# Bucket name is deterministic — no CloudFormation lookup needed.
BUCKET="steampulse-assets-${STAGE}"

# --list: show available snapshots and exit
if [[ "$LIST_ONLY" == true ]]; then
  echo "Available snapshots in s3://$BUCKET/db-snapshots/:"
  aws s3 ls "s3://$BUCKET/db-snapshots/" --region "$REGION" --no-cli-pager | awk '{print $3, $4}'
  exit 0
fi

LOADER_FN=$(aws cloudformation list-stack-resources \
  --stack-name "SteamPulse-${STAGE_CAP}-Compute" \
  --region "$REGION" --no-cli-pager \
  --query 'StackResourceSummaries[?LogicalResourceId==`DbLoaderFn`].PhysicalResourceId' \
  --output text)

if [[ -z "$LOADER_FN" ]]; then
  echo "ERROR: DbLoaderFn not found in SteamPulse-${STAGE_CAP}-Compute stack"
  exit 1
fi

echo "    Bucket : $BUCKET"
echo "    Lambda : $LOADER_FN"

TMP_FILE="/tmp/steampulse-dump.sql.gz"

if [[ -n "$FROM_SNAPSHOT" ]]; then
  # Load from an existing named snapshot — no local dump needed
  LOAD_KEY="db-snapshots/${FROM_SNAPSHOT}.sql.gz"
  echo "==> Loading from snapshot: s3://$BUCKET/$LOAD_KEY"
  # Verify it exists
  if ! aws s3 ls "s3://$BUCKET/$LOAD_KEY" --region "$REGION" --no-cli-pager &>/dev/null; then
    echo "ERROR: Snapshot not found. Run --list to see available snapshots."
    exit 1
  fi
else
  # Dump local DB
  echo "==> Dumping local DB..."
  pg_dump "$LOCAL_DB" \
    --no-owner --no-acl \
    --exclude-table=rate_limits \
    | gzip > "$TMP_FILE"

  if [[ -n "$SNAPSHOT_NAME" ]]; then
    # Save as a named snapshot
    SNAPSHOT_KEY="db-snapshots/${SNAPSHOT_NAME}.sql.gz"
    echo "==> Saving snapshot → s3://$BUCKET/$SNAPSHOT_KEY"
    aws s3 cp "$TMP_FILE" "s3://$BUCKET/$SNAPSHOT_KEY" --region "$REGION" --no-cli-pager
    echo "    Snapshot saved. Reuse with: --from ${SNAPSHOT_NAME}"
    LOAD_KEY="$SNAPSHOT_KEY"
  else
    # Transient dump — upload, load, delete
    LOAD_KEY="db-dumps/transient-$(date +%Y%m%d-%H%M%S).sql.gz"
    echo "==> Uploading transient dump → s3://$BUCKET/$LOAD_KEY"
    aws s3 cp "$TMP_FILE" "s3://$BUCKET/$LOAD_KEY" --region "$REGION" --no-cli-pager
  fi

  rm -f "$TMP_FILE"
fi

echo "==> Invoking loader Lambda (this may take 1-2 min for large dumps)..."
aws lambda invoke \
  --function-name "$LOADER_FN" \
  --region "$REGION" \
  --cli-binary-format raw-in-base64-out \
  --payload "{\"bucket\":\"$BUCKET\",\"key\":\"$LOAD_KEY\"}" \
  --no-cli-pager \
  /tmp/loader-response.json

echo ""
cat /tmp/loader-response.json
echo ""

# Check for Lambda-level error
if grep -q '"errorMessage"' /tmp/loader-response.json; then
  echo "ERROR: Lambda reported an error (see above)"
  # Clean up transient dump even on failure
  [[ -z "$SNAPSHOT_NAME" && -z "$FROM_SNAPSHOT" ]] && \
    aws s3 rm "s3://$BUCKET/$LOAD_KEY" --region "$REGION" --no-cli-pager 2>/dev/null || true
  exit 1
fi

# Clean up transient dump (snapshots are kept)
if [[ -z "$SNAPSHOT_NAME" && -z "$FROM_SNAPSHOT" ]]; then
  echo "==> Cleaning up transient dump from S3..."
  aws s3 rm "s3://$BUCKET/$LOAD_KEY" --region "$REGION" --no-cli-pager
fi

echo "==> Done! ${STAGE} Aurora is loaded."
if [[ -n "$SNAPSHOT_NAME" ]]; then
  echo "    To load this snapshot into another env:"
  echo "    bash scripts/dev/push-to-staging.sh --stage prod --from ${SNAPSHOT_NAME}"
fi
