#!/usr/bin/env bash
# Bootstrap CDK in all spoke regions (plus us-east-1 for ACM cross-region certs).
#
# Usage:
#   bash scripts/bootstrap-regions.sh
#
# Prerequisites:
#   - AWS credentials configured (aws sso login or env vars)
#   - Poetry installed

set -euo pipefail

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGIONS=(
    us-west-2
    us-east-1
    us-east-2
    ca-central-1
    eu-west-1
    eu-central-1
    eu-north-1
    ap-south-1
    ap-southeast-1
    ap-northeast-1
    ap-northeast-2
    ap-southeast-2
)

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  CDK bootstrap → account $ACCOUNT"
echo "  Regions: ${#REGIONS[@]}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

FAILED=()

for region in "${REGIONS[@]}"; do
    echo "▶ Bootstrapping $region ..."
    if poetry run cdk bootstrap "aws://$ACCOUNT/$region" --quiet; then
        echo "  ✅ $region done"
    else
        echo "  ❌ $region FAILED"
        FAILED+=("$region")
    fi
    echo ""
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ ${#FAILED[@]} -eq 0 ]]; then
    echo "  ✅ All ${#REGIONS[@]} regions bootstrapped successfully."
else
    echo "  ❌ Failed regions: ${FAILED[*]}"
    exit 1
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
