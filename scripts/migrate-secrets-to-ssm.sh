#!/usr/bin/env bash
# Backfill SSM SecureString params from existing Secrets Manager secrets.
# Idempotent (uses --overwrite). Verifies byte-for-byte after each write.
#
# Usage:
#   bash scripts/migrate-secrets-to-ssm.sh --env production
#   bash scripts/migrate-secrets-to-ssm.sh --env staging
#
# Prerequisites:
#   - AWS credentials configured for the target env
#   - AWS_REGION set (or AWS_DEFAULT_REGION) — secrets live in the primary region
#   - python3 on PATH (used to extract the password field from db-credentials JSON)

set -euo pipefail

ENV=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --env)
            ENV="$2"
            shift 2
            ;;
        *)
            echo "Unknown arg: $1" >&2
            exit 2
            ;;
    esac
done

if [[ "$ENV" != "production" && "$ENV" != "staging" ]]; then
    echo "Usage: $0 --env {production|staging}" >&2
    exit 2
fi

# Per-env legacy paths (some have leading slash, some don't; staging has 'anthropic-apikey' typo).
declare -A LEGACY
if [[ "$ENV" == "production" ]]; then
    LEGACY[steam]="steampulse/production/steam-api-key"
    LEGACY[anthropic]="/steampulse/production/anthropic-api-key"
    LEGACY[resend]="steampulse/production/resend-api-key"
    LEGACY[db]="steampulse/production/db-credentials"
else
    LEGACY[steam]="steampulse/staging/steam-api-key"
    LEGACY[anthropic]="/steampulse/staging/anthropic-apikey"
    LEGACY[resend]="steampulse/staging/resend-api-key"
    LEGACY[db]="steampulse/staging/db-credentials"
fi

# New SSM SecureString params (consistent /steampulse/{env}/api-keys/{short} + /steampulse/{env}/db-password).
declare -A NEW_PARAM
NEW_PARAM[steam]="/steampulse/${ENV}/api-keys/steam"
NEW_PARAM[anthropic]="/steampulse/${ENV}/api-keys/anthropic"
NEW_PARAM[resend]="/steampulse/${ENV}/api-keys/resend"
NEW_PARAM[db]="/steampulse/${ENV}/db-password"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Backfill SSM SecureString ← Secrets Manager (${ENV})"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

migrate_plain() {
    local short="$1"
    local legacy="${LEGACY[$short]}"
    local new="${NEW_PARAM[$short]}"
    echo "▶ ${short}: ${legacy} → ${new}"

    local value
    value=$(aws secretsmanager get-secret-value \
        --secret-id "$legacy" \
        --query 'SecretString' --output text)

    if [[ "$value" == "{"* ]]; then
        echo "  ❌ legacy SecretString is JSON-shaped — adjust the script to extract the right field" >&2
        unset value
        exit 1
    fi

    aws ssm put-parameter \
        --name "$new" \
        --type SecureString \
        --value "$value" \
        --overwrite >/dev/null

    if diff <(printf '%s' "$value") \
            <(aws ssm get-parameter --name "$new" --with-decryption \
                  --query 'Parameter.Value' --output text) >/dev/null; then
        echo "  ✅ OK"
    else
        echo "  ❌ MISMATCH after write" >&2
        unset value
        exit 1
    fi
    unset value
}

migrate_db_password() {
    local legacy="${LEGACY[db]}"
    local new="${NEW_PARAM[db]}"
    echo "▶ db-password: ${legacy}.password → ${new}"

    local raw value
    raw=$(aws secretsmanager get-secret-value \
        --secret-id "$legacy" \
        --query 'SecretString' --output text)
    value=$(printf '%s' "$raw" | python3 -c "import json,sys; print(json.load(sys.stdin)['password'], end='')")
    unset raw

    aws ssm put-parameter \
        --name "$new" \
        --type SecureString \
        --value "$value" \
        --overwrite >/dev/null

    if diff <(printf '%s' "$value") \
            <(aws ssm get-parameter --name "$new" --with-decryption \
                  --query 'Parameter.Value' --output text) >/dev/null; then
        echo "  ✅ OK"
    else
        echo "  ❌ MISMATCH after write" >&2
        unset value
        exit 1
    fi
    unset value
}

migrate_plain steam
migrate_plain anthropic
migrate_plain resend
migrate_db_password

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ All 4 SecureString params verified for ${ENV}."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
