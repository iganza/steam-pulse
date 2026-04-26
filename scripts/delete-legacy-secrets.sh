#!/usr/bin/env bash
# Force-delete the 3 legacy API-key secrets in Secrets Manager (no recovery window).
# Run only AFTER the SSM SecureString migration has deployed and been verified end-to-end.
# Skips db-credentials — that goes with the T4/T5 DB-credentials migration.
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

# Per-env legacy paths. Convention: leading slash. The no-leading-slash
# duplicates (if any still exist) are wrong and not deleted by this script.
TARGETS=()
if [[ "$ENV" == "production" ]]; then
    TARGETS=(
        "/steampulse/production/steam-api-key"
        "/steampulse/production/anthropic-api-key"
        "/steampulse/production/resend-api-key"
    )
else
    TARGETS=(
        "/steampulse/staging/steam-api-key"
        "/steampulse/staging/anthropic-apikey"
        "/steampulse/staging/resend-api-key"
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
