# Cost trim — round 4 (spoke region collapse + observability cleanup)

## Context

After `cost-trim-round-3.md` shipped (ARM lambdas, SpokeIngest 384MB, alarm trim), daily AWS spend on **2026-04-25** was **$5.47** — the lowest of the past week (down from a $12.35 peak on 4/21). A fresh Cost Explorer sweep on 2026-04-26 showed cross-region spoke architecture is now ~50% of remaining spend, and CloudWatch + observability extras account for most of the rest.

Top remaining drivers (2026-04-25 daily):

| Service | $/day | Note |
|---|---:|---|
| Lambda | $2.18 | $1.40 in USW2; $0.78 across 11 other spoke regions |
| RDS | $1.10 | t4g.small + GP3 — structurally fixed |
| CloudWatch | $1.02 | $0.65/day per-region custom metrics + $0.10/day dashboard + $0.21/day alarms |
| S3, VPC, SQS, others | <$0.30 each | Mostly structural |

Four levers in this round:

1. **12 → 6 spoke regions** (geographic-spread set chosen)
2. **Strip custom CloudWatch metrics** from spoke + ingest + downstream handlers
3. **Hand-roll the production dashboard** below the 50-metric free tier (replaces `MonitoringFacade`)
4. **Tighten log retention, add S3 lifecycle, drop X-Ray ACTIVE tracing**

Items tagged: `[code]` (Claude), `[manual]` (user, often `cdk destroy`-style).

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

**Single code change:**

- `.env.production:43` — replace the `SPOKE_REGIONS=...` line with the 6-region comma-separated list.

That's it. **No other code changes are required.**

- `.env.production:44` (`SPOKE_CRAWL_QUEUE_URLS=`) is **intentionally empty** — `infra/application_stage.py:88-93` computes the queue URLs at synth time from `config.spoke_region_list` and passes them as a Lambda env var via `infra/stacks/compute_stack.py:455-459`. Trimming the regions list flows through automatically.
- `.env.staging:43` already has only `us-west-2,us-east-1` — leave it alone.
- `infra/application_stage.py:196-210` already iterates `config.spoke_region_list`.
- `src/library-layer/library_layer/config.py:100-106` already splits and filters empty strings.

**Manual (user) — destroy the 6 dropped regional stacks:**

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

> ⚠️ **Destructive — user runs this, not Claude.** Per `feedback_no_deploy.md` and `feedback_no_commit_push.md`, Claude does not run `cdk destroy` or `cdk deploy`. Verify the queue is drained first; in-flight messages will be lost.

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

## Tier 2 — CloudWatch custom-metric strip (with one exception)

### T2-A. Strip powertools `Metrics` from all handlers except `crawler/handler.py`'s heartbeat metric `[code]`

**Pivotal evidence found during planning:** `infra/stacks/monitoring_stack.py` defines a `CatalogRefreshHeartbeat` alarm that depends on the `CatalogRefreshRun` custom metric emitted by `crawler/handler.py`. Stripping it would silently break new-game discovery monitoring. Decision: **keep that one metric**, strip everything else. Marginal cost ~$0.30/mo for one stream.

**Per-handler strategy:**

- **`crawler/handler.py`**: KEEP `Metrics(...)` instance, `set_default_dimensions`, and `@metrics.log_metrics(capture_cold_start_metric=False)` decorator (cold-start metric off — that's also a billed stream). KEEP only the single `CatalogRefreshRun` emission. Convert all 9 other `add_metric` calls (`SpokeDispatched`, `GamesUpserted`, `ReviewsUpserted`, `CatalogAppsDiscovered` ×2, `CatalogAppsEnqueued` ×2, `RefreshMetaEnqueued`, `RefreshReviewsEnqueued`) to `logger.info(...)` lines carrying the same fields.
- **All 6 other handlers**: STRIP completely — remove `Metrics`/`MetricUnit` imports, instance, dimensions, decorator, and every `add_metric(...)` call. Convert each to `logger.info(...)`.

**Files (full strip):**

- `src/lambda-functions/lambda_functions/crawler/spoke_handler.py` — 3 `add_metric` calls (`MetadataFetched`, `ReviewsFetched`, `TagsFetched`)
- `src/lambda-functions/lambda_functions/crawler/ingest_handler.py` — 3 calls (`GamesUpserted`, `TagsIngested`, `ReviewsUpserted`)
- `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py` — 5 calls (`OriginRevalidationsSucceeded`, `PageCacheBust`, `OriginRevalidationsFailed`, `CdnInvalidations`, `CdnInvalidationsFailed`)
- `src/lambda-functions/lambda_functions/analysis/handler.py` — 1 call (`ReportsGenerated`)
- `src/lambda-functions/lambda_functions/genre_synthesis/prepare.py` — Metrics scaffolding only (no add_metric in handler; service does)
- `src/lambda-functions/lambda_functions/genre_synthesis/collect.py` — Metrics scaffolding only

**Service drop:**

- `src/library-layer/library_layer/services/genre_synthesis_service.py` — drops `metrics: Metrics` constructor parameter and 2 `self._metrics.add_metric` calls (`GenreSynthesisCacheHit`, `GenreSynthesisRuns`). Converted to `logger.info` (the cache-hit log line was already there).

**Helper module to delete:**

- `src/library-layer/library_layer/utils/steam_metrics.py` — was a callback factory passed via `on_request=` to `DirectSteamSource`. After the strip, none of the 3 callsites pass a Metrics instance, so the helper is dead. **Delete the file** and remove `from library_layer.utils.steam_metrics import make_steam_metrics_callback` + the `_steam_metrics_callback = ...` line + the `on_request=...` keyword from each `DirectSteamSource(...)` call in:
  - `crawler/handler.py`
  - `crawler/spoke_handler.py`
  - `crawler/ingest_handler.py`

**Tests:**

- `tests/services/test_genre_synthesis_service.py` — drop the `Metrics(namespace=...)` mock and the 3 `metrics=` constructor args (1 fixture + 2 ad-hoc service builders).

**Pyproject — NOT changed:**

The original prompt assumed dropping a `metrics` extra from `aws-lambda-powertools`. The actual dependency is `extras = ["tracer"]` in both `pyproject.toml` and `src/library-layer/pyproject.toml`. **No `metrics` extra exists, so no `poetry lock` is needed for this** (see `feedback_lock_files.md` for when relocking is required).

**Verification:**

```bash
poetry run pytest tests/  # all green
aws cloudwatch describe-alarms --query 'MetricAlarms[?Namespace==`SteamPulse`].AlarmName'
# expect: only CatalogRefreshHeartbeat references the SteamPulse namespace
```

**Savings:** Drops ~24 metric streams across 6 regions to 1. **~$13/mo** within ~7 days as old streams age out of the billed set.

---

## Tier 3 — production dashboard rewrite (free-tier compliant)

### T3-A. Replace `MonitoringFacade` with hand-rolled `Dashboard` + `Alarm` constructs `[code]`

**Pivotal evidence found during planning:** The original prompt assumed dropping a few `monitor_*` calls would land below 50 metrics. It does not — `cdk-monitoring-constructs` `monitor_lambda_function` produces ~14 metrics per Lambda (TPS, Latency p50/p99/p99.9, Errors, Rates, Invocations, Iterator) and `monitor_sqs_queue_with_dlq` produces ~17 per pair (Message Count, Age, Size, Producer-vs-Consumer, Time to drain, ×2 for DLQ). Even after deleting custom-metric widgets the dashboard still synthesized to **116 metric expressions across 71 widgets**.

**Decision:** Replace the entire facade-driven dashboard with hand-rolled `Dashboard` + `GraphWidget` + standalone `Alarm` constructs. Alarms don't count toward the dashboard cap; widgets do. Compact widgets keep the metric count low.

**Target dashboard (achieved):**

| Section | Widgets | Metrics |
|---|---:|---:|
| Crawler Pipeline header | 1 text | 0 |
| Crawler invocations/errors/throttles | 1 graph | 3 |
| Crawler p99 latency | 1 graph | 1 |
| Spoke Ingest invocations/errors/throttles | 1 graph | 3 |
| App Crawl queue+DLQ depth | 1 graph | 2 |
| Review Crawl queue+DLQ depth | 1 graph | 2 |
| Spoke Results queue+DLQ depth | 1 graph | 2 |
| Catalog Refresh Heartbeat (≥1/hr) | 1 graph | 1 |
| API & Frontend header | 1 text | 0 |
| API invocations/errors/throttles | 1 graph | 3 |
| API p99 latency | 1 graph | 1 |
| Frontend SSR invocations/errors/throttles | 1 graph | 3 |
| Supporting Services header | 1 text | 0 |
| Email queue+DLQ depth | 1 graph | 2 |
| **Total** | **14** | **23** |

**Alarms preserved (separate constructs, not in widget count):**
- 4 lambda × {Errors, Throttles} = 8
- Crawler P99 (>300s), API P99 (>10s) = 2
- 3 main queues × Age = 3
- 4 DLQs × MessageCount = 4
- CatalogRefreshHeartbeat = 1
- **Total: 18 alarms**, all bound to the `AlarmTopic` SNS topic via `SnsAction`.

**File rewrite:** `infra/stacks/monitoring_stack.py` — drop the `cdk_monitoring_constructs` imports (`MonitoringFacade`, `*Threshold`, etc.) and use `aws_cdk.aws_cloudwatch` primitives directly: `Dashboard`, `GraphWidget`, `TextWidget`, `Metric`, `Alarm`, `Stats`, `ComparisonOperator`, `TreatMissingData`, `PeriodOverride`. Helper closures `_lambda_metric`, `_sqs_metric`, `_lambda_alarms`, `_sqs_alarms` keep the body short.

**Verification:**

```bash
poetry run cdk synth SteamPulse-Production-Monitoring  # synth must succeed
python3 -c "
import json
with open('cdk.out/SteamPulse-Production-Monitoring.template.json') as f:
    tpl = json.load(f)
for k, v in tpl['Resources'].items():
    if v['Type'] == 'AWS::CloudWatch::Dashboard':
        body = v['Properties']['DashboardBody']
        text = ''.join(p if isinstance(p,str) else 'X' for p in body['Fn::Join'][1])
        doc = json.loads(text)
        total = sum(len(w.get('properties',{}).get('metrics',[])) for w in doc['widgets'])
        print('metric expressions:', total)        # expect <= 50
        print('widgets:', len(doc['widgets']))
        break
"
```

**Savings:** **$3/mo** (full elimination of the dashboard line item, drops the dashboard back into the free tier).

---

## Tier 4 — observability extras

### T4-A. Tighten Lambda log retention `[code]`

**Evidence:** `infra/stacks/compute_stack.py` already sets explicit retention everywhere, so there's no "never expire" leak. But `crawler-fn`, `spoke-ingest-fn`, and the spoke crawler use `RetentionDays.ONE_MONTH` (hub-side high volume; spoke uses ONE_MONTH at `infra/stacks/spoke_stack.py:128-163`). Logs Insights queries rarely look back beyond 7 days for these high-volume functions.

**Files (drop `ONE_MONTH` → `ONE_WEEK`):**

- `infra/stacks/compute_stack.py:432-460` — CrawlerFn log group
- `infra/stacks/compute_stack.py:509-538` — SpokeIngestFn log group
- `infra/stacks/spoke_stack.py:128-163` — SpokeCrawlerFn log group (×6 regions)

**Savings:** Lambda log storage is $0.03/GB-month after ingestion. Going from 30→7 day retention cuts the steady-state stored volume by ~75% on these high-volume groups. Modest but trivial to apply: ~**$0.50–$1/mo**.

### T4-B. Add S3 lifecycle on assets bucket `[code]`

**Evidence:** `infra/stacks/data_stack.py:144-157` defines the assets bucket with no `lifecycle_rules=`. Spoke writes go to `spoke-results/{metadata,reviews,tags}/{appid}-{uid}.json.gz`; the ingest handler deletes them on success. **But:** when an SQS spoke-results message exhausts its retry budget and lands in the DLQ, the S3 object stays forever — there's no other cleanup path. Pre-launch this is small, but it grows unbounded.

**Frontend bucket already does this** at `infra/stacks/data_stack.py:171-189` (7-day expiration on `cache/`). Mirror that pattern.

**File:** `infra/stacks/data_stack.py:144-157` — add a `lifecycle_rules=[s3.LifecycleRule(...)]` with `prefix="spoke-results/"` and `expiration=Duration.days(7)`. The happy path deletes within seconds; 7 days is a generous safety net for any DLQ-orphaned objects.

**Savings:** Pre-launch ~$0/mo, but prevents an unbounded-growth bug. Worth the 5-line CDK change.

### T4-C. Drop X-Ray ACTIVE tracing + remove powertools `Tracer` `[code]`

**Evidence:** Two Lambdas have `tracing=lambda_.Tracing.ACTIVE` configured today:

- `infra/stacks/compute_stack.py:151` — AnalysisFn
- `infra/stacks/compute_stack.py:940` — EmailFn
- `infra/stacks/batch_analysis_stack.py:159` — three batch phases via factory (PreparePhase, CollectPhase, CheckBatchStatus)

The other 6 primary functions explicitly set `tracing=lambda_.Tracing.DISABLED`. Several of those still import + decorate with powertools `Tracer` even though no traces are emitted — dead instrumentation that adds ~10–20ms per cold start.

**Strategy:** Remove ACTIVE tracing from all CDK Lambda configs **and** remove the `Tracer`/`@tracer.capture_lambda_handler` code paths everywhere. X-Ray is not load-bearing for any current debugging; logs cover ops visibility.

**CDK files:**

- `infra/stacks/compute_stack.py:151` (AnalysisFn) — drop `tracing=lambda_.Tracing.ACTIVE`
- `infra/stacks/compute_stack.py:940` (EmailFn) — drop
- `infra/stacks/batch_analysis_stack.py:159` (`_make_batch_fn` factory) — drop

**Handler files (remove `Tracer` import, instantiation, and `@tracer.capture_lambda_handler` decorator):**

- `src/lambda-functions/lambda_functions/email/handler.py`
- `src/lambda-functions/lambda_functions/analysis/handler.py`
- `src/lambda-functions/lambda_functions/genre_synthesis/prepare.py`
- `src/lambda-functions/lambda_functions/genre_synthesis/collect.py`
- `src/lambda-functions/lambda_functions/batch_analysis/check_batch_status.py`
- `src/lambda-functions/lambda_functions/batch_analysis/prepare_phase.py`
- `src/lambda-functions/lambda_functions/batch_analysis/collect_phase.py`
- `src/lambda-functions/lambda_functions/batch_analysis/dispatch_batch.py`

**Savings:** X-Ray is $5/M traces recorded + $0.50/M traces scanned. With ACTIVE tracing on 5 functions × thousands of invocations/day, this is **~$1–$2/mo** depending on volume. Plus one-time cold-start latency reduction.

**Verification:**

```bash
poetry run pytest tests/                                # all green
poetry run cdk synth SteamPulse-Production-Compute      # tracing param gone from synth
poetry run cdk diff SteamPulse-Production-Compute       # only tracing/log retention deltas
```

---

## Intentionally out of scope

- **fck-nat × 2** (~$9/mo) — HA-correct, matches `feedback_fixed_cost_infra.md`.
- **RDS t4g.small** ($22/mo) — already smallest reasonable.
- **Tier window slackening** (S 2d→4d etc.) — separate freshness-vs-cost decision.
- **Hub Lambda compute** — round 3 already trimmed memory and switched to ARM.
- **Dropping the dashboard entirely** — usability hit isn't worth $0/mo if it's already free-tier.
- **Secrets Manager consolidation** — deferred to its own prompt (`scripts/prompts/secrets-consolidation.md`).

---

## Verification (aggregate)

7 days after Tier 1+2+3+4 deploy + destroys, expect (vs 2026-04-25 baseline):

| Line | Pre | Target |
|---|---:|---:|
| Daily Lambda | $2.18 | < $1.50 |
| Daily CloudWatch | $1.02 | < $0.40 |
| Daily total | $5.47 | **< $4.00** |
| Custom metrics in `SteamPulse` namespace | ~24 (post-region-cut) | 1 (`CatalogRefreshRun`) |
| Dashboard widgets | 90 (187 metrics) | 14 (≤ 50 metrics) |
| Active spoke regions | 12 | 6 |
| Lambdas with X-Ray ACTIVE | 5 | 0 |

```bash
aws ce get-cost-and-usage --time-period Start=YYYY-MM-DD,End=YYYY-MM-DD \
  --granularity DAILY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE
```

Aggregate potential: **~$42/mo off** ($165 → $123 run rate), no behavior change for end users; lower observability ceiling (acceptable pre-launch).

---

## Critical files

- `.env.production` — `SPOKE_REGIONS`
- `infra/stacks/monitoring_stack.py` — full rewrite (hand-rolled Dashboard + Alarms)
- `infra/stacks/compute_stack.py` — log retention on crawler/ingest, drop ACTIVE tracing on analysis + email
- `infra/stacks/spoke_stack.py` — log retention on spoke crawler
- `infra/stacks/data_stack.py` — S3 lifecycle on assets bucket
- `infra/stacks/batch_analysis_stack.py` — drop ACTIVE tracing in `_make_batch_fn`
- `src/library-layer/library_layer/services/genre_synthesis_service.py` — drop `metrics` parameter
- `src/library-layer/library_layer/utils/steam_metrics.py` — DELETE
- `src/lambda-functions/lambda_functions/crawler/{handler,spoke_handler,ingest_handler}.py` — Metrics strip (handler keeps `CatalogRefreshRun` only)
- `src/lambda-functions/lambda_functions/{revalidate_frontend,analysis,email}/handler.py` — strip Metrics + Tracer
- `src/lambda-functions/lambda_functions/genre_synthesis/{prepare,collect}.py` — strip Metrics + Tracer
- `src/lambda-functions/lambda_functions/batch_analysis/{check_batch_status,prepare_phase,collect_phase,dispatch_batch}.py` — strip Tracer
- `tests/services/test_genre_synthesis_service.py` — drop Metrics mock + constructor arg
