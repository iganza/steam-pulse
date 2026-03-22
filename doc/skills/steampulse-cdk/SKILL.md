---
name: steampulse-cdk
description: SteamPulse CDK patterns, stack structure, and mandatory rules. Use this when writing or modifying any CDK infrastructure code in the infra/ directory.
---

## Stack Inventory

All stacks live in `infra/stacks/`. They are composed in `infra/application_stage.py` and deployed via `infra/pipeline_stack.py` (self-mutating CDK Pipelines).

| Stack | File | What it owns |
|---|---|---|
| CommonStack | `common_stack.py` | LibraryLayer (shared Lambda layer from `src/library-layer`) |
| NetworkStack | `network_stack.py` | VPC, subnets, NAT (FckNatInstanceProvider), security groups |
| DataStack | `data_stack.py` | RDS PostgreSQL + S3 bucket. `termination_protection=True` — never destroy. |
| SqsStack | `sqs_stack.py` | SQS queues + DLQs (app-crawl-queue, review-crawl-queue) |
| LambdaStack | `lambda_stack.py` | Crawler Lambdas (AppCrawler, ReviewCrawler) + EventBridge schedules |
| AnalysisStack | `analysis_stack.py` | Analysis Lambda + Step Functions EXPRESS state machine |
| AppStack | `app_stack.py` | FastAPI Lambda (Lambda Web Adapter) + Function URL + CloudFront + Route53 + ACM |
| FrontendStack | `frontend_stack.py` | Next.js Lambda (OpenNext) + CloudFront behaviour |
| DeliveryStack | `delivery_stack.py` | Static assets S3 + CloudFront distribution |
| MonitoringStack | `monitoring_stack.py` | CloudWatch via cdk-monitoring-constructs |

## Mandatory CDK Rules

1. **No physical resource names** — let CDK generate names to avoid CloudFormation naming conflicts. Exception: `pipeline_name="steampulse"` on CodePipeline only (singleton, humans need to find it in Console).

2. **No env var lookups inside constructs** — pass all config as constructor props or read from CDK context. Never `os.getenv()` inside a stack class.

3. **Secrets in Secrets Manager, referenced by ARN** — never embed secret values in environment variables or CDK code. Pass `secret.secret_arn` as an env var; Lambda fetches the value at runtime via `boto3`.

4. **DataStack has `termination_protection=True`** — never remove this. RDS and S3 cannot be accidentally deleted by CDK.

5. **GitHub source via CodeStar Connection only** — use `CodePipelineSource.connection()`, never a PAT token.

6. **Two environments: staging and production**
   - Staging: auto-deploys on every push to `main`. CloudFront URL only — no custom domain, no ACM cert, no Route53 records.
   - Production: manual `ManualApprovalStep` gate in the pipeline before deploy. ACM cert (us-east-1) + CloudFront alias + Route53 A record for `steampulse.io`.
   - Gate production changes behind `is_production: bool` prop — never use `stage == "production"` string comparisons in construct logic.

7. **Monitoring via cdk-monitoring-constructs only** — never write raw CloudWatch alarms or dashboards by hand. Import `cdk-monitoring-constructs` (npm) and use its fluent API.

8. **EventBridge rules deploy with `enabled=False`** — all scheduled rules are off by default. Enable manually after the initial seed is complete and the site is live.

## Stack Props Pattern

Every stack receives resources as typed constructor props — never use SSM lookups for stack-to-stack resource sharing (except model IDs which are runtime config, not CDK objects).

```python
class MyStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        intra_sg: ec2.ISecurityGroup,
        db_secret: secretsmanager.ISecret,
        library_layer: lambda_.ILayerVersion,
        stage: str = "staging",
        is_production: bool = False,
        **kwargs: object,
    ) -> None:
```

## Lambda Patterns

All Lambdas follow this pattern:

```python
lambda_.Function(
    self, "MyFn",
    runtime=lambda_.Runtime.PYTHON_3_12,
    handler="lambda_functions.module.handler.handler",
    code=lambda_.Code.from_asset("src/lambda-functions"),
    layers=[library_layer],          # always include LibraryLayer
    role=role,
    vpc=vpc,
    vpc_subnets=ec2.SubnetSelection(
        subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS if is_production
                    else ec2.SubnetType.PUBLIC
    ),
    allow_public_subnet=True,        # required for staging public subnets
    security_groups=[intra_sg],
    timeout=cdk.Duration.minutes(N),
    memory_size=1024,
    environment={...},
    log_group=log_group,             # always attach a named log group
)
```

Staging uses PUBLIC subnets (free internet egress). Production uses PRIVATE_WITH_EGRESS (NAT).

## IAM Pattern

Create one shared role per stack, not one role per Lambda:

```python
role = iam.Role(
    self, "CrawlerRole",
    assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
    managed_policies=[
        iam.ManagedPolicy.from_aws_managed_policy_name(
            "service-role/AWSLambdaVPCAccessExecutionRole"
        ),
    ],
)
role.add_to_policy(iam.PolicyStatement(
    actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
    resources=[db_secret.secret_arn],
))
```

For Bedrock access:
```python
role.add_to_policy(iam.PolicyStatement(
    actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
    resources=["*"],
))
```

## NAT Configuration

Use `FckNatInstanceProvider` for BOTH staging and production. Never use CDK's built-in `NatInstanceProviderV2` with `LookupMachineImage` — it fails in CloudFormation due to IAM role creation timing.

```python
from fck_nat.fck_nat_cdk import FckNatInstanceProvider

nat = FckNatInstanceProvider(instance_type=ec2.InstanceType("t3.nano"))
vpc = ec2.Vpc(self, "Vpc",
    nat_gateway_provider=nat,
    nat_gateways=2 if is_production else 1,
)
```

## Step Functions

- **EXPRESS** workflow for real-time single-game analysis (fast, cheap, 15-min max).
- **STANDARD** workflow for Bedrock Batch Inference pipeline (hours-long, needs Wait states).
- Always attach a log group. Use `LogLevel.ERROR` for Express, `LogLevel.ALL` for Standard during development.
- Add retry on every `LambdaInvoke` task: `max_attempts=2, interval=10s, backoff_rate=2`.

## Log Groups

Every Lambda and state machine gets a dedicated log group with `RetentionDays.ONE_WEEK` and `RemovalPolicy.DESTROY`. Never rely on auto-created log groups.

```python
log_group = logs.LogGroup(
    self, "MyLogs",
    retention=logs.RetentionDays.ONE_WEEK,
    removal_policy=cdk.RemovalPolicy.DESTROY,
)
```

## SSM Parameters (runtime config only)

SSM is only used for values that are runtime configuration, not CDK objects. Currently:
- `/steampulse/{stage}/llm/haiku-model` — Bedrock model ID for Haiku
- `/steampulse/{stage}/llm/sonnet-model` — Bedrock model ID for Sonnet
- `/steampulse/{stage}/steam-api-key-secret-arn` — ARN of the Steam API key secret

Read these with `ssm.StringParameter.value_for_string_parameter()` and pass the resolved token as a Lambda environment variable.
