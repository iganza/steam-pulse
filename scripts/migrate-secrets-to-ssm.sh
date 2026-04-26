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
#
# Bash 3.x compatible (no associative arrays — macOS default bash works).

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

# Per-env legacy paths. Convention: leading slash. The env files have some
# entries WITHOUT leading slash that point to the wrong (duplicate/stale)
# secrets — DO NOT source from those. Always read the leading-slash version.
# Staging anthropic preserves the existing 'anthropic-apikey' name (no hyphen).
legacy_path() {
    case "$1:$ENV" in
        steam:production)     echo "/steampulse/production/steam-api-key" ;;
        anthropic:production) echo "/steampulse/production/anthropic-api-key" ;;
        resend:production)    echo "/steampulse/production/resend-api-key" ;;
        db:production)        echo "/steampulse/production/db-credentials" ;;
        steam:staging)        echo "/steampulse/staging/steam-api-key" ;;
        anthropic:staging)    echo "/steampulse/staging/anthropic-apikey" ;;
        resend:staging)       echo "/steampulse/staging/resend-api-key" ;;
        db:staging)           echo "/steampulse/staging/db-credentials" ;;
        *) echo "unknown legacy key: $1:$ENV" >&2; exit 1 ;;
    esac
}

# New SSM SecureString params (consistent /steampulse/{env}/api-keys/{short} + /steampulse/{env}/db-password).
new_param() {
    case "$1" in
        steam)     echo "/steampulse/${ENV}/api-keys/steam" ;;
        anthropic) echo "/steampulse/${ENV}/api-keys/anthropic" ;;
        resend)    echo "/steampulse/${ENV}/api-keys/resend" ;;
        db)        echo "/steampulse/${ENV}/db-password" ;;
        *) echo "unknown new key: $1" >&2; exit 1 ;;
    esac
}

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Backfill SSM SecureString ← Secrets Manager (${ENV})"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

verify_match() {
    # Compare two values via shell vars — `$()` strips trailing newlines uniformly,
    # avoiding spurious mismatches from `aws --output text` adding a trailing \n.
    local expected="$1" param_name="$2"
    local actual
    actual=$(aws ssm get-parameter --name "$param_name" --with-decryption \
                 --query 'Parameter.Value' --output text)
    if [[ "$expected" == "$actual" ]]; then
        echo "  ✅ OK"
        return 0
    fi
    echo "  ❌ MISMATCH after write (expected ${#expected} bytes, got ${#actual})" >&2
    return 1
}

migrate_plain() {
    local short="$1"
    local legacy new value
    legacy=$(legacy_path "$short")
    new=$(new_param "$short")
    echo "▶ ${short}: ${legacy} → ${new}"

    value=$(aws secretsmanager get-secret-value \
        --secret-id "$legacy" \
        --query 'SecretString' --output text)

    if [[ "$value" == "{"* ]]; then
        echo "  ❌ legacy SecretString is JSON-shaped — use migrate_json instead" >&2
        unset value
        exit 1
    fi

    aws ssm put-parameter \
        --name "$new" \
        --type SecureString \
        --value "$value" \
        --overwrite >/dev/null

    verify_match "$value" "$new" || { unset value; exit 1; }
    unset value
}

# Extract one field from a JSON-shaped SecretString and write it to a SecureString.
# Args: <short-key> <json-field-name>
migrate_json() {
    local short="$1" field="$2"
    local legacy new raw value
    legacy=$(legacy_path "$short")
    new=$(new_param "$short")
    echo "▶ ${short}: ${legacy}.${field} → ${new}"

    raw=$(aws secretsmanager get-secret-value \
        --secret-id "$legacy" \
        --query 'SecretString' --output text)
    value=$(printf '%s' "$raw" | python3 -c "
import json, sys
data = json.load(sys.stdin)
if '$field' not in data:
    print('missing field $field; available:', list(data.keys()), file=sys.stderr)
    sys.exit(1)
print(data['$field'], end='')
")
    unset raw

    aws ssm put-parameter \
        --name "$new" \
        --type SecureString \
        --value "$value" \
        --overwrite >/dev/null

    verify_match "$value" "$new" || { unset value; exit 1; }
    unset value
}

migrate_plain steam
migrate_plain anthropic
migrate_json resend api_key
migrate_json db password

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ All 4 SecureString params verified for ${ENV}."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
