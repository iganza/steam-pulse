#!/usr/bin/env bash
# Push local Postgres DB to a target Aurora environment.
#
# Two load methods:
#   --psql   Stream directly via psql over SSM tunnel (requires tunnel open on port 5433)
#   (default) Invoke loader Lambda via S3 upload
#
# Usage:
#   bash scripts/dev/push-to-staging.sh                        # dump local → staging via Lambda
#   bash scripts/dev/push-to-staging.sh --psql                 # dump local → staging via psql tunnel
#   bash scripts/dev/push-to-staging.sh --save seed-v1         # dump local → staging + save named snapshot
#   bash scripts/dev/push-to-staging.sh --from seed-v1         # load existing snapshot → staging
#   bash scripts/dev/push-to-staging.sh --from seed-v1 --psql  # load snapshot via psql tunnel
#   bash scripts/dev/push-to-staging.sh --list                 # list available snapshots
#   bash scripts/dev/push-to-staging.sh --stage prod --from seed-v1  # promote snapshot to prod
#
# Requires: docker compose, aws cli
# For --psql: SSM tunnel must be open (run scripts/dev/db-tunnel.sh first)

set -euo pipefail

STAGE="staging"
SNAPSHOT_NAME=""
FROM_SNAPSHOT=""
LIST_ONLY=false
USE_PSQL=false
REGION="us-west-2"
LOCAL_PORT="5433"

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --stage)    STAGE="$2";          shift 2 ;;
    --save)     SNAPSHOT_NAME="$2";  shift 2 ;;
    --from)     FROM_SNAPSHOT="$2";  shift 2 ;;
    --list)     LIST_ONLY=true;      shift   ;;
    --psql)     USE_PSQL=true;       shift   ;;
    --port)     LOCAL_PORT="$2";     shift 2 ;;
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

STAGE_CAP="$(python3 -c "print('$STAGE'.capitalize())")"
# Bucket name is deterministic — no CloudFormation lookup needed.
BUCKET="steampulse-assets-${STAGE}"
DB_NAME="${STAGE}_steampulse"

# --list: show available snapshots and exit
if [[ "$LIST_ONLY" == true ]]; then
  echo "Available snapshots in s3://$BUCKET/db-snapshots/:"
  aws s3 ls "s3://$BUCKET/db-snapshots/" --region "$REGION" --no-cli-pager | awk '{print $3, $4}'
  exit 0
fi

echo "==> Fetching ${STAGE} resources..."
echo "    Bucket : $BUCKET"

TMP_FILE="/tmp/steampulse-dump.sql.gz"

if [[ -n "$FROM_SNAPSHOT" ]]; then
  # Load from an existing named snapshot — download if using psql, reference by key if using Lambda
  LOAD_KEY="db-snapshots/${FROM_SNAPSHOT}.sql.gz"
  if ! aws s3 ls "s3://$BUCKET/$LOAD_KEY" --region "$REGION" --no-cli-pager &>/dev/null; then
    echo "ERROR: Snapshot not found. Run --list to see available snapshots."
    exit 1
  fi
  if [[ "$USE_PSQL" == true ]]; then
    echo "==> Downloading snapshot from S3..."
    aws s3 cp "s3://$BUCKET/$LOAD_KEY" "$TMP_FILE" --region "$REGION" --no-cli-pager
  fi
else
  # Dump local DB — run pg_dump inside the Docker container to avoid version mismatch
  echo "==> Dumping local DB..."
  docker compose exec -T db pg_dump \
    "postgresql://steampulse:dev@localhost/steampulse" \
    --no-owner --no-acl --clean --if-exists \
    --exclude-table=rate_limits \
    | gzip > "$TMP_FILE"

  if [[ -n "$SNAPSHOT_NAME" ]]; then
    LOAD_KEY="db-snapshots/${SNAPSHOT_NAME}.sql.gz"
    echo "==> Saving snapshot → s3://$BUCKET/$LOAD_KEY"
    aws s3 cp "$TMP_FILE" "s3://$BUCKET/$LOAD_KEY" --region "$REGION" --no-cli-pager
    echo "    Snapshot saved. Reuse with: --from ${SNAPSHOT_NAME}"
  else
    LOAD_KEY="db-dumps/transient-$(date +%Y%m%d-%H%M%S).sql.gz"
    if [[ "$USE_PSQL" == false ]]; then
      echo "==> Uploading transient dump → s3://$BUCKET/$LOAD_KEY"
      aws s3 cp "$TMP_FILE" "s3://$BUCKET/$LOAD_KEY" --region "$REGION" --no-cli-pager
    fi
  fi
fi

if [[ "$USE_PSQL" == true ]]; then
  # ── psql path: stream directly over SSM tunnel ─────────────────────────────
  echo "==> Fetching DB password from Secrets Manager..."
  PGPASSWORD=$(aws secretsmanager get-secret-value \
    --secret-id "steampulse/${STAGE}/db-credentials" \
    --region "$REGION" --query 'SecretString' --output text \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['password'])")
  export PGPASSWORD

  echo "==> Loading via psql tunnel (localhost:${LOCAL_PORT})..."
  echo "    (SSM tunnel must be open — run scripts/dev/db-tunnel.sh first)"
  gunzip -c "$TMP_FILE" | /opt/homebrew/opt/postgresql@16/bin/psql \
    "host=127.0.0.1 port=${LOCAL_PORT} dbname=${DB_NAME} user=postgres sslmode=require"

  rm -f "$TMP_FILE"
  echo "==> Done! ${STAGE} Aurora is loaded."
else
  # ── Lambda path: S3 upload → invoke loader Lambda ──────────────────────────
  LOADER_FN=$(aws cloudformation list-stack-resources \
    --stack-name "SteamPulse-${STAGE_CAP}-Compute" \
    --region "$REGION" --no-cli-pager \
    --query 'StackResourceSummaries[?starts_with(LogicalResourceId, `DbLoaderFn`) && ResourceType == `AWS::Lambda::Function`].PhysicalResourceId | [0]' \
    --output text)

  if [[ -z "$LOADER_FN" || "$LOADER_FN" == "None" ]]; then
    echo "ERROR: DbLoaderFn not found in SteamPulse-${STAGE_CAP}-Compute stack"
    exit 1
  fi
  echo "    Lambda : $LOADER_FN"

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

  if grep -q '"errorMessage"' /tmp/loader-response.json; then
    echo "ERROR: Lambda reported an error (see above)"
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
fi
