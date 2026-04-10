#!/usr/bin/env bash
# Invalidate the CloudFront distribution for a given environment.
#
# Usage:
#   bash scripts/invalidate-cdn.sh --env production           # invalidate everything
#   bash scripts/invalidate-cdn.sh --env production --paths "/new-releases"
#   bash scripts/invalidate-cdn.sh --env staging --paths "/games/*" "/trending"
#
set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-us-west-2}"
ENV=""
PATHS=("/*")  # default: full invalidation

while [[ $# -gt 0 ]]; do
    case "$1" in
        --env)   ENV="$2"; shift 2 ;;
        --paths) shift; PATHS=(); while [[ $# -gt 0 && "$1" != --* ]]; do PATHS+=("$1"); shift; done ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

if [[ -z "$ENV" ]]; then
    echo "Usage: bash scripts/invalidate-cdn.sh --env staging|production [--paths /path1 /path2]"
    exit 1
fi

echo "▶ Looking up CloudFront distribution for ${ENV}..."
DIST_ID=$(aws ssm get-parameter \
    --name "/steampulse/${ENV}/delivery/distribution-id" \
    --region "$REGION" \
    --query 'Parameter.Value' \
    --output text 2>/dev/null || true)

if [[ -z "$DIST_ID" ]]; then
    echo "✗ SSM param /steampulse/${ENV}/delivery/distribution-id not found."
    echo "  Is the delivery stack deployed for ${ENV}?"
    exit 1
fi

echo "✓ Distribution: ${DIST_ID}"
echo "▶ Invalidating paths: ${PATHS[*]}"

INVALIDATION_ID=$(aws cloudfront create-invalidation \
    --distribution-id "$DIST_ID" \
    --paths "${PATHS[@]}" \
    --query 'Invalidation.Id' \
    --output text)

echo "✓ Invalidation created: ${INVALIDATION_ID}"
echo "  Propagates in ~30-60 seconds."
echo ""
echo "  To watch progress:"
echo "  aws cloudfront get-invalidation --distribution-id ${DIST_ID} --id ${INVALIDATION_ID}"
