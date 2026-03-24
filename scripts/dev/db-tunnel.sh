#!/usr/bin/env bash
# Open an SSM port-forward tunnel to Aurora via the fck-nat EC2 instance.
# No SSH keys, no open ports — uses AWS Systems Manager Session Manager.
#
# Usage:
#   bash scripts/dev/db-tunnel.sh                  # tunnel staging Aurora → localhost:5433
#   bash scripts/dev/db-tunnel.sh --stage prod      # tunnel production Aurora → localhost:5433
#   bash scripts/dev/db-tunnel.sh --port 5434       # use a different local port
#
# Then in another terminal:
#   psql "host=localhost port=5433 dbname=staging_steampulse user=postgres sslmode=verify-full sslrootcert=./global-bundle.pem"
#
# Requires: aws cli, session-manager-plugin
#   brew install --cask session-manager-plugin

set -euo pipefail

STAGE="staging"
LOCAL_PORT="5433"
REGION="us-west-2"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stage) STAGE="$2"; shift 2 ;;
    --port)  LOCAL_PORT="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

case "$STAGE" in
  prod)               STAGE="production" ;;
  staging|production) ;;
  *) echo "ERROR: --stage must be staging or production (got: $STAGE)"; exit 1 ;;
esac

STAGE_CAP="$(python3 -c "print('$STAGE'.capitalize())")"

echo "==> Looking up resources for $STAGE..."

# Get Aurora writer endpoint from CloudFormation
RDS_HOST=$(aws cloudformation describe-stacks \
  --stack-name "SteamPulse-${STAGE_CAP}-Data" \
  --region "$REGION" --no-cli-pager \
  --query 'Stacks[0].Outputs[?OutputKey==`DbWriterEndpoint`].OutputValue' \
  --output text 2>/dev/null)

if [[ -z "$RDS_HOST" ]]; then
  # Fallback: look it up from RDS directly
  RDS_HOST=$(aws rds describe-db-clusters \
    --region "$REGION" --no-cli-pager \
    --query "DBClusters[?contains(DBClusterIdentifier, 'steampulse') && contains(DBClusterIdentifier, '$STAGE')].Endpoint" \
    --output text 2>/dev/null | head -1)
fi

if [[ -z "$RDS_HOST" ]]; then
  echo "ERROR: Could not find Aurora endpoint for $STAGE. Check CloudFormation outputs."
  exit 1
fi

# Get the NAT instance ID (the SSM-managed fck-nat instance in the VPC)
NAT_INSTANCE=$(aws ec2 describe-instances \
  --region "$REGION" --no-cli-pager \
  --filters \
    "Name=instance-state-name,Values=running" \
    "Name=tag:Name,Values=*${STAGE_CAP}*PublicSubnet*" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text 2>/dev/null)

if [[ -z "$NAT_INSTANCE" || "$NAT_INSTANCE" == "None" ]]; then
  echo "ERROR: Could not find running NAT instance for $STAGE."
  exit 1
fi

echo "    Aurora  : $RDS_HOST"
echo "    NAT EC2 : $NAT_INSTANCE"
echo "    Tunnel  : localhost:$LOCAL_PORT → $RDS_HOST:5432"
echo ""
echo "==> Opening SSM tunnel (Ctrl+C to close)..."
echo "    Connect: psql \"host=localhost port=$LOCAL_PORT dbname=${STAGE}_steampulse user=postgres sslmode=verify-full sslrootcert=./global-bundle.pem\""
echo ""

aws ssm start-session \
  --target "$NAT_INSTANCE" \
  --region "$REGION" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"$RDS_HOST\"],\"portNumber\":[\"5432\"],\"localPortNumber\":[\"$LOCAL_PORT\"]}"
