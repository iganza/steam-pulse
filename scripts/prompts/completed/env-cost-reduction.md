# Plan: Env cost reduction — consolidated sweep

## Context

April 2026 MTD env spend is ~$130 across the AWS account. An Apr 21 Lambda spike (`SpokeIngestFn` running 90× slower per invocation) exposed that most of the steady-state cost is not the review-fetch/metadata-update pipeline itself — it's the **refresh cascades and over-provisioned infra around it**. A full Cost Explorer sweep + Performance Insights analysis identified levers worth bundling into one atomic sweep.

April 2026 MTD by service (non-Bedrock — Bedrock was an unrelated user mistake, self-correcting):

| Service | MTD | What's actually there |
|---|---:|---|
| Lambda | $22.67 | Apr 21 spike + 12-region spoke crawl baseline |
| RDS | $19.75 | Prod `db.t4g.small` + storage + backups + staging Aurora Serverless v2 |
| CloudWatch | $7.85 | Dashboards $1.83, alarms $1.05, metrics ~$3 |
| VPC | $7.64 | 100% `PublicIPv4:InUseAddress` (~3 public IPs @ $0.005/hr) |
| EC2 Compute | $6.43 | Standalone `t4g.nano` running 24/7 |
| Secrets Manager | $4.26 | 15 secrets — slash-prefix dupes + Aurora orphans |
| S3 | $3.54 | |
| SQS | $2.66 | Cross-region data transfer from 12 spokes |
| X-Ray | $1.26 | Active tracing on 22 functions including hot spoke paths |

The Apr 21 PI data showed the DB is **I/O-bound, not CPU-bound**. `IO:DataFileRead` waits dominated on Apr 21 (load 3.5); by Apr 23, post-`db-performance-optimizations-v1`, the top wait shifted to `Lock:relation` (4.1) — queries queueing behind `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_audience_overlap` (PI load 5.226 by itself). That matview runs 24× per day because every hourly `catalog-refresh-complete` event triggers a full 18-view refresh.

## Goal

Cut non-Bedrock baseline env cost roughly in half (~$60/mo → ~$30/mo) and eliminate the matview-refresh cascade as a cost-variability risk. No product-facing changes. Each tier is independently shippable.

Items are tagged:
- `[code]` — Claude implements (CDK / Python changes)
- `[manual]` — User does it in AWS console or locally
- `[decide→code]` — User investigates and decides, Claude then ships the change

---

## Tier 1 — ship together, highest impact

### T1-A. Catalog refresh: hourly → daily `[code]`

**Evidence:** `CatalogRefreshRule` at `cron(15 * * * ? *)` publishes `catalog-refresh-complete` 24×/day. Steam's `GetAppList` grows slowly — new games appear throughout the day but a 24h discovery lag is acceptable for our product stage. Hourly cadence is the root cause of the matview cascade (T1-B).

**Files:**
- `infra/stacks/compute_stack.py:933-938`

**Change:**

```python
catalog_rule = events.Rule(
    self,
    "CatalogRefreshRule",
    schedule=events.Schedule.cron(minute="15", hour="6"),  # daily 06:15 UTC
    enabled=config.is_production,
)
```

Keep `RefreshMetaRule` and `RefreshReviewsRule` hourly — those are the tiered-refresh dispatchers that handle ongoing per-game updates and must stay frequent. Only the full-catalog `GetAppList` pass drops to daily.

**Verification:** After deploy, `aws logs filter-log-events --log-group /steampulse/production/crawler --filter-pattern "Catalog refresh complete"` should show exactly one entry per day, not 24.

---

### T1-B. Matview refresh: single daily job, one narrow `report-ready` exception `[code]`

**Evidence:** Current architecture triggers matview refreshes on three event types (`trigger.py:32-36`): `report-ready`, `catalog-refresh-complete`, `batch-analysis-complete`. Plus a redundant daily cron `MatviewRefreshSchedule` at `cron(45 7 * * ? *)`. This produces ~24 full refreshes per day at hourly cadence. Each full refresh does `REFRESH MATERIALIZED VIEW CONCURRENTLY` for 18 views — `mv_audience_overlap` alone is an O(N²) self-join over `reviews` and dominates DB load (PI 5.226 on Apr 23, bigger than the entire Apr 21 Lambda incident).

Tracing the UI confirmed: the report view (`/api/games/{appid}/report`) reads base tables directly (`reports`, `games`, `game_tags`, `reviews`) — **no matview refresh is needed for a newly-ready report to be viewable**. The current `REPORT_DEPENDENT_VIEWS` set only powers discovery/listing surfaces (homepage strips, `/reports` catalog), all of which tolerate 24h staleness.

**Files:**
- `src/library-layer/library_layer/repositories/matview_repo.py:13-41` — collapse `REPORT_DEPENDENT_VIEWS` and `MATVIEW_NAMES`
- `src/lambda-functions/lambda_functions/matview_refresh/trigger.py:28-68` — remove `_EVENT_PRIORITY` classification
- `src/lambda-functions/lambda_functions/matview_refresh/start.py:42-84` — remove debounce, in-flight gate, and trigger-event branch
- `infra/stacks/compute_stack.py` — remove `MatviewRefreshSchedule` cron and the `report-ready` + `batch-analysis-complete` SNS subscriptions on `cache-invalidation-queue`
- `infra/stacks/messaging_stack.py` — prune SNS subscription filter policies

**Change (architecture):**

Keep one refresh path only: `catalog-refresh-complete` (now daily, from T1-A) → existing SNS → `cache-invalidation-queue` → `MatviewRefreshTriggerFn` → `MatviewRefreshMachine` SFN → full 18-view refresh. No priority classification, no debounce, no in-flight gate — events fire once per day, can't race themselves.

`report-ready` no longer triggers any matview refresh. Newly-ready reports are viewable instantly via direct URL / cross-link; discovery pages show them within 24h at the next daily refresh.

`batch-analysis-complete` no longer triggers matview refresh either — the operator who runs batch analysis can manually invoke the SFN if they want early visibility, otherwise the next daily run covers it.

**Code simplifications (delete):**

- `REPORT_DEPENDENT_VIEWS` tuple in `matview_repo.py` — dead
- `_EVENT_PRIORITY` dict and `_classify()` function in `trigger.py` — only one event type remains
- `DEBOUNCE_SECONDS`, `RUNNING_STALE_SECONDS`, `get_running_cycle_id()`, `get_last_refresh_time()` in `start.py` + `matview_repo.py` — debounce irrelevant at 1/day cadence
- SNS subscription filter for `content-events-topic` filtering `report-ready` onto `cache-invalidation-queue` — remove the subscription entirely
- SNS subscription filter for `system-events-topic` filtering `batch-analysis-complete` — remove
- `MatviewRefreshSchedule` EventBridge rule — redundant

`start.py` shrinks to: validate event, call `_repo.start_cycle()`, return `MATVIEW_NAMES`. ~15 lines total.

**Optional further simplification (T1-B-bonus, same PR):** replace the SNS/SQS/trigger-Lambda hop with a direct Step Functions chain. The Crawler Lambda's catalog-refresh path ends with a `StartExecution` call on `MatviewRefreshMachine`. Kills `cache-invalidation-queue` (SQS), the `catalog-refresh-complete` SNS subscription, `MatviewRefreshTriggerFn` Lambda, and the SNS publish in `catalog_service.py:123-132`. If that's too much scope, leave for a follow-up.

**Verification:**
- `aws logs filter-log-events --log-group /aws/lambda/...MatviewRefreshWorkerFn... --start-time $(24h ago)` — expect 18 REFRESH lines per day, not ~400.
- Performance Insights 24h after deploy: `mv_audience_overlap` load should be <0.25 (was 5.226). `Lock:relation` wait should drop from 4.1 to <0.5.

---

### T1-C. SpokeIngest Lambda memory: 1024 MB → 512 MB `[code]`

**Evidence:** Across 5,930 invocations in the last 24h, SpokeIngest p50 memory usage is 180 MB, p99 is 190 MB, max is 192 MB. It uses ~19% of its allocated 1024 MB. The bump to 1024 MB in `feature/unblock-spoke-results-ingest` was made under the assumption the slowness was CPU-bound; Performance Insights subsequently confirmed the bottleneck was DB I/O. More Lambda CPU just meant more idle CPU.

**Files:**
- `infra/stacks/compute_stack.py` — `SpokeIngestFn` definition, `memory_size=1024` → `memory_size=512`

**Change:** One-line memory drop. 512 MB leaves 2.7× headroom over observed peak.

**Verification:** 24h after deploy, re-run the `/aws/lambda/.../SpokeIngestFn` CloudWatch Logs Insights query for `Max Memory Used` — p99 should still be <256 MB.

**Savings:** Halves GB-seconds cost for this function. ~$5–7/mo structural, 2× that during spikes.

---

## Tier 2 — investigate, decide, then ship

### T2-A. Staging off Aurora Serverless v2 `[decide→code]`

**Evidence:** Staging DB `steampulse-staging-data-dbwriter9bd1608d-6l9pq03hlefr` is `db.serverless` (Aurora Serverless v2). April charges: `ServerlessV2Usage` $0.44 + `StorageIOUsage` $0.60 + `StorageUsage` $0.06 = $1.10 MTD. Per `feedback_fixed_cost_infra.md`: prefer fixed monthly cost, avoid per-ACU billing.

Three orphan `AuroraServerlessClusterSecr-*` secrets in Secrets Manager confirm a prior Aurora cluster iteration wasn't fully cleaned up.

**Decide (user):** Target instance class for staging — `db.t4g.micro` (matches the pre-upgrade prod sizing, ~$0.015/hr ≈ $11/mo) or `db.t4g.small` (matches current prod).

**Code (Claude, after user decides):**
- `infra/stacks/data_stack.py` — replace Aurora Serverless cluster construct with a single `rds.DatabaseInstance` matching user's chosen class.
- Add one-time migration runbook step: `pg_dump` from Aurora cluster → restore to new RDS instance → update staging `/steampulse/staging/db-credentials` secret → redeploy.
- Delete the three `AuroraServerlessClusterSecr-*` orphan secrets as part of the cleanup (see T2-C).

**Savings:** Direct $1–2/mo; eliminates cost-variability risk.

---

### T2-B. Public IPv4 audit `[decide→code]`

**Evidence:** $7.64 MTD = ~$0.005/hr × ~3 in-use IPs in us-west-2 (all `USW2-PublicIPv4:InUseAddress`). AWS now charges for every public IPv4 since Feb 2024, including attached ones.

**Investigate (user):** run:

```bash
aws ec2 describe-addresses --region us-west-2 --output table
aws ec2 describe-network-interfaces --region us-west-2 \
  --filters Name=association.public-ip,Values=* \
  --query 'NetworkInterfaces[].[NetworkInterfaceId,Description,Association.PublicIp,Attachment.InstanceId]' \
  --output table
```

Likely candidates: RDS public endpoint (if `PubliclyAccessible=true`), NAT Gateway EIPs, leftover EIPs from prior deploys.

**Decide:** Which IPs can be released. If RDS is public and shouldn't be, flip `publicly_accessible=False` in `data_stack.py` (user accesses via VPN/SSM tunnel after that).

**Code (Claude):** CDK changes for any CDK-managed resources the user flags.

**Savings:** $3–10/mo depending on how many are releasable.

---

### T2-C. Secrets cleanup `[decide→code]`

**Evidence:** 15 secrets × $0.40/mo = $6/mo. Observed dupes (`aws secretsmanager list-secrets`):

- `/steampulse/staging/steam-api-key` **and** `steampulse/staging/steam-api-key` (leading slash vs no slash)
- Same dupe pattern for `production/db-credentials`, `production/steam-api-key`, `production/resend-api-key`, `staging/db-credentials`, `staging/resend-api-key`
- `/steampulse/staging/anthropic-apikey` (note: `apikey` not `api-key`) vs `/steampulse/production/anthropic-api-key` — inconsistent naming
- Three `AuroraServerlessClusterSecr-vu07YAqua8q9`, `-bRsMpVwHN2IA`, `-B4JqgMomW3G4` orphans (from T2-A cleanup)

**Investigate (user):** For each dupe pair, check which one the Lambda code reads from (grep `SecretId` / `get_secret_value` in `src/`) and which one local scripts or `sp.py` read from. One of each pair is dead — confirm.

**Decide:** Canonical path pattern — pick one of `/steampulse/<env>/<name>` (leading slash) or `steampulse/<env>/<name>` (no slash) and normalize. Plus kill the 3 Aurora orphans.

**Code (Claude):** Update CDK `secret.Secret.from_secret_name_v2(...)` calls to match canonical path, then user runs `aws secretsmanager delete-secret --secret-id <orphan> --force-delete-without-recovery` for each orphan.

Target end state: ~8 secrets (env × {db, steam-api, anthropic, resend}).

**Savings:** $2.80/mo.

---

### T2-D. Standalone `t4g.nano` EC2 `[manual]`

**Evidence:** $6.42 MTD, runs 24/7. Purpose unknown — not managed by CDK stacks inspected.

**Investigate (user):**

```bash
aws ec2 describe-instances --region us-west-2 \
  --filters Name=instance-type,Values=t4g.nano \
  --query 'Reservations[].Instances[].[InstanceId,Tags,State.Name,LaunchTime,IamInstanceProfile.Arn]' \
  --output json
```

Check: is it a bastion for RDS access? A leftover from initial setup? A forgotten cost-tracking script runner?

**Decide:**
- If bastion: terminate and use SSM Session Manager (free) via `aws ssm start-session --target <rds-instance-or-host>` for future DB access.
- If unused: terminate.
- If actively used: leave it, document purpose in CLAUDE.md.

**Savings:** Up to $3/mo.

---

## Tier 3 — small wins, code-only

### T3-A. Disable X-Ray on hot paths `[code]`

**Evidence:** 22 Lambda functions have `TracingConfig.Mode=Active`. X-Ray is $5/million traces stored — $1.26 MTD now, scales linearly with invocations. Hot paths (SpokeIngest, Crawler, 12 spoke crawlers, API, Frontend) generate the vast majority of traces. Analysis / Batch / GenreSynthesis / Matview functions are low-volume and benefit most from traces.

**Files:**
- `infra/stacks/compute_stack.py` — `SpokeIngestFn`, `CrawlerFn`, `ApiFn`, `FrontendFn`: set `tracing=lambda_.Tracing.DISABLED`
- `infra/stacks/spoke_stack.py` — all spoke crawler functions: `tracing=DISABLED`

Keep `Active` on: `AnalysisFn`, `PreparePhaseFn`, `CollectPhaseFn`, `CheckBatchStatusFn`, `GenreSynthesisPrepareFn`, `GenreSynthesisCollectFn`, `DispatchBatchFn`, matview refresh functions.

Also remove the `@tracer.capture_lambda_handler` decorator from the disabled functions' handlers (no-op when tracing is off, but dead code).

**Savings:** Immediate ~$1/mo; scales with traffic growth.

---

### T3-B. CloudWatch dashboards audit `[decide→code]`

**Evidence:** $1.83 MTD on `DashboardsUsageHour`. First 3 dashboards per account are free; beyond that is $3/mo each.

**Investigate (user):**

```bash
aws cloudwatch list-dashboards --query 'DashboardEntries[].DashboardName' --output table
```

**Decide:** Keep the 3 most valuable; drop the rest.

**Code (Claude):** Remove corresponding CDK constructs in `infra/stacks/monitoring_stack.py`.

**Savings:** $3/mo per dashboard dropped beyond 3.

---

### T3-C. Default log retention = 30 days `[code]`

**Evidence:** Several CDK-generated log groups have `retentionInDays: None` (infinite):
- `/aws/lambda/SteamPulse-...-CustomCDKBucketDeploymen-...`
- `/aws/codebuild/PipelineBuildSynthCdkBuildP-...`
- `/aws/codebuild/steampulse-staging-selfupdate`
- `/aws/codebuild/metacraft-dev-selfupdate`

Small bytes now but grow forever. The steampulse-managed groups already have 7 or 30 day retention.

**Files:**
- `infra/app.py` or per-stack constructor — add default `aws_cdk.aws_logs.RetentionDays.ONE_MONTH` via `logs.LogRetention` construct or `log_retention` parameter on Lambda functions that don't explicitly set it.
- For CodeBuild/CodePipeline-created groups: add explicit `log_group` constructs with 30-day retention in `infra/stacks/pipeline_stack.py` (if present).

**One-shot backfill (user runs after deploy):**

```bash
for lg in $(aws logs describe-log-groups --query 'logGroups[?retentionInDays==`null`].logGroupName' --output text); do
  aws logs put-retention-policy --log-group-name "$lg" --retention-in-days 30
done
```

**Savings:** Negligible now, prevents unbounded growth.

---

## Intentionally out of scope

- **12-region spoke architecture.** ~$9/mo Lambda structural cost from the 12 regional spoke crawlers is working as designed. Dropping to 6 regions is a product decision about geographic review diversity, not a cost bug.
- **SpokeIngest `batch_size=40` / `max_concurrency=6`.** I originally suggested dropping batch_size to 20, retracted after PI analysis — smaller batches don't reduce DB contention; concurrency is the real lever. Leave both alone until Tier 1 ships, then re-check PI. If `Lock:relation` wait is still elevated, drop concurrency to 4.
- **Bedrock $47.** User-acknowledged mistake, corrected going forward.
- **Prod `db.t4g.small` sizing.** Already upgraded Apr 21. Further upsize (→ `db.t4g.medium` for more shared_buffers) deferred — let Tier 1 reduce matview load first, then reassess.

---

## Verification

7 days after Tier 1 + Tier 3 deploy, expect:

- **Daily Lambda cost (steady state, no spike):** < $0.30/day (was ~$0.28 pre-incident, now will be lower with matview cascade gone)
- **Daily RDS cost:** < $0.50/day (was ~$1.60 during spike days)
- **Non-Bedrock total daily cost:** < $1.50/day (was ~$3 recent days)
- **PI top wait event:** CPU or IO:DataFileRead (NOT Lock:relation)
- **`mv_audience_overlap` PI load:** < 0.25 (was 5.226)
- **matview_refresh_log rows:** 1 per day (was ~20+)

Command:

```bash
aws ce get-cost-and-usage --time-period Start=$(date -v-7d +%Y-%m-%d),End=$(date +%Y-%m-%d) \
  --granularity DAILY --metrics UnblendedCost \
  --filter '{"Not":{"Dimensions":{"Key":"SERVICE","Values":["Claude Sonnet 4.6 (Amazon Bedrock Edition)","Tax"]}}}' \
  --group-by Type=DIMENSION,Key=SERVICE
```
