# Cost trim — round 4 (spoke region collapse + CloudWatch cleanup)

## Context

After `cost-trim-round-3.md` shipped (ARM lambdas, SpokeIngest 384MB, alarm trim), daily AWS spend on **2026-04-25** was **$5.47** — the lowest of the past week (down from a $12.35 peak on 4/21). A fresh Cost Explorer sweep on 2026-04-26 showed the cross-region spoke architecture is now ~50% of remaining spend, and one CloudWatch dashboard line is a self-inflicted free-tier miss.

Top remaining drivers (2026-04-25 daily):

| Service | $/day | Note |
|---|---:|---|
| Lambda | $2.18 | $1.40 in USW2; $0.78 across 11 other spoke regions |
| RDS | $1.10 | t4g.small + GP3 — structurally fixed |
| CloudWatch | $1.02 | $0.65/day per-region `MetricMonitorUsage` (custom metrics) + $0.10/day dashboard + $0.21/day alarms |
| S3, VPC, SQS, others | <$0.30 each | Mostly structural |

Three levers in this round, all under the spoke/CloudWatch umbrella:

1. **12 → 6 spoke regions** (geographic-spread set chosen)
2. **Strip custom CloudWatch metrics from spoke handlers** (powertools `Metrics` emissions)
3. **Trim `SteamPulse-Production` dashboard from 187 metrics → <50** to land in the free tier

Items tagged: `[code]` (Claude), `[manual]` (user, often `cdk destroy`-style), `[decide→code]`.

---

## Tier 1 — spoke region collapse (12 → 6)

### T1-A. Reduce `SPOKE_REGIONS` to 6 `[code + manual destroy]`

**Decision (locked):** Keep these 6 regions for geographic distinct-IP coverage of Steam's per-IP appdetails rate limit:

```
us-west-2     (hub + spoke #1, NA-West)
us-east-1     (NA-East)
eu-west-1     (EU-West, Ireland)
eu-central-1  (EU-Central, Frankfurt)
ap-northeast-1 (APAC-North, Tokyo)
ap-southeast-1 (APAC-South, Singapore)
```

**Drop these 6:**

```
us-east-2, ca-central-1, eu-north-1, ap-south-1, ap-southeast-2, ap-northeast-2
```

**Files (code):**

- `.env.production` — replace `SPOKE_REGIONS=...` line with the 6-region list above. Update `SPOKE_CRAWL_QUEUE_URLS` to the matching subset (regenerate from the 6 region codes; the format is `https://sqs.{region}.amazonaws.com/{account}/steampulse-spoke-crawl-{region}-production`).
- `.env.staging` — same shape if staging uses a similar list (verify; staging may already be empty).
- `infra/application_stage.py` — find the loop that instantiates a `SpokeStack` per region and confirm it iterates `config.spoke_region_list`. Should be no code change here, but verify it picks up the trimmed list.

**Manual (user) — destroy the 6 dropped regional stacks before/after deploy:**

For each region in `us-east-2 ca-central-1 eu-north-1 ap-south-1 ap-southeast-2 ap-northeast-2`:

```bash
# Sequence per region:
# 1. Drain the regional SQS crawl queue first (avoid losing in-flight work)
aws sqs purge-queue \
  --queue-url "https://sqs.${R}.amazonaws.com/052475889199/steampulse-spoke-crawl-${R}-production" \
  --region "$R"

# 2. Destroy the regional spoke stack
cdk destroy SteamPulse-Production-Spoke-${R} --force

# 3. Confirm no orphan resources
aws lambda list-functions --region "$R" \
  --query 'Functions[?starts_with(FunctionName, `SteamPulse-Production`)].FunctionName' \
  --output text
aws sqs list-queues --region "$R" --queue-name-prefix steampulse-
aws logs describe-log-groups --region "$R" \
  --log-group-name-prefix /aws/lambda/SteamPulse-Production --query 'logGroups[].logGroupName' --output text
```

> ⚠️ **Destructive — user runs this, not Claude.** Per `feedback_no_deploy.md` and `feedback_no_commit_push.md`, Claude does not run `cdk destroy` or `cdk deploy`. Verify queue is drained first; in-flight messages will be lost.

**Verification (post-deploy, post-destroy):**

```bash
# 1. Hub still talks to exactly 6 spoke queues
aws lambda get-function-configuration \
  --function-name SteamPulse-Production-Compute-CrawlerFn \
  --query 'Environment.Variables.SPOKE_CRAWL_QUEUE_URLS' --output text \
  | tr ',' '\n' | wc -l   # expect 6

# 2. No new metrics appearing in dropped regions over the next hour
aws cloudwatch list-metrics --region us-east-2 --namespace SteamPulse \
  --query 'Metrics[*].MetricName' --output text   # expect empty after retention window

# 3. Cost Explorer 7 days post-deploy
aws ce get-cost-and-usage --time-period Start=YYYY-MM-DD,End=YYYY-MM-DD \
  --granularity DAILY --metrics UnblendedCost \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":["AWS Lambda","AmazonCloudWatch"]}}' \
  --group-by Type=DIMENSION,Key=REGION
```

**Savings:** ~$0.79/day = **~$24/mo** (Lambda compute $13 + CloudWatch metric/alarm $11). Capacity halves but `tiered-refresh-schedule.org` shows steady-state demand (~888/hr) is well within 6 regions' Steam-API headroom.

---

## Tier 2 — CloudWatch custom metric strip

### T2-A. Remove powertools `Metrics` emissions from spoke handler `[code]`

**Evidence:** `src/lambda-functions/lambda_functions/crawler/spoke_handler.py:38-43,84-99,105` emits four custom metrics (`MetadataFetched`, `ReviewsFetched`, `TagsFetched`, plus the cold-start metric from `capture_cold_start_metric=True`) into the `SteamPulse` namespace, **per region**. After T1-A: 4 metrics × 6 regions = 24 metric streams. CloudWatch custom metric pricing is $0.30/metric/month for the first 10k → ~$7/mo just for these. Plus EMF emits one JSON log line per invocation, adding to log ingestion cost.

The structured logger (`Logger(service="crawler-spoke")`) already covers operational visibility — counts and outcomes are searchable in Logs Insights. The CloudWatch metrics aren't load-bearing for any current alarm (verify with `aws cloudwatch describe-alarms --region us-west-2 --query 'MetricAlarms[?Namespace==\`SteamPulse\`]'` before deleting).

**Files:**

- `src/lambda-functions/lambda_functions/crawler/spoke_handler.py`:
  - Remove `from aws_lambda_powertools import Metrics` and `from aws_lambda_powertools.metrics import MetricUnit`
  - Remove `metrics = Metrics(namespace="SteamPulse", service="crawler-spoke")` (line 40)
  - Remove `metrics.set_default_dimensions(...)` (line 43)
  - Remove `@metrics.log_metrics(capture_cold_start_metric=True)` decorator (line 105) — replace with nothing (handler is the entry point)
  - Replace each `metrics.add_metric(name=..., unit=..., value=...)` (lines 85, 92, 99) with a `logger.info(...)` line carrying the same fields. Example:
    ```python
    # before
    metrics.add_metric(name="MetadataFetched", unit=MetricUnit.Count, value=1 if ok else 0)
    # after
    logger.info("metadata_fetched", appid=req.appid, ok=ok)
    ```

- Other handlers using `Metrics` (verify each is necessary or strip too):
  - `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py`
  - `src/lambda-functions/lambda_functions/analysis/handler.py`
  - `src/lambda-functions/lambda_functions/crawler/ingest_handler.py`
  - `src/lambda-functions/lambda_functions/crawler/handler.py`
  - `src/lambda-functions/lambda_functions/genre_synthesis/prepare.py`
  - `src/lambda-functions/lambda_functions/genre_synthesis/collect.py`

  For each: confirm no alarm depends on the namespace, then remove `Metrics` use entirely. Same pattern as spoke_handler.

- `src/library-layer/library_layer/utils/steam_metrics.py` — module name suggests it may also publish metrics. Inspect; if it's just a helper and unused after the strip, delete it.

**Pyproject:** if `aws-lambda-powertools[metrics]` is the only Powertools extra used, drop `metrics` extra from `pyproject.toml` and run `poetry lock` (see `feedback_lock_files.md` — re-run for every affected package: root + nested library-layer).

**Tests:** Update tests that assert `metrics.add_metric` calls. Grep for `Metrics(` and `add_metric` in `tests/`.

**Verification:**

```bash
# 1. No new SteamPulse-namespace metrics created after deploy
aws cloudwatch list-metrics --namespace SteamPulse --region us-west-2 \
  --query 'Metrics[*].MetricName' --output text

# 2. Logs Insights still shows fetch outcomes
poetry run python scripts/logs.py refresh --env production
```

**Savings:** ~$0.65/day → ~$0.20/day (residual cold-start metric streams from non-spoke Lambdas, until they age out). **~$13/mo.** Most cost falls off within a week as old metric streams stop being queried.

---

## Tier 3 — dashboard trim (187 → <50 metrics, $3/mo)

### T3-A. Trim `SteamPulse-Production` dashboard below the free tier `[code]`

**Evidence:** `aws cloudwatch get-dashboard --dashboard-name SteamPulse-Production` shows 90 metric widgets containing **187 metric expressions**. CloudWatch's free tier is "first 3 dashboards, up to 50 metrics each." Crossing 50 metrics flips this dashboard to billed → **$3/mo flat**. The `test` dashboard (2.7KB) is small and stays free regardless.

The dashboard is generated by `cdk-monitoring-constructs` `MonitoringFacade` in `infra/stacks/monitoring_stack.py:71-78`. Trimming = removing `monitor*()` calls or grouping metrics into fewer expressions.

**Approach (code):**

Open `infra/stacks/monitoring_stack.py` and audit each `monitoring.monitorXxx(...)` call. Categorize widgets into:

- **Keep** (load-bearing, on-call uses these): hub Lambda errors, hub Lambda duration p99, RDS CPU + free-storage, SQS DLQ depth (per queue), one ingest-throughput chart.
- **Drop** (nice-to-have, redundant with logs/alarms): per-spoke duration breakdowns, per-spoke throttles, IteratorAge already covered by alarm, Lambda concurrency charts (correctable from logs), per-region cold-start counts.

**Concrete target:** ≤ 45 metrics across ≤ 12 widgets, leaving 5-metric headroom under the 50 cap.

**Files:**

- `infra/stacks/monitoring_stack.py` — remove or consolidate widgets. Be aggressive; the multi-region widgets are the biggest contributors after T1-A drops 6 regions anyway.

**Verification:**

```bash
# Post-deploy, recount:
aws cloudwatch get-dashboard --dashboard-name SteamPulse-Production --output json \
  | python3 -c "import json,sys; b=json.loads(json.load(sys.stdin)['DashboardBody']); print(sum(len(w.get('properties',{}).get('metrics',[])) for w in b['widgets']))"
# expect <= 50
```

Watch the next day's `DashboardsUsageHour` line in Cost Explorer — should drop from $0.10 to $0.00.

**Savings:** **$3/mo** flat (full elimination of the dashboard line item).

---

## Intentionally out of scope

- **fck-nat × 2** (~$9/mo) — HA-correct, matches `feedback_fixed_cost_infra.md`.
- **RDS t4g.small** ($22/mo) — already smallest reasonable.
- **Tier window slackening** (S 2d→4d etc.) — separate freshness-vs-cost decision; not a cost *bug*.
- **Hub Lambda compute** — round 3 already trimmed memory and switched to ARM; further savings need traffic reduction, not config tweaks.
- **Dropping the dashboard entirely** — usability hit isn't worth $3/mo if the user actually opens it.

---

## Verification (aggregate)

7 days after Tier 1+2+3 deploy + destroys, expect (vs 2026-04-25 baseline):

| Line | Pre | Target |
|---|---:|---:|
| Daily Lambda | $2.18 | < $1.50 |
| Daily CloudWatch | $1.02 | < $0.40 |
| Daily total | $5.47 | **< $4.00** |
| Custom metrics in `SteamPulse` namespace | ~24 (post-region-cut) | 0 |
| Dashboard widgets | 90 (187 metrics) | ≤ 12 (≤ 50 metrics) |
| Active spoke regions | 12 | 6 |

```bash
aws ce get-cost-and-usage --time-period Start=YYYY-MM-DD,End=YYYY-MM-DD \
  --granularity DAILY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE
```

Aggregate potential: **~$40/mo off** ($165 → $125 run rate), no behavior change for end users; lower observability ceiling (acceptable pre-launch).

---

## Critical files

- `.env.production` — `SPOKE_REGIONS`, `SPOKE_CRAWL_QUEUE_URLS`
- `infra/application_stage.py` — verifies spoke iteration uses `config.spoke_region_list`
- `infra/stacks/monitoring_stack.py:71-78` + body — dashboard widget definitions to trim
- `src/lambda-functions/lambda_functions/crawler/spoke_handler.py:38-43,84-99,105` — strip Metrics
- `src/lambda-functions/lambda_functions/crawler/handler.py` — strip Metrics
- `src/lambda-functions/lambda_functions/crawler/ingest_handler.py` — strip Metrics
- `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py` — strip Metrics
- `src/lambda-functions/lambda_functions/analysis/handler.py` — strip Metrics
- `src/lambda-functions/lambda_functions/genre_synthesis/{prepare,collect}.py` — strip Metrics
- `src/library-layer/library_layer/utils/steam_metrics.py` — inspect, likely delete
- `pyproject.toml` (root + `src/library-layer`) — drop `metrics` extra if unused
