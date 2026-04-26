# Secrets Manager consolidation

## Context

After `cost-trim-round-4.md` shipped, run-rate cut by ~$42/mo. The next visible knob in the long tail is **AWS Secrets Manager**: each secret is **$0.40/month + $0.05 per 10k API calls**, and we currently maintain **4 separate secrets** in production.

Today's secrets (per-environment, all imported via `Secret.from_secret_name_v2`, all created and rotated outside CDK):

| SSM/Secret name | Use | CDK reference |
|---|---|---|
| `/steampulse/{env}/db-credentials` | RDS password (multi-field JSON) | `infra/stacks/data_stack.py:60` |
| `/steampulse/{env}/steam-api-key` | Steam Web API key | `infra/stacks/compute_stack.py:390` |
| `/steampulse/{env}/anthropic-api-key` | Anthropic Console API key | `infra/stacks/compute_stack.py:114`, `infra/stacks/batch_analysis_stack.py:95` |
| `/steampulse/{env}/resend-api-key` (`config.RESEND_API_KEY_SECRET_NAME`) | Resend transactional email key | `infra/stacks/compute_stack.py:902` |

That's **$0.40 × 4 × 2 envs (production + staging) = $3.20/month** on the secret line, plus a few cents in API calls. Trivial in absolute terms but **80% of it is structural overhead**, not value.

## Goal

Collapse the three plain-string keys (Steam, Anthropic, Resend) into a single per-environment **bundled JSON secret** at `/steampulse/{env}/api-keys`, while keeping `db-credentials` separate (RDS managed rotation expects the bundled JSON shape it generates — don't disturb).

After: 2 secrets per env × 2 envs = **4 secrets total** (down from 8). Saves **$1.60/month**, plus reduces blast radius — one rotation tool path covers Steam + Anthropic + Resend.

## Tier 1 — Bundled secret schema

### T1-A. Define the JSON shape

Target shape for `/steampulse/{env}/api-keys`:

```json
{
  "steam_api_key": "ABCD...",
  "anthropic_api_key": "sk-ant-...",
  "resend_api_key": "re_..."
}
```

Each field is a non-empty string. No optional fields — pre-launch we always have all three.

### T1-B. Manual: provision the new secrets `[manual]`

Per environment, the user creates the bundled secret manually (Claude does not run AWS write APIs):

```bash
# production
aws secretsmanager create-secret \
  --name /steampulse/production/api-keys \
  --secret-string '{"steam_api_key":"...","anthropic_api_key":"...","resend_api_key":"..."}'

# staging
aws secretsmanager create-secret \
  --name /steampulse/staging/api-keys \
  --secret-string '{"steam_api_key":"...","anthropic_api_key":"...","resend_api_key":"..."}'
```

Backfill values from the existing 3 secrets before flipping code.

## Tier 2 — Code migration

### T2-A. Add a single resolver in the library layer

New module `src/library-layer/library_layer/utils/api_keys.py`:

```python
"""Resolve Steam / Anthropic / Resend API keys from one bundled secret."""

from functools import lru_cache

from aws_lambda_powertools.utilities.parameters import get_secret
from pydantic import BaseModel, Field

from library_layer.config import SteamPulseConfig


class ApiKeys(BaseModel):
    steam_api_key: str = Field(min_length=1)
    anthropic_api_key: str = Field(min_length=1)
    resend_api_key: str = Field(min_length=1)


@lru_cache(maxsize=1)
def get_api_keys(config: SteamPulseConfig) -> ApiKeys:
    """Single-cached fetch of the per-env bundled api-keys secret."""
    raw = get_secret(config.API_KEYS_SECRET_NAME)
    return ApiKeys.model_validate_json(raw)
```

### T2-B. Add config field

`src/library-layer/library_layer/config.py` — add:

```python
API_KEYS_SECRET_NAME: str = ""  # e.g. "/steampulse/production/api-keys"
```

Wire it through `.env.production`, `.env.staging`, `.env.example`, and `tests/conftest.py` defaults.

### T2-C. Migrate every callsite

Find each direct `get_secret_value(SecretId=...)` or `get_secret(...)` call referencing the three legacy secret names and replace with `get_api_keys(config).{steam_api_key|anthropic_api_key|resend_api_key}`.

Known sites (verify with `Grep STEAM_API_KEY_SECRET_NAME ANTHROPIC_API_KEY_SECRET_NAME RESEND_API_KEY_SECRET_NAME` before editing):

- `src/lambda-functions/lambda_functions/crawler/handler.py` — Steam key (Secrets Manager `get_secret_value` at cold start)
- `src/lambda-functions/lambda_functions/crawler/spoke_handler.py` — Steam key (cross-region SM client)
- `src/library-layer/library_layer/llm/__init__.py` — `resolve_anthropic_api_key`
- `src/lambda-functions/lambda_functions/email/handler.py` — Resend key

**Spoke wrinkle:** `spoke_handler.py` builds a **regional** Secrets Manager client targeted at the primary region (cross-region read). The bundled secret must live in the primary region (us-west-2) and the spoke cross-region read continues to point there. No code-level region change.

### T2-D. Update CDK to grant read on the bundled secret

`infra/stacks/compute_stack.py`, `infra/stacks/batch_analysis_stack.py`, `infra/stacks/spoke_stack.py`:
- Drop the three individual `Secret.from_secret_name_v2(...)` imports.
- Add one bundled `api_keys_secret = Secret.from_secret_name_v2(self, "ApiKeysSecret", config.API_KEYS_SECRET_NAME)`.
- Replace each `<old_secret>.grant_read(<role>)` with `api_keys_secret.grant_read(<role>)`.
- Keep `db_credentials_secret` untouched.

## Tier 3 — Deprecate the legacy secrets

After T2 ships and one full crawler/analysis cycle has succeeded against the bundled secret in production:

### T3-A. Remove old grants from CDK `[code]`

Drop the three legacy `Secret.from_secret_name_v2(...)` references entirely. CDK diff should show only IAM policy changes.

### T3-B. Manual: delete the old secrets `[manual]`

Per env, after a 7-day soak:

```bash
for s in steam-api-key anthropic-api-key resend-api-key; do
  aws secretsmanager delete-secret \
    --secret-id /steampulse/production/$s \
    --recovery-window-in-days 7
done
# repeat for /steampulse/staging/
```

The 7-day recovery window means an accidental deletion can be undone (`restore-secret`).

## Tier 4 — Optional: bundle DB credentials too?

Skip. RDS managed rotation expects the AWS-generated 6-field JSON layout (`username`, `password`, `engine`, `host`, `port`, `dbname`). Repackaging it would break rotation. Leave `db-credentials` alone.

## Verification

```bash
# 1. New secret is readable
aws secretsmanager get-secret-value \
  --secret-id /steampulse/production/api-keys \
  --query 'SecretString' --output text \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(sorted(d.keys()))"
# expect: ['anthropic_api_key', 'resend_api_key', 'steam_api_key']

# 2. Old secrets still exist during T2 deploy (rollback safety)
aws secretsmanager describe-secret --secret-id /steampulse/production/steam-api-key

# 3. After T3-B: old secrets scheduled for deletion
aws secretsmanager describe-secret --secret-id /steampulse/production/steam-api-key \
  --query 'DeletedDate'  # non-null = scheduled
```

End-to-end functional check: trigger one realtime analysis, one crawl, and one waitlist email after T2 deploy. All three must succeed without falling back to the old secrets.

## Out of scope

- Anthropic Console rotation tooling — no automation today; rotate manually when the bundled secret rolls.
- KMS CMK on the bundled secret — default AWS-managed key is fine for $5/mo of value.
- Cross-region replication of the bundled secret — spoke regions already cross-region read from us-west-2; no need to replicate.

## Critical files

- `src/library-layer/library_layer/utils/api_keys.py` — NEW (resolver + Pydantic model)
- `src/library-layer/library_layer/config.py` — add `API_KEYS_SECRET_NAME`
- `.env.production`, `.env.staging`, `.env.example`, `tests/conftest.py` — add `API_KEYS_SECRET_NAME`
- `src/lambda-functions/lambda_functions/crawler/handler.py` — switch Steam key resolver
- `src/lambda-functions/lambda_functions/crawler/spoke_handler.py` — switch Steam key resolver
- `src/library-layer/library_layer/llm/__init__.py` — switch `resolve_anthropic_api_key`
- `src/lambda-functions/lambda_functions/email/handler.py` — switch Resend key resolver
- `infra/stacks/compute_stack.py` — replace 3 secret imports with 1 bundled
- `infra/stacks/batch_analysis_stack.py` — replace Anthropic secret with bundled
- `infra/stacks/spoke_stack.py` — replace Steam secret with bundled

## Savings

**~$1.60/month** + simpler rotation surface + one fewer config knob to forget.
