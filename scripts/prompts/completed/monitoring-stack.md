# Comprehensive Monitoring Stack + Resource Tagging

## Problem

SteamPulse has no operational monitoring. The `monitoring_stack.py` is disabled and only covers Steam API custom metrics. With 12 spoke regions, a multi-stage crawl pipeline, LLM analysis, and a public API, we have zero visibility into system health. No alarms, no dashboards, no cross-region view.

## Goal

A single CloudWatch dashboard showing full system health, with alarms on every failure mode, consistent resource tagging for discovery and cost allocation, and cross-region spoke health — all without CDK cross-stack references.

## Architecture Constraints

- **Must use `cdk-monitoring-constructs`** — never write raw CloudWatch alarms or dashboards by hand
- **No CDK cross-stack references** — monitoring stack must NOT import Lambda/Queue/Topic CDK objects from other stacks
- **Discovery via SSM parameters** — use `ssm.StringParameter.value_for_string_parameter()` to encode resource ARN lookups as `{{resolve:ssm:...}}` CloudFormation dynamic references at synth time; the actual SSM values are resolved by CloudFormation at deploy/runtime. This avoids `Fn::ImportValue` and CDK cross-stack dependencies. Then use `from_function_arn()` / `from_queue_arn()` to get `IFunction` / `IQueue` references for the monitoring library.
- **Cross-region alarms live in spoke_stack.py** — CloudWatch alarms cannot span regions. Each spoke gets a local SNS alarm topic with alarms in the same region as the metric.
- **Cross-region dashboard IS possible** — CloudWatch dashboards can show metrics from any region by specifying `region` on `Metric` objects.
- **Tags are for cost allocation and operational identification** — not the primary discovery mechanism for `cdk-monitoring-constructs`.

## Design

### Part 1: Resource Tagging

Add consistent tags to ALL resources across all stacks.

**Tag scheme:**

| Tag Key | Values | Purpose |
|---|---|---|
| `steampulse:environment` | `staging` / `production` | Cost allocation, filtering |
| `steampulse:service` | `crawler`, `api`, `analysis`, `ingest`, `spoke`, `frontend`, `admin`, `email`, `batch`, `migration`, `database` | Identify service owner |
| `steampulse:tier` | `critical`, `standard`, `internal` | Alarm severity routing |

**Where to apply:**

- **`infra/application_stage.py`** — Stage-level `steampulse:environment` tag (inherited by ALL resources in all stacks):
  ```python
  cdk.Tags.of(self).add("steampulse:environment", environment)
  ```

- **`infra/stacks/compute_stack.py`** — Per-Lambda `steampulse:service` + `steampulse:tier` tags:
  - CrawlerFn: service=crawler, tier=critical
  - SpokeIngestFn: service=ingest, tier=critical
  - ApiFn: service=api, tier=critical
  - FrontendFn: service=frontend, tier=critical
  - AnalysisFn: service=analysis, tier=standard
  - EmailFn: service=email, tier=standard
  - AdminFn: service=admin, tier=internal
  - MigrationFn: service=migration, tier=internal

- **`infra/stacks/messaging_stack.py`** — Per-queue/topic `steampulse:service` tags

- **`infra/stacks/spoke_stack.py`** — service=spoke, tier=critical

- **`infra/stacks/data_stack.py`** — service=database, tier=critical

### Part 2: Missing SSM Parameters

Some resources don't yet have SSM params for monitoring discovery. Add:

**`infra/stacks/compute_stack.py`:**
- `/steampulse/{env}/compute/frontend-fn-arn` → `frontend_fn.function_arn`
- `/steampulse/{env}/compute/email-fn-arn` → `email_fn.function_arn`
- `/steampulse/{env}/compute/admin-fn-arn` → `admin_fn.function_arn`

**Already exist (no changes needed):**
- `/steampulse/{env}/compute/api-fn-arn`
- `/steampulse/{env}/compute/crawler-fn-arn`
- `/steampulse/{env}/compute/analysis-fn-arn`
- `/steampulse/{env}/compute/spoke-ingest-fn-arn`
- `/steampulse/{env}/compute/sfn-arn`
- `/steampulse/{env}/compute/migration-fn-arn`
- `/steampulse/{env}/compute/admin-fn-name`

**`infra/stacks/messaging_stack.py`:**
- `/steampulse/{env}/messaging/spoke-results-dlq-arn` → `spoke_results_dlq.queue_arn`
- `/steampulse/{env}/messaging/email-queue-arn` → `email_queue.queue_arn`
- `/steampulse/{env}/messaging/email-dlq-arn` → `email_dlq.queue_arn`

**Already exist (no changes needed):**
- `/steampulse/{env}/messaging/app-crawl-queue-arn`
- `/steampulse/{env}/messaging/review-crawl-queue-arn`
- `/steampulse/{env}/messaging/app-crawl-dlq-arn`
- `/steampulse/{env}/messaging/review-crawl-dlq-arn`
- `/steampulse/{env}/messaging/spoke-results-queue-arn`

**`infra/stacks/data_stack.py`:**
- `/steampulse/{env}/data/db-instance-identifier` → DB instance identifier (production) or cluster identifier (staging)

### Part 3: Monitoring Stack Rewrite (`infra/stacks/monitoring_stack.py`)

Full rewrite. The stack discovers all resources via SSM and builds a comprehensive dashboard + alarms.

**Resource lookup pattern (repeated for each resource):**
```python
api_fn_arn = ssm.StringParameter.value_for_string_parameter(
    self, f"/steampulse/{env}/compute/api-fn-arn"
)
api_fn = lambda_.Function.from_function_arn(self, "ApiFnRef", api_fn_arn)
```

**Dashboard sections:**

1. **Crawler Pipeline**
   - Lambda monitoring: CrawlerFn, SpokeIngestFn (errors, throttles, duration, invocations)
   - Queue monitoring: app-crawl + DLQ, review-crawl + DLQ, spoke-results + DLQ (depth, age, DLQ count)
   - Custom business metrics: SpokeDispatched, GamesUpserted, ReviewsUpserted, TagsIngested, CatalogRefreshRun

2. **API & Frontend**
   - Lambda monitoring: ApiFn (errors, throttles, p99 latency, invocations)
   - Lambda monitoring: FrontendFn (errors, duration)

3. **Cross-Region Spoke Health**
   - Per-region custom metrics: MetadataFetched, ReviewsFetched, TagsFetched (using `Metric(region=r)` for cross-region display)
   - Per-region spoke crawl queue depth (cross-region `Metric` objects)
   - Steam API health: SteamApiRequests, SteamApiRetries, SteamApiErrors, SteamApiLatency p99

4. **Supporting Services**
   - Lambda monitoring: EmailFn (errors, invocations)
   - Queue monitoring: email + DLQ

**Alarm thresholds:**

| Resource | Alarm | Threshold | Period |
|---|---|---|---|
| All critical Lambdas (crawler, ingest, api, frontend) | Error count | > 0 | 5 min |
| All critical Lambdas | Throttle count | > 0 | 5 min |
| ApiFn | p99 duration | > 10s | 5 min |
| CrawlerFn | p99 duration | > 300s (near 10-min timeout) | 5 min |
| All DLQs | Messages visible | > 0 (any message in DLQ is an alert) | 1 min |
| Main queues (app-crawl, review-crawl, spoke-results) | Age of oldest message | > 3600s (consumer stuck) | 5 min |

**All alarms route to an SNS alarm topic** with `CfnOutput` for the ARN so ops can subscribe their email.

### Part 4: Spoke Alarms (`infra/stacks/spoke_stack.py`)

CloudWatch alarms must live in the same region as the metric. Add to each spoke stack:

1. **Local SNS alarm topic** per spoke region
2. **MonitoringFacade with alarms only** (no dashboard — dashboard is central in primary region):
   - Lambda error count > 0
   - Lambda throttle count > 0
   - Spoke crawl queue DLQ messages > 0
   - Spoke crawl queue age of oldest message > 3600s
3. **CfnOutput** the spoke alarm topic ARN so ops can subscribe their email

### Part 5: Enable in `application_stage.py`

- Uncomment `MonitoringStack`
- Add `monitoring.add_dependency(compute)` and `monitoring.add_dependency(messaging)` (logical ordering — SSM params must exist before monitoring stack resolves them)

## Scope of Changes

| File | Changes |
|---|---|
| `infra/application_stage.py` | Stage-level env tag, uncomment MonitoringStack, add dependencies |
| `infra/stacks/monitoring_stack.py` | Full rewrite — SSM discovery, dashboard sections, alarms |
| `infra/stacks/compute_stack.py` | Add missing SSM params (frontend-fn-arn, email-fn-arn, admin-fn-arn), add per-Lambda tags |
| `infra/stacks/messaging_stack.py` | Add missing SSM params (spoke-results-dlq-arn, email-queue-arn, email-dlq-arn), add per-queue tags |
| `infra/stacks/data_stack.py` | Add DB identifier SSM param, add tags |
| `infra/stacks/spoke_stack.py` | Add local MonitoringFacade + alarm topic + tags |

## Existing Custom Metrics Reference

All in `SteamPulse` namespace, dimension `{environment: staging|production}`:

| Metric Name       | Emitted By                   | Unit         |
|-------------------|------------------------------|--------------|
| SteamApiRequests  | steam_source.py (all spokes) | Count        |
| SteamApiLatency   | steam_source.py (all spokes) | Milliseconds |
| SteamApiRetries   | steam_source.py (all spokes) | Count        |
| SteamApiErrors    | steam_source.py (all spokes) | Count        |
| SpokeDispatched   | crawler/handler.py           | Count        |
| CatalogRefreshRun | crawler/handler.py           | Count        |
| GamesUpserted     | crawler/ingest_handler.py    | Count        |
| TagsIngested      | crawler/ingest_handler.py    | Count        |
| ReviewsUpserted   | crawler/ingest_handler.py    | Count        |
| MetadataFetched   | crawler/spoke_handler.py     | Count        |
| ReviewsFetched    | crawler/spoke_handler.py     | Count        |
| TagsFetched       | crawler/spoke_handler.py     | Count        |
| ReportsGenerated  | analysis/handler.py          | Count        |
|                   |                              |              |

## Existing SSM Parameters Reference

**Compute (`/steampulse/{env}/compute/`):**
- `api-fn-arn`, `crawler-fn-arn`, `analysis-fn-arn`, `spoke-ingest-fn-arn`
- `sfn-arn`, `migration-fn-arn`, `admin-fn-name`
- `api-fn-url`, `library-layer-arn`

**Messaging (`/steampulse/{env}/messaging/`):**
- `app-crawl-queue-arn`, `app-crawl-queue-url`, `app-crawl-dlq-arn`
- `review-crawl-queue-arn`, `review-crawl-queue-url`, `review-crawl-dlq-arn`
- `spoke-results-queue-arn`, `spoke-results-queue-url`
- `game-events-topic-arn`, `content-events-topic-arn`, `system-events-topic-arn`
- `email-queue-url`

**Spokes (`/steampulse/{env}/spokes/{region}/`):**
- `status`, `crawl-queue-url`

## Spoke Regions

- **Staging:** us-west-2, us-east-1 (2 regions)
- **Production:** us-west-2, us-east-1, us-east-2, ca-central-1, eu-west-1, eu-central-1, eu-north-1, ap-south-1, ap-southeast-1, ap-northeast-1, ap-northeast-2, ap-southeast-2 (12 regions)

Each spoke has: Lambda (`steampulse-spoke-crawler-{region}-{env}`), SQS queue (`steampulse-spoke-crawl-{region}-{env}`), DLQ, log group (`/steampulse/{env}/spoke/{region}`)

## Verification

1. `poetry run cdk synth` — no errors
2. `poetry run pytest tests/infra/` — CDK assertion tests pass
3. Deploy to staging: `bash scripts/deploy.sh --env staging`
4. Verify dashboard appears in CloudWatch console with all sections populated
5. Verify spoke alarm topics exist in each spoke region
6. Verify tags appear on resources in AWS Resource Groups console
