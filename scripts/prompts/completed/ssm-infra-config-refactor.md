# SteamPulse — Refactor: ARN/URL References via SSM Parameter Store

## Context

SteamPulse Lambda functions currently receive infrastructure ARNs and URLs as direct
environment variables set by CDK at deploy time. For example:

```python
# lambda_stack.py (current)
common_env = {
    "DB_SECRET_ARN": db_secret.secret_arn,
    "SFN_ARN": state_machine.state_machine_arn,
    "STEAM_API_KEY_SECRET_ARN": steam_api_key_secret_arn,
}

# app_stack.py (current)
environment={
    "DB_SECRET_ARN": db_secret.secret_arn,
    "STEP_FUNCTIONS_ARN": state_machine.state_machine_arn,
}
```

And `config.py` stores these as direct fields:

```python
class SteamPulseConfig(BaseSettings):
    DB_SECRET_ARN: str = ""
    SFN_ARN: str = ""
    APP_CRAWL_QUEUE_URL: str = ""
    REVIEW_CRAWL_QUEUE_URL: str = ""
    STEAM_API_KEY_SECRET_ARN: str = ""
    ASSETS_BUCKET_NAME: str = ""
    STEP_FUNCTIONS_ARN: str = ""   # duplicate of SFN_ARN
```

## Problem

- CDK passes a different set of env vars to every Lambda — inconsistent, hard to audit
- The actual ARN values leak into Lambda environment variables (visible in AWS Console)
- `SFN_ARN` and `STEP_FUNCTIONS_ARN` are duplicates of the same value
- Empty-string defaults (`str = ""`) mean a missing ARN fails silently at call time rather than loudly at startup

## Goal

Replace direct ARN/URL environment variables with a single `ENVIRONMENT` env var.
Lambdas resolve all infrastructure references at cold start by reading from SSM
Parameter Store using well-known path conventions based on the environment.

CDK publishes every ARN/URL to SSM at deploy time. Lambdas read from SSM once on
cold start and cache the values. No more per-Lambda `environment={}` blocks full of ARNs.

---

## Target Design

### SSM Path Convention

All paths follow: `/steampulse/{env}/{resource-name}`

| SSM Path | Value | Written by |
|---|---|---|
| `/steampulse/{env}/db-secret-arn` | RDS secret ARN | DataStack |
| `/steampulse/{env}/sfn-arn` | Analysis state machine ARN | AnalysisStack |
| `/steampulse/{env}/app-crawl-queue-url` | SQS queue URL | SqsStack |
| `/steampulse/{env}/review-crawl-queue-url` | SQS queue URL | SqsStack |
| `/steampulse/{env}/steam-api-key-secret-arn` | Steam API key secret ARN | DataStack / manual |
| `/steampulse/{env}/assets-bucket-name` | S3 bucket name | AppStack |
| `/steampulse/{env}/llm/haiku-model` | Bedrock model ID | Already exists |
| `/steampulse/{env}/llm/sonnet-model` | Bedrock model ID | Already exists |

### config.py (target)

```python
class SteamPulseConfig(BaseSettings):
    # The ONLY env var CDK needs to set on every Lambda
    ENVIRONMENT: Literal["staging", "production"] = "staging"

    # LLM overrides (optional — fall back to SSM if not set)
    HAIKU_MODEL: str = _HAIKU_DEFAULT
    SONNET_MODEL: str = _SONNET_DEFAULT

    # Feature flags
    PRO_ENABLED: bool = False

    # Powertools
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # SSM path templates — resolved at runtime via get_infra()
    @property
    def ssm_prefix(self) -> str:
        return f"/steampulse/{self.ENVIRONMENT}"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"
```

### InfraConfig (new — loaded from SSM at cold start)

Create `library_layer/infra_config.py`:

```python
from dataclasses import dataclass
import boto3

@dataclass(frozen=True)
class InfraConfig:
    db_secret_arn: str
    sfn_arn: str
    app_crawl_queue_url: str
    review_crawl_queue_url: str
    steam_api_key_secret_arn: str
    assets_bucket_name: str

    @classmethod
    def from_ssm(cls, env: str) -> InfraConfig:
        """Load all infrastructure references from SSM in a single batch call."""
        ssm = boto3.client("ssm")
        prefix = f"/steampulse/{env}"
        names = [
            f"{prefix}/db-secret-arn",
            f"{prefix}/sfn-arn",
            f"{prefix}/app-crawl-queue-url",
            f"{prefix}/review-crawl-queue-url",
            f"{prefix}/steam-api-key-secret-arn",
            f"{prefix}/assets-bucket-name",
        ]
        resp = ssm.get_parameters(Names=names, WithDecryption=False)
        params = {p["Name"]: p["Value"] for p in resp["Parameters"]}

        missing = set(names) - set(params)
        if missing:
            raise RuntimeError(f"Missing SSM parameters: {missing}")

        return cls(
            db_secret_arn=params[f"{prefix}/db-secret-arn"],
            sfn_arn=params[f"{prefix}/sfn-arn"],
            app_crawl_queue_url=params[f"{prefix}/app-crawl-queue-url"],
            review_crawl_queue_url=params[f"{prefix}/review-crawl-queue-url"],
            steam_api_key_secret_arn=params[f"{prefix}/steam-api-key-secret-arn"],
            assets_bucket_name=params[f"{prefix}/assets-bucket-name"],
        )
```

Note: `get_parameters` accepts up to 10 names in a single API call — no need for a loop.

### Lambda handler pattern (target)

```python
# Module-level — runs once on cold start, cached for all warm invocations
from library_layer.config import config
from library_layer.infra_config import InfraConfig

_infra = InfraConfig.from_ssm(config.ENVIRONMENT)
```

All ARN/URL references in the handler use `_infra.db_secret_arn`, `_infra.sfn_arn`, etc.

---

## CDK Changes

### Every stack: publish ARNs to SSM at deploy time

Each stack that creates a resource publishes its ARN/URL to SSM:

```python
# In DataStack (after RDS secret is created)
ssm.StringParameter(self, "DbSecretArnParam",
    parameter_name=f"/steampulse/{stage}/db-secret-arn",
    string_value=db_secret.secret_arn,
)

# In AnalysisStack (after state machine is created)
ssm.StringParameter(self, "SfnArnParam",
    parameter_name=f"/steampulse/{stage}/sfn-arn",
    string_value=machine.state_machine_arn,
)

# In SqsStack (after queues are created)
ssm.StringParameter(self, "AppCrawlQueueUrlParam",
    parameter_name=f"/steampulse/{stage}/app-crawl-queue-url",
    string_value=app_crawl_queue.queue_url,
)
ssm.StringParameter(self, "ReviewCrawlQueueUrlParam",
    parameter_name=f"/steampulse/{stage}/review-crawl-queue-url",
    string_value=review_crawl_queue.queue_url,
)

# In AppStack (after S3 bucket is created)
ssm.StringParameter(self, "AssetsBucketNameParam",
    parameter_name=f"/steampulse/{stage}/assets-bucket-name",
    string_value=assets_bucket.bucket_name,
)
```

### Every Lambda: only pass ENVIRONMENT

Replace all `environment={}` blocks that contain ARNs with a single key:

```python
# Before (current):
environment={
    "DB_SECRET_ARN": db_secret.secret_arn,
    "SFN_ARN": state_machine.state_machine_arn,
    "STEAM_API_KEY_SECRET_ARN": steam_api_key_secret_arn,
}

# After (target):
environment={
    "ENVIRONMENT": stage,
    "POWERTOOLS_SERVICE_NAME": "app-crawler",
    "POWERTOOLS_METRICS_NAMESPACE": "SteamPulse",
}
```

Model IDs (`HAIKU_MODEL`, `SONNET_MODEL`) can stay as env vars since they are already read
from SSM by CDK and passed through — or they can move to SSM too (they already have paths).

### IAM: add SSM read permission to every Lambda role

```python
role.add_to_policy(iam.PolicyStatement(
    actions=["ssm:GetParameters"],
    resources=[
        f"arn:aws:ssm:{self.region}:{self.account}:parameter/steampulse/{stage}/*"
    ],
))
```

---

## Files to Change

| File | Change |
|---|---|
| `src/library-layer/library_layer/config.py` | Remove all ARN/URL fields. Keep `ENVIRONMENT`, feature flags, model IDs. |
| `src/library-layer/library_layer/infra_config.py` | **New file.** `InfraConfig` dataclass + `from_ssm()` classmethod. |
| `src/lambda-functions/lambda_functions/*/handler.py` | Add `_infra = InfraConfig.from_ssm(config.ENVIRONMENT)` at module level. Replace all direct env var reads with `_infra.*`. |
| `infra/stacks/lambda_stack.py` | Publish queue URLs to SSM. Simplify all `environment={}` to just `ENVIRONMENT`. Add SSM read IAM policy. |
| `infra/stacks/analysis_stack.py` | Publish SFN ARN to SSM. Simplify `environment={}`. Add SSM IAM policy. |
| `infra/stacks/app_stack.py` | Publish assets bucket name to SSM. Simplify `environment={}`. Add SSM IAM policy. |
| `infra/stacks/data_stack.py` | Publish DB secret ARN to SSM. |
| `infra/stacks/sqs_stack.py` | Publish queue URLs to SSM (or do it in lambda_stack — pick one). |
| `tests/` | Update fixtures to create `InfraConfig` directly with test values instead of setting env vars. |

---

## Constraints

- Use `get_parameters` (batch, up to 10 names) — NOT `get_parameter` in a loop
- `InfraConfig` must be a frozen `dataclass` — immutable after cold start
- Raise `RuntimeError` with the list of missing parameter names if any SSM fetch fails — fail loud
- Do NOT move `HAIKU_MODEL` / `SONNET_MODEL` to `InfraConfig` — they are config, not infra references
- Do NOT move `PRO_ENABLED` or `LOG_LEVEL` to `InfraConfig`
- The existing SSM paths for model IDs (`/steampulse/{stage}/llm/haiku-model`) already exist and are read by CDK — leave them alone
- Keep `SteamPulseConfig.for_environment()` classmethod — it is used by CDK at synth time

## Definition of Done

- [ ] `config.py` has no ARN or URL fields
- [ ] `InfraConfig.from_ssm()` fetches all infra references in one SSM batch call
- [ ] Every Lambda handler initialises `_infra` at module level (cold-start cache)
- [ ] All CDK stacks publish their ARNs/URLs to SSM using the `/steampulse/{env}/` prefix
- [ ] Every Lambda `environment={}` block contains only `ENVIRONMENT` + Powertools vars
- [ ] Lambda IAM roles have `ssm:GetParameters` on `/steampulse/{stage}/*`
- [ ] All tests pass
