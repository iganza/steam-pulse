#!/usr/bin/env bash
# Push local Postgres DB to staging Aurora via S3 + loader Lambda.
# Usage: bash scripts/dev/push-to-staging.sh [stage]
#
# Requires: pg_dump, aws cli, psql (for local dump only)

set -euo pipefail

STAGE="${1:-staging}"
LOCAL_DB="postgresql://steampulse:dev@127.0.0.1:5432/steampulse"
REGION="us-west-2"

echo "==> Fetching staging resources..."
BUCKET=$(aws cloudformation list-stack-resources \
  --stack-name "SteamPulse-${STAGE^}-App" \
  --region "$REGION" --no-cli-pager \
  --query 'StackResourceSummaries[?LogicalResourceId==`StaticAssetsBucket`].PhysicalResourceId' \
  --output text)

LOADER_FN=$(aws cloudformation list-stack-resources \
  --stack-name "SteamPulse-${STAGE^}-App" \
  --region "$REGION" --no-cli-pager \
  --query 'StackResourceSummaries[?LogicalResourceId==`DbLoaderFn`].PhysicalResourceId' \
  --output text)

echo "    Bucket : $BUCKET"
echo "    Lambda : $LOADER_FN"

DUMP_KEY="db-dumps/local-$(date +%Y%m%d-%H%M%S).sql.gz"
TMP_FILE="/tmp/steampulse-dump.sql.gz"

echo "==> Dumping local DB..."
pg_dump "$LOCAL_DB" \
  --no-owner --no-acl \
  --exclude-table=rate_limits \
  | gzip > "$TMP_FILE"

echo "==> Uploading to s3://$BUCKET/$DUMP_KEY..."
aws s3 cp "$TMP_FILE" "s3://$BUCKET/$DUMP_KEY" --region "$REGION"
rm "$TMP_FILE"

echo "==> Invoking loader Lambda..."
RESULT=$(aws lambda invoke \
  --function-name "$LOADER_FN" \
  --region "$REGION" \
  --cli-binary-format raw-in-base64-out \
  --payload "{\"bucket\":\"$BUCKET\",\"key\":\"$DUMP_KEY\"}" \
  --no-cli-pager \
  /tmp/loader-response.json 2>&1)

cat /tmp/loader-response.json
echo ""

# Cleanup dump from S3
echo "==> Cleaning up S3..."
aws s3 rm "s3://$BUCKET/$DUMP_KEY" --region "$REGION"

echo "==> Done! Local DB is now in staging Aurora."
