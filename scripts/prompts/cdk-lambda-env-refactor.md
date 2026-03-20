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

### `.env.staging` becomes the single source of truth

```bash
ENVIRONMENT=staging

# LLM model routing
LLM_MODEL__CHUNKING=us.anthropic.claude-haiku-4-5-20250514-v1:0
LLM_MODEL__SUMMARIZER=us.anthropic.claude-sonnet-4-6-20250514-v1:0

# Feature flags
PRO_ENABLED=false

# Infrastructure — SSM parameter names (resolved at Lambda cold start)
DB_SECRET_PARAM_NAME=/steampulse/staging/data/db-secret-arn
SFN_PARAM_NAME=/steampulse/staging/compute/sfn-arn
STEP_FUNCTIONS_PARAM_NAME=/steampulse/staging/compute/sfn-arn
APP_CRAWL_QUEUE_PARAM_NAME=/steampulse/staging/messaging/app-crawl-queue-url
REVIEW_CRAWL_QUEUE_PARAM_NAME=/steampulse/staging/messaging/review-crawl-queue-url
STEAM_API_KEY_PARAM_NAME=/steampulse/staging/data/steam-api-key-secret-arn
ASSETS_BUCKET_PARAM_NAME=/steampulse/staging/data/assets-bucket-name
GAME_EVENTS_TOPIC_PARAM_NAME=/steampulse/staging/messaging/game-events-topic-arn
CONTENT_EVENTS_TOPIC_PARAM_NAME=/steampulse/staging/messaging/content-events-topic-arn
SYSTEM_EVENTS_TOPIC_PARAM_NAME=/steampulse/staging/messaging/system-events-topic-arn
```

`.env.production` is identical except `ENVIRONMENT=production` and paths
use `/steampulse/production/...`.

### Lambdas resolve SSM at runtime via Powertools

Config fields hold SSM parameter names (values starting with `/`). Each
Lambda resolves only the ones it needs using Powertools `get_parameter()` —
cached, one-liner. Config itself is a pure data class with no SSM awareness.

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

### SSM resolution pattern — in Lambda code, NOT in config

`SteamPulseConfig` fields hold SSM parameter **names** (e.g.,
`/steampulse/staging/data/db-secret-arn`). Each Lambda resolves only the
params it actually uses, via Powertools:

```python
from aws_lambda_powertools.utilities.parameters import get_parameter

_config = SteamPulseConfig()

# Resolve only the SSM params this Lambda needs — cached 5 min by default
db_secret_arn = get_parameter(_config.DB_SECRET_PARAM_NAME)
sfn_arn = get_parameter(_config.SFN_PARAM_NAME)
```

**Why this is better than bulk resolution in config:**
- Each Lambda resolves only what it uses (analysis Lambda doesn't fetch queue URLs)
- Powertools caches with 5-minute TTL — free on warm invocations
- No boto3 in config.py — config stays a pure data class
- No `model_validator` complexity, no CDK-vs-Lambda detection hacks

### Lambda handler changes

Every handler that reads infrastructure ARNs/URLs from config needs to resolve
via `get_parameter()`. Example for `crawler/handler.py`:

```python
# Before:
_config = SteamPulseConfig()
_sqs = boto3.client("sqs")
_crawl_service = CrawlService(
    ...
    review_queue_url=_config.REVIEW_CRAWL_QUEUE_PARAM_NAME,  # was a real URL
    sfn_arn=_config.SFN_PARAM_NAME,                          # was a real ARN
    ...
)

# After:
from aws_lambda_powertools.utilities.parameters import get_parameter

_config = SteamPulseConfig()
_crawl_service = CrawlService(
    ...
    review_queue_url=get_parameter(_config.REVIEW_CRAWL_QUEUE_PARAM_NAME),
    sfn_arn=get_parameter(_config.SFN_PARAM_NAME),
    ...
)
```

Apply the same pattern in every handler that uses infrastructure config fields.
Fields that are NOT SSM paths (LLM_MODEL, PRO_ENABLED, ENVIRONMENT, etc.)
are used directly — no `get_parameter()` needed.

### 2. CDK stacks — add missing SSM parameters

Some infrastructure values are already published to SSM. Add the missing ones:

**`infra/stacks/data_stack.py`** — add:
```python
ssm.StringParameter(self, "DbSecretArnParam",
    parameter_name=f"/steampulse/{env}/data/db-secret-arn",
    string_value=self.db_secret.secret_arn,
)
ssm.StringParameter(self, "SteamApiKeySecretArnParam",
    parameter_name=f"/steampulse/{env}/data/steam-api-key-secret-arn",
    string_value=self.steam_api_key_secret.secret_arn,
)
ssm.StringParameter(self, "AssetsBucketNameParam",
    parameter_name=f"/steampulse/{env}/data/assets-bucket-name",
    string_value=self.assets_bucket.bucket_name,
)
```

**`infra/stacks/messaging_stack.py`** — add queue URL params (currently only
publishes ARNs):
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
`/steampulse/{env}/compute/sfn-arn`. Verify the path matches what's in
`.env.staging`.

### 3. CDK stacks — replace all `environment=` blocks

Every Lambda becomes:

```python
environment=config.to_lambda_env(
    POWERTOOLS_SERVICE_NAME="crawler",
    POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
),
```

The only overrides are non-config keys like `POWERTOOLS_*`, `PORT`, `NODE_ENV`.
All infrastructure ARNs/URLs come from the config (which holds SSM param names
that resolve at Lambda runtime).

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

**`lambda_stack.py` — AppCrawler:**
```python
environment=config.to_lambda_env(
    POWERTOOLS_SERVICE_NAME="app-crawler",
    POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
),
```

Delete the `common_env` dict — no longer needed.

Same pattern for ReviewCrawler, CatalogRefresher, DbLoaderFn.

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

Add this once per role (crawler_role, api_role, analysis_role, etc.).
Wildcarded to `/steampulse/{env}/*` — minimal blast radius.

### 5. Update `.env.staging` and `.env.production`

Replace placeholder values with SSM parameter names:

**`.env.staging`:**
```bash
ENVIRONMENT=staging

# LLM model routing
LLM_MODEL__CHUNKING=us.anthropic.claude-haiku-4-5-20250514-v1:0
LLM_MODEL__SUMMARIZER=us.anthropic.claude-sonnet-4-6-20250514-v1:0

# Feature flags
PRO_ENABLED=false

# Infrastructure — SSM param names (resolved at Lambda cold start)
DB_SECRET_PARAM_NAME=/steampulse/staging/data/db-secret-arn
SFN_PARAM_NAME=/steampulse/staging/compute/sfn-arn
STEP_FUNCTIONS_PARAM_NAME=/steampulse/staging/compute/sfn-arn
APP_CRAWL_QUEUE_PARAM_NAME=/steampulse/staging/messaging/app-crawl-queue-url
REVIEW_CRAWL_QUEUE_PARAM_NAME=/steampulse/staging/messaging/review-crawl-queue-url
STEAM_API_KEY_PARAM_NAME=/steampulse/staging/data/steam-api-key-secret-arn
ASSETS_BUCKET_PARAM_NAME=/steampulse/staging/data/assets-bucket-name
GAME_EVENTS_TOPIC_PARAM_NAME=/steampulse/staging/messaging/game-events-topic-arn
CONTENT_EVENTS_TOPIC_PARAM_NAME=/steampulse/staging/messaging/content-events-topic-arn
SYSTEM_EVENTS_TOPIC_PARAM_NAME=/steampulse/staging/messaging/system-events-topic-arn
```

**`.env.production`:**
Same but `ENVIRONMENT=production` and `/steampulse/production/...` paths.

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
        DB_SECRET_PARAM_NAME="/steampulse/staging/data/db-secret-arn",
        SFN_PARAM_NAME="x", APP_CRAWL_QUEUE_PARAM_NAME="x",
        REVIEW_CRAWL_QUEUE_PARAM_NAME="x", STEAM_API_KEY_PARAM_NAME="x",
        ASSETS_BUCKET_PARAM_NAME="x", STEP_FUNCTIONS_PARAM_NAME="x",
        GAME_EVENTS_TOPIC_PARAM_NAME="x", CONTENT_EVENTS_TOPIC_PARAM_NAME="x",
        SYSTEM_EVENTS_TOPIC_PARAM_NAME="x",
    )
    env = config.to_lambda_env()
    assert env["ENVIRONMENT"] == "staging"
    assert env["LLM_MODEL__chunking"] == "haiku"
    assert env["LLM_MODEL__summarizer"] == "sonnet"
    assert env["PRO_ENABLED"] == "false"
    assert env["REVIEW_ELIGIBILITY_THRESHOLD"] == "500"
    # SSM param names pass through as-is (resolved by Lambda, not config)
    assert env["DB_SECRET_PARAM_NAME"] == "/steampulse/staging/data/db-secret-arn"


def test_to_lambda_env_overrides_applied():
    config = SteamPulseConfig(
        ENVIRONMENT="staging",
        LLM_MODEL={"chunking": "h", "summarizer": "s"},
        DB_SECRET_PARAM_NAME="x", SFN_PARAM_NAME="x", APP_CRAWL_QUEUE_PARAM_NAME="x",
        REVIEW_CRAWL_QUEUE_PARAM_NAME="x", STEAM_API_KEY_PARAM_NAME="x",
        ASSETS_BUCKET_PARAM_NAME="x", STEP_FUNCTIONS_PARAM_NAME="x",
        GAME_EVENTS_TOPIC_PARAM_NAME="x", CONTENT_EVENTS_TOPIC_PARAM_NAME="x",
        SYSTEM_EVENTS_TOPIC_PARAM_NAME="x",
    )
    env = config.to_lambda_env(POWERTOOLS_SERVICE_NAME="test", PORT="8080")
    assert env["POWERTOOLS_SERVICE_NAME"] == "test"
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
