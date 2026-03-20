# CDK Lambda Environment Refactor — SSM-Backed Config

## Goal

Today, every Lambda has 8–15 hand-coded env vars in CDK passing CDK Token
references (`db_secret.secret_arn`, `queue.queue_url`, etc.). This drifts
out of sync with `SteamPulseConfig` and creates fragile cross-stack wiring.

**Target state:** CDK stacks publish resource ARNs/URLs to SSM. `.env.staging`
and `.env.production` hold SSM parameter **names**. Lambdas resolve SSM →
actual values at cold start. CDK sets `environment=config.to_lambda_env()` —
zero overrides, zero drift.

```
CDK stacks ──publish──▶ SSM Parameter Store
                            │
.env.staging ──SSM names──▶ SteamPulseConfig ──resolve──▶ actual ARNs/URLs
                            │
Lambda env = config.to_lambda_env()   ← zero CDK overrides
```

---

## Design

### SSM naming convention (already established)

```
/steampulse/{env}/{stack-domain}/{resource-name}
```

Examples:
- `/steampulse/staging/data/db-secret-arn`
- `/steampulse/staging/messaging/app-crawl-queue-url`
- `/steampulse/staging/compute/sfn-arn`

### All infrastructure config in `.env` — `to_lambda_env()` needs only `POWERTOOLS_*` overrides

Both Secrets Manager secrets use **deterministic names** so they can live in `.env`
just like SSM param names. Lambda calls `get_secret_value(SecretId=name)` — one hop,
no ARN needed.

- `STEAM_API_KEY_SECRET_ARN` already uses `from_secret_name_v2("steampulse/{env}/steam-api-key")` — deterministic name already exists.
- `DB_SECRET_ARN` — fix: add `credentials=rds.Credentials.from_generated_secret("postgres", secret_name=f"steampulse/{env}/db-credentials")` when creating the RDS instance/cluster. Then the name is known at `.env` time.

Rename both fields to `_SECRET_NAME` (holds a Secrets Manager **name**, not an ARN):
- `DB_SECRET_NAME` — value: `steampulse/staging/db-credentials`
- `STEAM_API_KEY_SECRET_NAME` — value: `steampulse/staging/steam-api-key`

**Result:** `to_lambda_env()` only ever needs `POWERTOOLS_*` overrides. No CDK token overrides.

### `.env.staging` — complete source of truth

```bash
ENVIRONMENT=staging

# LLM model routing
LLM_MODEL__CHUNKING=us.anthropic.claude-haiku-4-5-20250514-v1:0
LLM_MODEL__SUMMARIZER=us.anthropic.claude-sonnet-4-6-20250514-v1:0

# Feature flags
PRO_ENABLED=false

# Secrets Manager names — Lambda calls get_secret_value(SecretId=name) directly
DB_SECRET_NAME=steampulse/staging/db-credentials
STEAM_API_KEY_SECRET_NAME=steampulse/staging/steam-api-key

# SSM parameter names — resolved at Lambda cold start via get_parameter()
SFN_PARAM_NAME=/steampulse/staging/compute/sfn-arn
STEP_FUNCTIONS_PARAM_NAME=/steampulse/staging/compute/sfn-arn
APP_CRAWL_QUEUE_PARAM_NAME=/steampulse/staging/messaging/app-crawl-queue-url
REVIEW_CRAWL_QUEUE_PARAM_NAME=/steampulse/staging/messaging/review-crawl-queue-url
ASSETS_BUCKET_PARAM_NAME=/steampulse/staging/data/assets-bucket-name
GAME_EVENTS_TOPIC_PARAM_NAME=/steampulse/staging/messaging/game-events-topic-arn
CONTENT_EVENTS_TOPIC_PARAM_NAME=/steampulse/staging/messaging/content-events-topic-arn
SYSTEM_EVENTS_TOPIC_PARAM_NAME=/steampulse/staging/messaging/system-events-topic-arn
```

`.env.production` is identical except `ENVIRONMENT=production` and names use `staging` → `production`.

### Lambdas resolve SSM and Secrets Manager at runtime

`_PARAM_NAME` fields → Powertools `get_parameter()` (SSM, cached 5 min).
`_SECRET_NAME` fields → `secretsmanager.get_secret_value(SecretId=name)` (one hop).

---

## Files to Modify

### 1. `src/library-layer/library_layer/config.py`

Add `to_lambda_env()`. No SSM resolution here — Lambdas resolve SSM param
values themselves using Powertools `get_parameter()` (one-liner, cached).

```python
class SteamPulseConfig(BaseSettings):
    # ... existing fields unchanged ...

    def to_lambda_env(self, **overrides: str) -> dict[str, str]:
        """Build a Lambda environment dict from this config.

        Serialises all config fields as flat key=string pairs.
        Nested dicts (LLM_MODEL) are flattened with __ delimiter.
        Overrides are applied last (for POWERTOOLS_* and similar).
        """
        env: dict[str, str] = {}
        for k, v in self.model_dump().items():
            if isinstance(v, dict):
                for nk, nv in v.items():
                    env[f"{k}__{nk}"] = str(nv)
            elif isinstance(v, bool):
                env[k] = str(v).lower()
            else:
                env[k] = str(v)
        env.update(overrides)
        return env
```

**Also remove `ARCHIVE_BUCKET: str = ""`** — dead code.

**Also rename** `DB_SECRET_ARN` → `DB_SECRET_NAME` and `STEAM_API_KEY_SECRET_ARN` → `STEAM_API_KEY_SECRET_NAME` in `SteamPulseConfig`. These hold Secrets Manager **names** (not ARNs). Lambda calls `get_secret_value(SecretId=name)` — no CDK override needed.

### Runtime resolution — in Lambda handlers, NOT in config

Two resolution patterns depending on the field suffix:

**`_PARAM_NAME`** — SSM Parameter Store, via Powertools `get_parameter()` (cached 5 min):
```python
from aws_lambda_powertools.utilities.parameters import get_parameter

_config = SteamPulseConfig()

# Resolve only the SSM params this Lambda needs
sfn_arn       = get_parameter(_config.SFN_PARAM_NAME)
review_q_url  = get_parameter(_config.REVIEW_CRAWL_QUEUE_PARAM_NAME)
```

**`_SECRET_NAME`** — Secrets Manager, direct `get_secret_value()` call (no SSM hop):
```python
# db.py already does this — no changes needed:
sm = boto3.client("secretsmanager")
secret = json.loads(sm.get_secret_value(SecretId=_config.DB_SECRET_NAME)["SecretString"])
```

Fields that are NOT resolution paths (LLM_MODEL, PRO_ENABLED, ENVIRONMENT) are used directly.

### Lambda handler changes

Example for `crawler/handler.py`:

```python
# Before:
_config = SteamPulseConfig()
_crawl_service = CrawlService(
    review_queue_url=_config.REVIEW_CRAWL_QUEUE_URL,  # was a real URL
    sfn_arn=_config.STEP_FUNCTIONS_ARN,               # was a real ARN
)

# After:
from aws_lambda_powertools.utilities.parameters import get_parameter

_config = SteamPulseConfig()
_crawl_service = CrawlService(
    review_queue_url=get_parameter(_config.REVIEW_CRAWL_QUEUE_PARAM_NAME),
    sfn_arn=get_parameter(_config.SFN_PARAM_NAME),
)
```

`db.py` needs one rename: `os.getenv("DB_SECRET_ARN")` → `os.getenv("DB_SECRET_NAME")`.
The `get_secret_value()` call is unchanged — names work as `SecretId` the same as ARNs.

### 2. CDK stacks — fix RDS secret name + add missing SSM parameters

**`infra/stacks/data_stack.py`** — give RDS secret a deterministic name:
```python
# For DatabaseInstance (production):
db_instance = rds.DatabaseInstance(
    self, "Db",
    ...
    credentials=rds.Credentials.from_generated_secret(
        "postgres",
        secret_name=f"steampulse/{env}/db-credentials",
    ),
)

# For DatabaseCluster (staging):
db_cluster = rds.DatabaseCluster(
    self, "Db",
    ...
    credentials=rds.Credentials.from_generated_secret(
        "postgres",
        secret_name=f"steampulse/{env}/db-credentials",
    ),
)
```

Also add the assets bucket SSM param:
```python
ssm.StringParameter(self, "AssetsBucketNameParam",
    parameter_name=f"/steampulse/{env}/data/assets-bucket-name",
    string_value=self.assets_bucket.bucket_name,
)
```

**`infra/stacks/messaging_stack.py`** — add queue URL params (currently only publishes ARNs):
```python
ssm.StringParameter(self, "AppCrawlQueueUrlParam",
    parameter_name=f"/steampulse/{env}/messaging/app-crawl-queue-url",
    string_value=self.app_crawl_queue.queue_url,
)
ssm.StringParameter(self, "ReviewCrawlQueueUrlParam",
    parameter_name=f"/steampulse/{env}/messaging/review-crawl-queue-url",
    string_value=self.review_crawl_queue.queue_url,
)
```

**`infra/stacks/compute_stack.py`** — SFN ARN param already exists at
`/steampulse/{env}/compute/sfn-arn`. Verify the path matches `.env.staging`.

### 3. CDK stacks — replace all `environment=` blocks

Every Lambda is now simply:

```python
environment=config.to_lambda_env(
    POWERTOOLS_SERVICE_NAME="crawler",
    POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
),
```

No secret ARN overrides. No queue URL overrides. Everything is in `.env`.

**`compute_stack.py` — AnalysisFn:**
```python
environment=config.to_lambda_env(),
```

**`compute_stack.py` — ApiFn:**
```python
environment=config.to_lambda_env(PORT="8080"),
```

**`compute_stack.py` — FrontendFn:**
```python
environment={"NODE_ENV": "production"},  # Node.js Lambda — not Python, no config
```

**`compute_stack.py` — CrawlerFn:**
```python
environment=config.to_lambda_env(
    POWERTOOLS_SERVICE_NAME="crawler",
    POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
),
```

**`lambda_stack.py` — AppCrawler, ReviewCrawler, CatalogRefresher, DbLoaderFn:**
```python
environment=config.to_lambda_env(
    POWERTOOLS_SERVICE_NAME="app-crawler",  # adjust per Lambda
    POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
),
```

Delete the `common_env` dict — no longer needed.

**`app_stack.py` — ApiFunction:**
```python
environment=config.to_lambda_env(PORT="8080"),
```

**`analysis_stack.py` — AnalysisFn:**
```python
environment=config.to_lambda_env(),
```

### 4. IAM — grant SSM read to all Lambda roles

Every Lambda role needs `ssm:GetParameter` on the config params:

```python
role.add_to_policy(iam.PolicyStatement(
    actions=["ssm:GetParameter"],
    resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter/steampulse/{env}/*"],
))
```

Wildcarded to `/steampulse/{env}/*` — minimal blast radius.

### 5. Update `.env.staging` and `.env.production`

**`.env.staging`:**
```bash
ENVIRONMENT=staging

# LLM model routing
LLM_MODEL__CHUNKING=us.anthropic.claude-haiku-4-5-20250514-v1:0
LLM_MODEL__SUMMARIZER=us.anthropic.claude-sonnet-4-6-20250514-v1:0

# Feature flags
PRO_ENABLED=false

# Secrets Manager names — Lambda calls get_secret_value(SecretId=name) directly
DB_SECRET_NAME=steampulse/staging/db-credentials
STEAM_API_KEY_SECRET_NAME=steampulse/staging/steam-api-key

# SSM parameter names — resolved at Lambda cold start via get_parameter()
SFN_PARAM_NAME=/steampulse/staging/compute/sfn-arn
STEP_FUNCTIONS_PARAM_NAME=/steampulse/staging/compute/sfn-arn
APP_CRAWL_QUEUE_PARAM_NAME=/steampulse/staging/messaging/app-crawl-queue-url
REVIEW_CRAWL_QUEUE_PARAM_NAME=/steampulse/staging/messaging/review-crawl-queue-url
ASSETS_BUCKET_PARAM_NAME=/steampulse/staging/data/assets-bucket-name
GAME_EVENTS_TOPIC_PARAM_NAME=/steampulse/staging/messaging/game-events-topic-arn
CONTENT_EVENTS_TOPIC_PARAM_NAME=/steampulse/staging/messaging/content-events-topic-arn
SYSTEM_EVENTS_TOPIC_PARAM_NAME=/steampulse/staging/messaging/system-events-topic-arn
```

**`.env.production`:**
Same but `ENVIRONMENT=production` and `staging` → `production` in all names/paths.

---

## Constructor cleanup

After this refactor, CDK stacks that currently receive infrastructure as
constructor params (e.g., `db_secret`, `state_machine`, `app_crawl_queue`)
**still need them** for:
- IAM grants (`db_secret.grant_read(role)`)
- Event source mappings (`fn.add_event_source(SqsEventSource(queue))`)
- SSM parameter creation

They just no longer need them for `environment=` dicts.

---

## Cold start impact

Powertools `get_parameter()` adds ~10ms per SSM call on cold start, cached
5 minutes by default. A Lambda that resolves 3 params adds ~30ms. Warm
invocations use the cache — zero cost.

Acceptable for Lambda functions with 15–60s timeouts.

---

## Tests

### `tests/library_layer/test_config.py`

```python
def test_to_lambda_env_includes_all_fields():
    """model_dump → flat string dict with __ nesting."""
    config = SteamPulseConfig(
        ENVIRONMENT="staging",
        LLM_MODEL={"chunking": "haiku", "summarizer": "sonnet"},
        DB_SECRET_NAME="steampulse/staging/db-credentials",
        STEAM_API_KEY_SECRET_NAME="steampulse/staging/steam-api-key",
        SFN_PARAM_NAME="x", APP_CRAWL_QUEUE_PARAM_NAME="x",
        REVIEW_CRAWL_QUEUE_PARAM_NAME="x",
        ASSETS_BUCKET_PARAM_NAME="x", STEP_FUNCTIONS_PARAM_NAME="x",
        GAME_EVENTS_TOPIC_PARAM_NAME="x", CONTENT_EVENTS_TOPIC_PARAM_NAME="x",
        SYSTEM_EVENTS_TOPIC_PARAM_NAME="x",
    )
    env = config.to_lambda_env()
    assert env["ENVIRONMENT"] == "staging"
    assert env["LLM_MODEL__chunking"] == "haiku"
    assert env["LLM_MODEL__summarizer"] == "sonnet"
    assert env["PRO_ENABLED"] == "false"
    # Secrets Manager names pass through as-is (resolved by handlers, not config)
    assert env["DB_SECRET_NAME"] == "steampulse/staging/db-credentials"
    assert env["STEAM_API_KEY_SECRET_NAME"] == "steampulse/staging/steam-api-key"
    # SSM param names pass through as-is (resolved by handlers via get_parameter())
    assert env["APP_CRAWL_QUEUE_PARAM_NAME"] == "x"


def test_to_lambda_env_powertools_override():
    """Only POWERTOOLS_* overrides are needed — no CDK token overrides."""
    config = SteamPulseConfig(
        ENVIRONMENT="staging",
        LLM_MODEL={"chunking": "h", "summarizer": "s"},
        DB_SECRET_NAME="steampulse/staging/db-credentials",
        STEAM_API_KEY_SECRET_NAME="steampulse/staging/steam-api-key",
        SFN_PARAM_NAME="x", APP_CRAWL_QUEUE_PARAM_NAME="x",
        REVIEW_CRAWL_QUEUE_PARAM_NAME="x",
        ASSETS_BUCKET_PARAM_NAME="x", STEP_FUNCTIONS_PARAM_NAME="x",
        GAME_EVENTS_TOPIC_PARAM_NAME="x", CONTENT_EVENTS_TOPIC_PARAM_NAME="x",
        SYSTEM_EVENTS_TOPIC_PARAM_NAME="x",
    )
    env = config.to_lambda_env(POWERTOOLS_SERVICE_NAME="crawler", PORT="8080")
    assert env["POWERTOOLS_SERVICE_NAME"] == "crawler"
    assert env["PORT"] == "8080"
```

SSM resolution is tested at the Lambda handler level (where `get_parameter()`
is called), not in config tests.

---

## Validation

```bash
# 1. Tests pass
poetry run pytest tests/library_layer/test_config.py -v

# 2. CDK synth succeeds (SSM resolution skipped — not in Lambda)
poetry run cdk synth

# 3. Deploy and verify Lambda can resolve SSM
cdk deploy SteamPulse-Staging-Data SteamPulse-Staging-Messaging SteamPulse-Staging-Compute
# Invoke a Lambda and check logs for resolved values
```

---

## Execution Order

Run this prompt **before** `crawl-spoke-stack.md` — the spoke stack prompt
assumes `config.to_lambda_env()` and SSM-backed config already exist.
