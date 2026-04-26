#!/usr/bin/env bash
# Force-delete remaining legacy API-key secrets in Secrets Manager (no recovery window).
# Run only AFTER the SSM SecureString migration has deployed and been verified end-to-end.
#
# CRITICAL: do NOT delete `steampulse/{env}/db-credentials` (no leading slash) —
# that is the CANONICAL DB secret in active use:
#   - .env.production:DB_SECRET_NAME points here
#   - infra/stacks/data_stack.py wires the RDS Master Password from here
#   - library_layer/utils/db.py:get_db_url reads full {username,password,host,port,dbname} JSON
# The DB-secret migration is T4/T5; until then this stays.
#
# This script targets the duplicates only:
#   - leading-slash db-credentials (duplicate; never read)
#   - no-slash steam-api-key / resend-api-key (duplicates; T2 Lambdas no longer read them)
#
# Usage:
#   bash scripts/delete-legacy-secrets.sh --env production
#   bash scripts/delete-legacy-secrets.sh --env staging

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

# Duplicates safe to delete in T3.
# Skips: `steampulse/{env}/db-credentials` (canonical, in active use until T4).
TARGETS=()
if [[ "$ENV" == "production" ]]; then
    TARGETS=(
        "/steampulse/production/db-credentials"
        "steampulse/production/steam-api-key"
        "steampulse/production/resend-api-key"
    )
else
    TARGETS=(
        "/steampulse/staging/db-credentials"
        "steampulse/staging/steam-api-key"
        "steampulse/staging/resend-api-key"
    )
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ⚠️  FORCE DELETE legacy API-key secrets (${ENV})"
echo "  No recovery window — these vanish immediately."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
for t in "${TARGETS[@]}"; do
    echo "  - $t"
done
echo ""
read -r -p "Type FORCE-DELETE to continue: " CONFIRM
if [[ "$CONFIRM" != "FORCE-DELETE" ]]; then
    echo "Aborted." >&2
    exit 1
fi

for t in "${TARGETS[@]}"; do
    echo "▶ deleting $t"
    aws secretsmanager delete-secret \
        --secret-id "$t" \
        --force-delete-without-recovery >/dev/null
    echo "  ✅ gone"
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ All ${#TARGETS[@]} legacy API-key secrets force-deleted for ${ENV}."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
