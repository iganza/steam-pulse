# Retire the Secrets Manager DB secret (replace with two SSM SecureStrings)

## Context

After `secrets-consolidation.md` shipped (T2), all 3 API keys live in SSM SecureString. The only remaining Secrets Manager line item in production is `steampulse/production/db-credentials` — a JSON blob `{"username": "postgres", "password": "...", "host": "...", "port": 5432, "dbname": "production_steampulse"}` that:

1. **The application reads** at every Lambda cold start via `library_layer.utils.db.get_db_url()` (line 42), parsing all 5 fields to build the postgres URL.
2. **CDK references** in `infra/stacks/data_stack.py:60` via `Credentials.from_secret(db_secret)` to set the RDS instance's `MasterUserPassword` at deploy time. CFN resolves `{{resolve:secretsmanager:steampulse/production/db-credentials:SecretString:password}}` and passes the result to `ModifyDBInstance`.
3. **8 Lambda roles** grant `db_secret.grant_read(...)` (compute_stack.py: 7 sites, batch_analysis_stack.py: 1 site).
4. Costs ~**$0.40/mo** per env, and is the last item keeping `aws_cdk.aws_secretsmanager` alive in our CDK.

A previous attempt to fold this into the `secrets-consolidation` PR backed out for two reasons:
- We tried `Credentials.from_password(SecretValue.ssm_secure(DB_PASSWORD_PARAM_NAME))` against the existing SSM SecureString that holds the **full JSON blob**. CFN's `{{resolve:ssm-secure:NAME:VERSION}}` does not support JSON-field extraction (unlike `secretsmanager:NAME:SecretString:FIELD`), so it would set `MasterUserPassword` to the literal JSON string — locking out every connection.
- The L1 deletion-override alternative (strip `MasterUserPassword` from the synthesized template entirely) works mechanically but is a one-way door with no preview path other than `cdk diff`. Given the no-staging environment, the user opted for a more conservative split-param design.

## Goal

Eliminate the Secrets Manager DB secret. Net savings: ~$0.40/mo plus the ability to drop `aws_cdk.aws_secretsmanager` from CDK entirely (one fewer service surface).

The approach: **two SSM SecureStrings** with clean separation of concerns.

| Param | Holds | Read by |
|---|---|---|
| `/steampulse/{env}/db-password` | Full credentials JSON: `{"username","password","host","port","dbname"}` | Application (`db.py:get_db_url()`) |
| `/steampulse/{env}/db-master-password` (NEW) | Just the password string | CDK → CFN → `MasterUserPassword` on the RDS DBInstance |

The first param already exists from the previous prompt's T1 backfill. T1 below adds the second.

## Tier 1 — Provision the password-only SecureString `[manual]`

Operator extracts the password from the existing `/steampulse/{env}/db-password` JSON (or directly from the canonical Secrets Manager secret) and writes it as a plain SecureString.

```bash
for env in production; do  # add staging when/if it returns
  pw=$(aws ssm get-parameter \
         --name "/steampulse/${env}/db-password" \
         --with-decryption \
         --query 'Parameter.Value' --output text \
       | python3 -c "import json,sys; print(json.load(sys.stdin)['password'], end='')")

  aws ssm put-parameter \
    --name "/steampulse/${env}/db-master-password" \
    --type SecureString \
    --value "$pw" \
    --overwrite
  unset pw
done
```

**Verify byte-for-byte match against the live password** (the canonical Secrets Manager `password` field) before T2 ships. If they differ, CFN will issue `ModifyDBInstance` with a different `MasterUserPassword` at deploy time and reset the live RDS password — locking out every connection.

```bash
for env in production; do
  ssm_value=$(aws ssm get-parameter --name "/steampulse/${env}/db-master-password" \
                --with-decryption --query 'Parameter.Value' --output text)
  sm_value=$(aws secretsmanager get-secret-value \
               --secret-id "steampulse/${env}/db-credentials" \
               --query SecretString --output text \
             | python3 -c "import json,sys; print(json.load(sys.stdin)['password'], end='')")
  if [[ "$ssm_value" == "$sm_value" ]]; then echo "OK ${env}"; else echo "MISMATCH ${env}"; fi
  unset ssm_value sm_value
done
```

Expect `OK production`. Any `MISMATCH` blocks T2 — re-run the put-parameter against the canonical source.

> **Why this matters:** `Credentials.from_secret(db_secret)` resolves to the JSON `password` field, which is what RDS currently uses. The new SSM SecureString must hold that exact same string.

## Tier 2 — Switch the app to read DB creds from SSM `[code]`

`src/library-layer/library_layer/utils/db.py` — replace the boto3 secretsmanager call with PowerTools `get_parameter`. The SSM SecureString at `/steampulse/{env}/db-password` holds the same JSON shape, so the parsing stays identical.

```python
def get_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    param_name = os.getenv("DB_PASSWORD_PARAM_NAME")
    if param_name:
        from aws_lambda_powertools.utilities.parameters import get_parameter

        creds = json.loads(get_parameter(param_name, decrypt=True))
        return (
            f"postgresql://{creds['username']}:{creds['password']}"
            f"@{creds['host']}:{creds['port']}/{creds['dbname']}"
        )
    raise RuntimeError("No DATABASE_URL or DB_PASSWORD_PARAM_NAME configured")
```

**No CDK/IAM change needed for this step** — every Lambda role already has the `ssm:GetParameter` wildcard on `parameter/steampulse/{env}/*`, and the AWS-managed `aws/ssm` key has an implicit decrypt grant for principals with SSM read perms. (Verified during the original `secrets-consolidation` work.)

This change is a no-op until the env files actually point at the new flow — but `DB_PASSWORD_PARAM_NAME` is already wired in `.env.production` from the original `secrets-consolidation` PR. Effective immediately on deploy.

## Tier 3 — Switch RDS to source MasterUserPassword from SSM `[code]`

Add the new param name to `SteamPulseConfig`:

```python
DB_MASTER_PASSWORD_PARAM_NAME: str   # /steampulse/{env}/db-master-password
```

Wire it in all 5 env files (`.env.production`, `.env.staging`, `.env.example`, `.env`, `tests/conftest.py` `_TEST_ENV_DEFAULTS`). No defaults (matches the existing required-field pattern).

In `infra/stacks/data_stack.py`:

```python
# Production branch
db_instance = rds.DatabaseInstance(
    ...
    credentials=rds.Credentials.from_password(
        "postgres",
        cdk.SecretValue.ssm_secure(config.DB_MASTER_PASSWORD_PARAM_NAME),
    ),
    ...
)

# Staging branch (if/when staging returns) — same pattern
db_cluster = rds.DatabaseCluster(
    ...
    credentials=rds.Credentials.from_password(
        "postgres",
        cdk.SecretValue.ssm_secure(config.DB_MASTER_PASSWORD_PARAM_NAME),
    ),
    ...
)
```

Drop the `secret_name = f"steampulse/{env}/db-credentials"` line. Drop the staging `cfn_secret.override_logical_id(...)` block (the secret is gone). Drop `self.db_secret = ...` and the `import aws_cdk.aws_secretsmanager` import.

> **CFN behavior on the password swap:** CFN compares the resource template, which changes from `MasterUserPassword: {{resolve:secretsmanager:.../db-credentials:SecretString:password}}` to `{{resolve:ssm-secure:/steampulse/production/db-master-password:1}}`. The dynamic-reference token is textually different, so CFN issues `ModifyDBInstance` with the resolved value as the new password. **As long as T1's verify step shows `OK`, the resolved value matches what's already set on the instance, and `ModifyDBInstance` is functionally a no-op.**

## Tier 4 — Drop db_secret plumbing from consumer stacks `[code]`

Remove the `db_secret: secretsmanager.ISecret` constructor param + every `db_secret.grant_read(...)` call:

- **`infra/stacks/compute_stack.py`** — constructor param (line ~51) + 7 grant_read sites (Analysis L113, Api L203, Crawler L406, Admin L589, Migration L630, MatviewRefresh L643, DbLoader L868). Drop `import aws_cdk.aws_secretsmanager as secretsmanager` if no other consumer.
- **`infra/stacks/batch_analysis_stack.py`** — constructor param (line ~44) + 1 grant_read site (BatchLambda L99). Drop the secretsmanager import.
- **`infra/application_stage.py`** — drop `db_secret=data.db_secret` from both ComputeStack instantiation (L103) and BatchAnalysisStack instantiation (L167).

After this tier, the Secrets Manager secret is referenced by zero code paths. Pre-deploy verification: `cdk synth` succeeds and `grep -r 'secretsmanager' infra/` returns nothing (or only legitimate uses we don't touch).

## Tier 5 — Verification before deploy `[manual]`

Production-only environment, no staging — `cdk diff` is the only preview tool.

```bash
poetry run cdk diff SteamPulse-Production/Data
```

Expected diffs:
- `Resources.Db.Properties.MasterUserPassword`: `{{resolve:secretsmanager:...}}` → `{{resolve:ssm-secure:/steampulse/production/db-master-password:1}}`
- `Resources.DbSecret`: REMOVED (the import is gone)
- 8 IAM Policy diffs (compute + batch): `secretsmanager:GetSecretValue` action removed from the db-secret resource entry

**If `cdk diff` shows ANY change to RDS properties OTHER THAN MasterUserPassword's reference token** (e.g. `MasterUsername` flip, `Engine` re-evaluation, `MasterUserSecret` injection), STOP and investigate before deploying. CFN sometimes pulls in side-effects when one property changes.

```bash
poetry run cdk diff SteamPulse-Production/Compute
poetry run cdk diff SteamPulse-Production/BatchAnalysis
```

Expect: 8 IAM Policy statement removals, no Lambda function changes (env vars already include `DB_PASSWORD_PARAM_NAME` from the prior PR).

## Tier 6 — Deploy + verify `[manual]`

```bash
poetry run cdk deploy SteamPulse-Production/Data SteamPulse-Production/Compute SteamPulse-Production/BatchAnalysis
```

Order matters: Data stack first (RDS property change), then Compute + BatchAnalysis (IAM grant removal). The Data deploy will issue `ModifyDBInstance` with the new password — should be a no-op since T1 verified the value matches.

Post-deploy checks:
1. Tail any DB-touching Lambda log (e.g. `crawler`) — confirm no `password authentication failed` errors.
2. Trigger one realtime API call that hits the DB — confirm 200 response.
3. Pull `db-tunnel.sh` to confirm operator access still works with the live password.

If anything fails, the rollback path is: revert the PR, re-deploy Data stack to restore the Secrets Manager reference, restore IAM grants. The Secrets Manager secret was retained throughout, so this rollback works.

## Tier 7 — Delete the legacy DB secret `[manual]`

After 24h of clean Lambda + API operation:

```bash
aws secretsmanager delete-secret \
  --secret-id steampulse/production/db-credentials \
  --force-delete-without-recovery
```

Update `scripts/delete-legacy-secrets.sh` to add this to its target list (or run via console).

After deletion, the only remaining `steampulse/*` secrets in production should be: NONE. The `aws secretsmanager list-secrets` command should return empty for the `steampulse/` prefix.

## Tier 8 — Drop DB_SECRET_NAME config field `[code]`

`src/library-layer/library_layer/config.py` — remove `DB_SECRET_NAME: str`. Remove the matching env-var lines from `.env.production`, `.env.staging`, `.env.example`, `.env`, `tests/conftest.py` `_TEST_ENV_DEFAULTS`. Update `tests/test_config.py` (line ~47 uses `DB_SECRET_NAME` in the validation test — swap to another required field).

Grep for any leftover references — should be none in the source tree (some completed prompts reference it; those are historical and stay).

## Out of scope

- **T3-A from the original `secrets-consolidation.md`** — dropping the unused `STEAM_API_KEY_SECRET_NAME` / `RESEND_API_KEY_SECRET_NAME` config fields. Could be folded into Tier 8 here for one big cleanup, but it's clean enough as a separate trivial PR.
- **L1 deletion-override alternative** — leaves CFN unable to manage `MasterUserPassword` ever again. Conservative choice was to keep CDK in the loop via the SSM SecureString.
- **Staging environment** — currently not deployed. If staging returns, T1 needs to backfill `/steampulse/staging/db-master-password` and the Aurora Serverless v2 cluster needs the same `from_password(SecretValue.ssm_secure(...))` swap.

## Critical files

- `src/library-layer/library_layer/utils/db.py` — switch from boto3 secretsmanager to PowerTools `get_parameter` (T2)
- `src/library-layer/library_layer/config.py` — add `DB_MASTER_PASSWORD_PARAM_NAME` (T3); drop `DB_SECRET_NAME` (T8)
- `infra/stacks/data_stack.py` — switch RDS to `from_password(SecretValue.ssm_secure(...))`; drop secret import + plumbing (T3)
- `infra/stacks/compute_stack.py` — drop `db_secret` param + 7 grant_read sites + secretsmanager import (T4)
- `infra/stacks/batch_analysis_stack.py` — drop `db_secret` param + 1 grant_read + secretsmanager import (T4)
- `infra/application_stage.py` — drop `db_secret=` kwargs from 2 stack instantiations (T4)
- `.env.production`, `.env.staging`, `.env.example`, `.env`, `tests/conftest.py` — wire `DB_MASTER_PASSWORD_PARAM_NAME` (T3); drop `DB_SECRET_NAME` (T8)
- `tests/infra/test_compute_stack.py` — drop the fake `db_secret = secretsmanager.Secret(...)` fixture + kwarg + secretsmanager import (T4)
- `tests/test_config.py` — update validation test to use a different required field (T8)

## Savings

**~$0.40/mo** plus removal of `aws_cdk.aws_secretsmanager` import from CDK (one fewer service surface to reason about). After T7, `aws secretsmanager list-secrets --query 'SecretList[?starts_with(Name, \`steampulse/\`)]'` returns empty.

## Risks / gotchas

1. **T1 verify mismatch → password reset.** The single biggest risk. CFN's `ModifyDBInstance` with a different `MasterUserPassword` resets the live password and breaks every connection. T1's byte-for-byte verify is non-negotiable. Re-verify immediately before T6 deploy in case anything drifted.
2. **No staging means no preview-then-promote.** Production is the only env. `cdk diff` is the only preview tool. Rely on it; if the diff shows anything unexpected on the RDS resource, abort.
3. **Rollback window.** The Secrets Manager secret stays through T6 — rollback is "revert the PR, redeploy Data stack". After T7 (force-delete), rollback requires manually recreating the secret from the SSM SecureString. T7 should not run until T6 is proven stable for at least 24h.
4. **PowerTools `get_parameter` cache.** 5-second default TTL. The cold-start fetch in `get_db_url()` happens once per Lambda invocation chain (cached at the connection-pool level via `_state["conn"]`), so the inner cache TTL doesn't matter.
5. **Spoke handlers don't touch DB.** No changes needed — they remain DB-free and unaffected.
