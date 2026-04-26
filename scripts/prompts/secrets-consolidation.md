# Secrets → SSM Parameter Store SecureString (full migration)

## Context

After `cost-trim-round-4.md` shipped, run-rate cut by ~$42/mo. The next visible knob in the long tail is **AWS Secrets Manager**: each secret costs **$0.40/month** plus a few cents per 10k API calls. We currently maintain **4 secrets per environment** (8 total across production + staging). None of them use Secrets Manager's billed features — no rotation, no auto-generation we depend on, no replication.

Today's secrets:

| SSM/Secret name | Use | CDK reference | Why it's there |
|---|---|---|---|
| `/steampulse/{env}/steam-api-key` | Steam Web API key | `infra/stacks/compute_stack.py:390` | Plain string, manually set |
| `/steampulse/{env}/anthropic-api-key` | Anthropic Console API key | `infra/stacks/compute_stack.py:114`, `infra/stacks/batch_analysis_stack.py:95` | Plain string, manually set |
| `/steampulse/{env}/resend-api-key` (`config.RESEND_API_KEY_SECRET_NAME`) | Resend transactional email key | `infra/stacks/compute_stack.py:902` | Plain string, manually set |
| `steampulse/{env}/db-credentials` | RDS master password | `infra/stacks/data_stack.py:60` (prod, manual import); `data_stack.py:104-107` (staging, CDK-generated) | RDS `Credentials.from_secret` / `from_generated_secret` integration |

**Current spend:** $0.40 × 4 × 2 envs = **$3.20/month** purely for "encrypted-string-at-rest." Parameter Store SecureString offers exactly that for **$0** (using the AWS-managed `aws/ssm` KMS key, which carries no monthly fee; only `kms:Decrypt` API calls are billed at $0.03/10k — rounding error at our cold-start fetch volume).

**Important context found during planning:** No managed rotation is enabled on any of these secrets (no `add_rotation_schedule` calls anywhere in the CDK). The DB-secret-stays-in-Secrets-Manager argument I wrote in the previous draft of this prompt was wrong — there's no rotation to break. The real DB-credentials constraint is just that RDS's `rds.Credentials.from_secret` / `from_generated_secret` constructs only accept Secrets Manager secrets, so the migration requires switching to `rds.Credentials.from_password(SecretValue.ssm_secure(...))`. That's a deploy-time consideration, not a runtime one.

## Goal

Move all 8 secrets from Secrets Manager → Parameter Store SecureString. Net savings: **~$3.20/month** (full elimination of the Secrets Manager line item). Plus a single uniform IAM surface (`ssm:GetParameter` + `kms:Decrypt`) instead of mixing two services.

The DB-credentials migration (T4) is more involved than the API-key migration (T2–T3) because it touches the RDS construct itself. Ship T1–T3 first, soak for a week, then ship T4.

## Tier 1 — Provision SecureString parameters

### T1-A. Manual: copy values from Secrets Manager → SecureString params `[manual]`

The user runs these commands (Claude does not run AWS write APIs). Each block reads the current value from the existing Secrets Manager secret and writes it byte-for-byte into a new SecureString parameter — no manual retyping, no source-of-truth files. This guarantees the migration is a relocation, not a rotation.

```bash
# API keys — pulled directly from the existing Secrets Manager secrets.
# All 3 are stored as plain strings in SecretString (not JSON), so the
# raw SecretString value is the key.
for env in production staging; do
  for k in steam-api-key anthropic-api-key resend-api-key; do
    short=${k%-api-key}                # steam | anthropic | resend
    value=$(aws secretsmanager get-secret-value \
      --secret-id "/steampulse/${env}/${k}" \
      --query 'SecretString' --output text)
    aws ssm put-parameter \
      --name "/steampulse/${env}/api-keys/${short}" \
      --type SecureString \
      --value "$value"
    unset value
  done
done

# DB passwords — pulled from the JSON-shaped db-credentials secret.
# CFN compares string equality on MasterUserPassword in T4; any drift
# (whitespace, encoding) would trigger ModifyDBInstance and reset the
# live password mid-deploy.
for env in production staging; do
  value=$(aws secretsmanager get-secret-value \
    --secret-id "steampulse/${env}/db-credentials" \
    --query 'SecretString' --output text \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['password'])")
  aws ssm put-parameter \
    --name "/steampulse/${env}/db-password" \
    --type SecureString \
    --value "$value"
  unset value
done
```

> **Verify each `SecretString` is actually a plain string before running** — if any of the API key secrets were rewritten as JSON at some point, adjust the extraction (use the same `python3 -c "import json,sys; print(json.load(sys.stdin)['key'])"` pattern as the DB block).
>
> Quick check:
> ```bash
> for env in production staging; do
>   for k in steam-api-key anthropic-api-key resend-api-key; do
>     v=$(aws secretsmanager get-secret-value --secret-id "/steampulse/${env}/${k}" \
>       --query 'SecretString' --output text)
>     echo "${env}/${k}: $(echo "$v" | python3 -c 'import json,sys; d=sys.stdin.read(); print(\"json\" if d.startswith(\"{\") else \"plain\")')"
>     unset v
>   done
> done
> ```

Defaults: AWS-managed key (`alias/aws/ssm`), Standard tier (free, no monthly fee). Run this entire block **before** flipping any code — both T2 (API keys) and T4 (DB) read from these new parameters at the next deploy.

### T1-B. Verify the values match `[manual]`

Before any code change, confirm each SecureString parameter matches its source secret byte-for-byte. The `diff` swallows the values so they don't end up in shell history.

```bash
for env in production staging; do
  for k in steam-api-key anthropic-api-key resend-api-key; do
    short=${k%-api-key}
    diff <(aws secretsmanager get-secret-value --secret-id "/steampulse/${env}/${k}" \
              --query 'SecretString' --output text) \
         <(aws ssm get-parameter --name "/steampulse/${env}/api-keys/${short}" \
              --with-decryption --query 'Parameter.Value' --output text) \
      && echo "OK ${env}/${k}" || echo "MISMATCH ${env}/${k}"
  done
  diff <(aws secretsmanager get-secret-value --secret-id "steampulse/${env}/db-credentials" \
            --query 'SecretString' --output text \
            | python3 -c "import json,sys; print(json.load(sys.stdin)['password'])") \
       <(aws ssm get-parameter --name "/steampulse/${env}/db-password" \
            --with-decryption --query 'Parameter.Value' --output text) \
    && echo "OK ${env}/db-password" || echo "MISMATCH ${env}/db-password"
done
```

Expect 8 `OK` lines. Any `MISMATCH` blocks the rest of the migration — re-run the relevant `put-parameter` and verify before proceeding.

> **KMS note:** SecureString uses the AWS-managed `aws/ssm` key by default. AWS-managed keys are free; only `kms:Decrypt` API calls cost $0.03/10k. At our cold-start fetch volume (~one decrypt per Lambda cold start per key) this is well under $0.05/month total.

## Tier 2 — Migrate API key code paths

### T2-A. Add config fields

`src/library-layer/library_layer/config.py` — add four fields (alongside the existing `*_SECRET_NAME` fields, which stay until T5):

```python
STEAM_API_KEY_PARAM_NAME: str = ""       # /steampulse/{env}/api-keys/steam
ANTHROPIC_API_KEY_PARAM_NAME: str = ""   # /steampulse/{env}/api-keys/anthropic
RESEND_API_KEY_PARAM_NAME: str = ""      # /steampulse/{env}/api-keys/resend
DB_PASSWORD_PARAM_NAME: str = ""         # /steampulse/{env}/db-password (used in T4)
```

Wire them through `.env.production`, `.env.staging`, `.env.example`, and `tests/conftest.py` defaults.

### T2-B. Migrate every API-key callsite to `get_parameter(..., decrypt=True)`

Use `aws_lambda_powertools.utilities.parameters.get_parameter` (already in use elsewhere) or a regional `boto3.client("ssm")` for cross-region paths.

**Known sites (verify with `Grep STEAM_API_KEY_SECRET_NAME ANTHROPIC_API_KEY_SECRET_NAME RESEND_API_KEY_SECRET_NAME` before editing):**

- `src/lambda-functions/lambda_functions/crawler/handler.py` — Steam key:
  ```python
  # Before
  _sm = boto3.client("secretsmanager")
  _steam_api_key = _sm.get_secret_value(SecretId=_crawler_config.STEAM_API_KEY_SECRET_NAME)["SecretString"]
  # After
  from aws_lambda_powertools.utilities.parameters import get_parameter
  _steam_api_key = get_parameter(_crawler_config.STEAM_API_KEY_PARAM_NAME, decrypt=True)
  ```

- `src/lambda-functions/lambda_functions/crawler/spoke_handler.py` — Steam key, **cross-region read** from primary. Powertools `get_parameter` doesn't accept `region_name`, so use raw boto3 (same pattern as today):
  ```python
  _ssm = boto3.client("ssm", region_name=_PRIMARY_REGION)
  _steam_api_key = _ssm.get_parameter(
      Name=_config.STEAM_API_KEY_PARAM_NAME, WithDecryption=True
  )["Parameter"]["Value"]
  ```

- `src/library-layer/library_layer/llm/__init__.py` — `resolve_anthropic_api_key`:
  ```python
  return get_parameter(config.ANTHROPIC_API_KEY_PARAM_NAME, decrypt=True)
  ```

- `src/lambda-functions/lambda_functions/email/handler.py` — Resend key:
  ```python
  _resend_api_key = get_parameter(_config.RESEND_API_KEY_PARAM_NAME, decrypt=True)
  ```

### T2-C. Update CDK grants for API keys

For each affected stack, replace `Secret.from_secret_name_v2(...)` import + `<secret>.grant_read(<role>)` with `StringParameter.from_secure_string_parameter_attributes(...)` + `<param>.grant_read(<role>)`.

**`infra/stacks/compute_stack.py`** — three sites:
- AnalysisFn (line ~114): replace `anthropic_secret`
- CrawlerFn (line ~390): replace `steam_api_key_secret`
- EmailFn (line ~902): replace `resend_secret`

```python
# Before
anthropic_secret = secretsmanager.Secret.from_secret_name_v2(
    self, "AnalysisAnthropicApiKey", f"/steampulse/{env}/anthropic-api-key"
)
anthropic_secret.grant_read(analysis_role)

# After
anthropic_param = ssm.StringParameter.from_secure_string_parameter_attributes(
    self, "AnalysisAnthropicApiKey", parameter_name=config.ANTHROPIC_API_KEY_PARAM_NAME
)
anthropic_param.grant_read(analysis_role)
```

**`infra/stacks/batch_analysis_stack.py`** — same swap for the Anthropic key (line ~95).

**`infra/stacks/spoke_stack.py`** — switch the spoke role's IAM grant from secretsmanager to ssm. Rename the env var passed to the spoke handler from `STEAM_API_KEY_SECRET_NAME` → `STEAM_API_KEY_PARAM_NAME`.

`StringParameter.grant_read(...)` automatically includes the `kms:Decrypt` permission for the AWS-managed `aws/ssm` key — no extra KMS policy work needed.

## Tier 3 — Decommission the legacy API-key secrets

After T2 ships and one full crawler/analysis/email cycle has succeeded against the new SecureString params in production:

### T3-A. Drop the old `*_SECRET_NAME` config fields `[code]`

`src/library-layer/library_layer/config.py` — remove:
- `STEAM_API_KEY_SECRET_NAME`
- `ANTHROPIC_API_KEY_SECRET_NAME`
- `RESEND_API_KEY_SECRET_NAME`

Drop the matching env-var lines from `.env.production`, `.env.staging`, `.env.example`, `tests/conftest.py`. Grep for any leftover references — should be none after T2.

### T3-B. Manual: delete the old API-key secrets `[manual]`

Per env, after a 7-day soak:

```bash
for env in production staging; do
  for s in steam-api-key anthropic-api-key resend-api-key; do
    aws secretsmanager delete-secret \
      --secret-id "/steampulse/${env}/${s}" \
      --recovery-window-in-days 7
  done
done
```

The 7-day recovery window means an accidental deletion can be undone. Once it expires the $0.40/mo line stops billing.

## Tier 4 — Migrate DB credentials (more involved)

> **⚠️ Ship this AFTER T1–T3 have soaked for at least a week.** This tier touches the RDS construct, which is harder to roll back than a Lambda code change. Read the full tier before starting.

### T4-A. Switch the application's DB connection logic `[code]`

Today's `src/library-layer/library_layer/utils/db.py` reads the full credentials JSON from Secrets Manager (username + password + host + port + dbname). After T4, the application reads:

- **password** from SSM SecureString (`config.DB_PASSWORD_PARAM_NAME`)
- **host / port / dbname / username** from plain SSM String parameters that CDK writes from RDS construct outputs (no secret material — they're public-once-deployed metadata)

Add four new config fields:

```python
DB_HOST_PARAM_NAME: str = ""       # /steampulse/{env}/db/host
DB_PORT_PARAM_NAME: str = ""       # /steampulse/{env}/db/port
DB_NAME_PARAM_NAME: str = ""       # /steampulse/{env}/db/name
DB_USERNAME_PARAM_NAME: str = ""   # /steampulse/{env}/db/username (always "postgres" today)
```

In `db.py`, replace the Secrets Manager fetch with parallel SSM fetches (cold-start only, cached at module level):

```python
from aws_lambda_powertools.utilities.parameters import get_parameter

_DB_HOST = get_parameter(_config.DB_HOST_PARAM_NAME)
_DB_PORT = int(get_parameter(_config.DB_PORT_PARAM_NAME))
_DB_NAME = get_parameter(_config.DB_NAME_PARAM_NAME)
_DB_USER = get_parameter(_config.DB_USERNAME_PARAM_NAME)
_DB_PASSWORD = get_parameter(_config.DB_PASSWORD_PARAM_NAME, decrypt=True)
```

### T4-B. Switch the RDS construct from `from_secret` → `from_password(ssm_secure)` `[code]`

`infra/stacks/data_stack.py` — both branches.

**Production branch** (line ~60):

```python
# Before
db_secret = secretsmanager.Secret.from_secret_name_v2(self, "DbSecret", secret_name)
db_instance = rds.DatabaseInstance(
    ...,
    credentials=rds.Credentials.from_secret(db_secret),
    ...
)

# After
db_password = cdk.SecretValue.ssm_secure(config.DB_PASSWORD_PARAM_NAME)
db_instance = rds.DatabaseInstance(
    ...,
    credentials=rds.Credentials.from_password(username="postgres", password=db_password),
    ...
)
```

> **Critical:** the SecureString value MUST exactly match the current Secrets Manager `password` field. CFN compares string equality on `MasterUserPassword`; any drift triggers `ModifyDBInstance` to reset the live password and break every active connection. T1-A's backfill loop reads the existing value and writes it byte-for-byte — do not retype it manually.

**Staging branch** (line ~98) is more invasive because it currently uses `Credentials.from_generated_secret(...)`. Switch to:

```python
db_password = cdk.SecretValue.ssm_secure(config.DB_PASSWORD_PARAM_NAME)
db_cluster = rds.DatabaseCluster(
    ...,
    credentials=rds.Credentials.from_password(username="postgres", password=db_password),
    ...
)
# REMOVE: db_secret = db_cluster.secret  (no longer exists)
# REMOVE: the cfn_secret.override_logical_id() block (the secret is gone)
```

The pre-existing CDK-generated secret will become orphaned after this deploy (CFN no longer manages it). Delete it manually in T5-B.

### T4-C. Write RDS connection metadata to SSM Strings `[code]`

After the RDS construct is built, write its endpoint/port/dbname/username to plain SSM parameters:

```python
ssm.StringParameter(
    self, "DbHostParam",
    parameter_name=f"/steampulse/{env}/db/host",
    string_value=db_endpoint,
)
ssm.StringParameter(
    self, "DbPortParam",
    parameter_name=f"/steampulse/{env}/db/port",
    string_value="5432",
)
ssm.StringParameter(
    self, "DbNameParam",
    parameter_name=f"/steampulse/{env}/db/name",
    string_value=db_name,
)
ssm.StringParameter(
    self, "DbUsernameParam",
    parameter_name=f"/steampulse/{env}/db/username",
    string_value="postgres",
)
```

These are non-sensitive (host/port/dbname are visible in any AWS console anyway) so plain `String` is fine — no encryption cost.

### T4-D. Drop `db_secret` plumbing from every consumer `[code]`

Today multiple stacks accept a `db_secret: secretsmanager.ISecret` parameter and call `db_secret.grant_read(<role>)`. Audit every site:

- `infra/stacks/compute_stack.py` — `db_secret` constructor param + `db_secret.grant_read(...)` calls
- `infra/stacks/batch_analysis_stack.py` — same pattern
- `infra/application_stage.py` — wires `db_secret=data_stack.db_secret` into both stacks

Replace with `db_password_param: ssm.IStringParameter` (or just have each stack import the SecureString param itself by name). The grant becomes `db_password_param.grant_read(role)` (auto-includes `kms:Decrypt`).

The plain String params (host/port/dbname/username) are world-readable to anyone with `ssm:GetParameter` — the existing `arn:aws:ssm:.../parameter/steampulse/{env}/*` wildcard policies in each role already cover them. No new grants needed for those four.

### T4-E. Verify before merging `[code]`

```bash
poetry run cdk diff SteamPulse-Production-Data
# Expect:
#   - Db: MasterUserPassword changes from {{resolve:secretsmanager:...}} to {{resolve:ssm-secure:...}}
#   - 4 new AWS::SSM::Parameter resources (Host, Port, Name, Username)
#   - IAM policies switched from secretsmanager:GetSecretValue → ssm:GetParameter + kms:Decrypt
```

If `cdk diff` shows ANY change to `MasterUserPassword`'s resolved value (CFN expands the dynamic reference at deploy time — you can't see the resolved value in the diff, but you can see whether the reference token changed), pause and re-verify T1-A's backfill matches the live password byte-for-byte. The safest way to verify pre-deploy:

```bash
# Compare the two values without echoing them
diff \
  <(aws secretsmanager get-secret-value --secret-id steampulse/production/db-credentials \
      --query 'SecretString' --output text \
      | python3 -c "import json,sys; print(json.load(sys.stdin)['password'])") \
  <(aws ssm get-parameter --name /steampulse/production/db-password \
      --with-decryption --query 'Parameter.Value' --output text)
# expect: no output (identical)
```

End-to-end functional check after deploy: trigger one realtime analysis (which touches the DB), verify it succeeds in CloudWatch logs. Pull `db-tunnel.sh` to confirm operator access still works.

## Tier 5 — Decommission DB secrets

After T4 has soaked for a week:

### T5-A. Drop the legacy `db_secret` import in `data_stack.py` `[code]`

The `db_secret = secretsmanager.Secret.from_secret_name_v2(...)` line in the production branch becomes unused after T4. Remove it. Also remove the `self.db_secret` attribute and update `application_stage.py` to stop passing it through.

### T5-B. Manual: delete the legacy DB secrets `[manual]`

Per env, after a 7-day soak:

```bash
for env in production staging; do
  aws secretsmanager delete-secret \
    --secret-id "steampulse/${env}/db-credentials" \
    --recovery-window-in-days 7
done
```

7-day recovery window means an accidental deletion can be undone (`restore-secret`).

## Out of scope

- **Customer-managed KMS key (CMK) on the SecureString params.** Default `aws/ssm` is fine for $0/month; CMK adds $1/month per key for no security benefit at our scale.
- **Advanced parameter tier.** Standard tier (4KB max value, 10k params per account) is plenty.
- **Cross-region replication.** Spokes already cross-region read from us-west-2 with a regional client. Same pattern works on SSM.
- **RDS managed rotation.** Not currently enabled (verified: no `add_rotation_schedule` calls in the CDK). If we ever need it, we'd move the DB password back to Secrets Manager — a one-stack change.

## Verification (aggregate, after T5)

```bash
# 1. New parameters readable + decryptable
aws ssm get-parameter --name /steampulse/production/api-keys/steam --with-decryption \
  --query 'Parameter.Value' --output text | head -c 8 ; echo
aws ssm get-parameter --name /steampulse/production/db-password --with-decryption \
  --query 'Parameter.Value' --output text | head -c 8 ; echo

# 2. No SteamPulse-namespaced secrets remain
aws secretsmanager list-secrets \
  --query 'SecretList[?starts_with(Name, `steampulse/`) || starts_with(Name, `/steampulse/`)].Name'
# expect: empty (or only secrets scheduled for deletion within recovery window)

# 3. Cost Explorer line item drops to $0 within ~7 days
aws ce get-cost-and-usage --time-period Start=YYYY-MM-DD,End=YYYY-MM-DD \
  --granularity DAILY --metrics UnblendedCost \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":["AWS Secrets Manager"]}}'
```

## Critical files

- `src/library-layer/library_layer/config.py` — add 8 `*_PARAM_NAME` fields (T2-A, T4-A); drop `*_SECRET_NAME` fields (T3-A, T5-A)
- `.env.production`, `.env.staging`, `.env.example`, `tests/conftest.py` — wire all 8 new param-name env vars; drop secret-name env vars after migration
- `src/library-layer/library_layer/utils/db.py` — switch from Secrets Manager fetch to parallel SSM fetches (T4-A)
- `src/library-layer/library_layer/llm/__init__.py` — switch `resolve_anthropic_api_key` to `get_parameter` (T2-B)
- `src/lambda-functions/lambda_functions/crawler/handler.py` — switch Steam key resolver (T2-B)
- `src/lambda-functions/lambda_functions/crawler/spoke_handler.py` — switch cross-region Steam key resolver (T2-B)
- `src/lambda-functions/lambda_functions/email/handler.py` — switch Resend key resolver (T2-B)
- `infra/stacks/compute_stack.py` — replace 3 Secret imports + grants with SSM equivalents (T2-C); drop `db_secret` plumbing (T4-D, T5-A)
- `infra/stacks/batch_analysis_stack.py` — replace Anthropic Secret + db_secret grants with SSM (T2-C, T4-D, T5-A)
- `infra/stacks/spoke_stack.py` — replace Steam Secret grant with SSM (T2-C); rename spoke env var
- `infra/stacks/data_stack.py` — switch RDS `Credentials.from_secret` / `from_generated_secret` to `Credentials.from_password(SecretValue.ssm_secure(...))` (T4-B); add 4 SSM String params for endpoint metadata (T4-C); drop `self.db_secret` (T5-A)
- `infra/application_stage.py` — stop wiring `db_secret` through to compute and batch stacks (T5-A)

## Savings

**~$3.20/month** (8 secrets × $0.40 × 0 remaining) + uniform IAM (one service for all credential storage) + simpler config story (everything is `*_PARAM_NAME`).

Tier ordering keeps risk concentrated in T4 — T1–T3 are entirely additive and can be rolled back trivially. Don't ship T4 until T1–T3 have proven stable.
