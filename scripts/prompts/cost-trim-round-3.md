# Cost trim — round 3 (post env-cost-reduction)

## Context

The `env-cost-reduction.md` round shipped (matview consolidation, SpokeIngest 1024→512, X-Ray off hot paths, etc.) and staging was destroyed on **2026-04-24**. Despite that, daily AWS spend on **2026-04-23** was **$8.31** and **2026-04-24** was **$7.35** (~$220/mo run rate). A fresh Cost Explorer + CloudWatch sweep on 2026-04-25 surfaced three categories of waste that round 2 didn't catch.

Top remaining drivers (daily avg 4/23–4/24):

| Service | $/day | Note |
|---|---:|---|
| Lambda | $3.69 | `SpokeIngestFn` $1.85 alone; matview cascade still firing |
| RDS | $1.40 | t4g.small + GP3 + backups (structurally fixed) |
| CloudWatch | $1.13 | **$0.90/day from 11 spoke regions** — not addressed in round 2 |
| S3, VPC, EC2, SQS, Secrets | <$0.40 each | Mostly structural |

Items tagged: `[code]` (Claude), `[manual]` (user), `[decide→code]` (user investigates, Claude ships), `[investigate]` (user reports back before deciding).

---

## Tier 1 — high-impact gaps round 2 missed

### T1-A. ARM (Graviton2) migration for all Python Lambdas `[code]`

**Evidence:** Every Steampulse Lambda in `aws lambda list-functions` runs `Architectures=["x86_64"]`. ARM (Graviton2) Lambda is **20% cheaper per GB-second** for the same memory and equal or better Python perf. With $3.69/day on Lambda, a 20% drop = **~$0.74/day = $22/mo** structural saving.

The boto3 / psycopg2-binary / httpx / anthropic deps all have arm64 wheels (Python 3.12). The PythonFunction CDK construct builds via Docker — needs `bundling.platform=linux/arm64` to produce an arm64 layer.

**Files:**
- `infra/stacks/compute_stack.py` — for every `PythonFunction(...)` and `lambda_.Function(...)`, add `architecture=lambda_.Architecture.ARM_64`. Same for the `PythonLayerVersion` (line ~82) — set `compatible_architectures=[lambda_.Architecture.ARM_64]` and ensure the bundling Docker image is `aws-lambda-python:3.12-arm64`.
- `infra/stacks/spoke_stack.py` (or wherever spoke crawlers are defined) — same change for spoke crawler functions across all 12 regions.
- Skip Node.js custom-resource Lambdas (CDK-managed, not worth touching).
- Skip `FrontendFn` (OpenNext nodejs22.x — separate test pass needed; default to leaving as x86_64 unless the OpenNext build supports arm64).

**Verification:** After deploy:

```bash
aws lambda list-functions --region us-west-2 \
  --query 'Functions[?starts_with(FunctionName, `SteamPulse-Production`)].[FunctionName,Architectures[0]]' \
  --output table
# Expect arm64 for all Python functions
```

Run the full integration test suite after deploy (any binary-deps regression will surface here). Spot-check `SpokeIngestFn` Logs Insights for any `ImportError` cold-starts in the first hour.

**Savings:** ~$22/mo with no behavior change.

---

### T1-B. ~~Matview refresh volatility~~ — RESOLVED, but new finding `[separate prompt]`

**Status (verified 2026-04-25):** The volatility (4/168/17 executions/day) was historical — pre-deploy data. Trigger Lambda was last-modified `2026-04-25T04:17:21Z` and now generates `daily-YYYY-MM-DD` execution names with `input="{}"`. Today's first execution is `daily-2026-04-25`, fired once. Cascade is **fixed** by the round 2 deploy.

**New finding (NOT cost-related):** Today's `daily-2026-04-25` execution FAILED with `Matview refresh partial_failure — 5/18 failed`. Multiple individual matview Lambdas hit `Sandbox.Timedout` at the 15-min Lambda max. Affected views include `mv_tag_games`, `mv_review_counts`, `mv_trend_by_tag`. This is a correctness issue — refresh exceeds Lambda's hard 15-min ceiling. **Defer to a separate prompt** (e.g. `matview-refresh-runtime-bound.md`): move the slow-running views to a non-Lambda runtime (Fargate task, ECS one-shot, or SFN activity) or drop the heaviest views entirely.

---

### T1-C. CloudWatch monitoring trim — 11 spoke regions `[decide→code]`

**Evidence:** Round 2's T3-B addressed dashboards in USW2 only. The bigger line is **`MetricMonitorUsage` + `AlarmMonitorUsage` in 11 spoke regions = $0.90/day = $27/mo**. Each spoke region pays $0.06–0.07/day for ~12 monitored metrics + ~4 alarms — disproportionate to a 1-Lambda-1-queue footprint.

**Investigate (user):**

```bash
for r in us-east-1 us-east-2 ca-central-1 eu-west-1 eu-central-1 eu-north-1 \
         ap-northeast-1 ap-northeast-2 ap-south-1 ap-southeast-1 ap-southeast-2; do
  echo "=== $r ==="
  aws cloudwatch describe-alarms --region $r \
    --query 'MetricAlarms[?contains(AlarmName, `SteamPulse`) || contains(AlarmName, `steampulse`)].AlarmName' \
    --output text | tr '\t' '\n'
done
```

**Decide:** Identify which spoke alarms actually page anyone. Likely keepers: spoke Lambda error rate, spoke DLQ depth. Likely droppers: per-spoke Duration / Throttles / ConcurrentExecutions / Iterator-age (already covered by central ingest queue health).

**Code (Claude, after user decides):** In whatever construct creates spoke alarms (likely `infra/stacks/spoke_stack.py` or a `cdk-monitoring-constructs` block in `monitoring_stack.py`), pass an `alarm_*` allowlist or remove construct calls.

**Savings:** $15–25/mo depending on aggressiveness.

---

## Tier 2 — moderate impact, code-only

### T2-A. SpokeIngest memory: 512 MB → 384 MB `[code]`

**Evidence (verified 2026-04-25):** 7-day Logs Insights query on `/steampulse/production/ingest` returned `peakMB=227, p99MB=216, p50MB=171, samples=24131`. Original prompt suggested 256MB but peak exceeds that (1.13× headroom — too tight). **384MB gives 1.69× headroom over observed peak** — safe.

**Files:**
- `infra/stacks/compute_stack.py:510` — `memory_size=512` → `memory_size=384`

**Savings:** ~$0.45/day = **$13/mo** (25% drop, not 50%).

---

### T2-B. MatviewRefreshMachine STANDARD → EXPRESS `[decide→code]`

**Evidence:** `state_machine_type=sfn.StateMachineType.STANDARD` at `compute_stack.py:775`. STANDARD charges **$25 per million state transitions**. EXPRESS charges per execution + duration ($1 per million executions + $0.0001 per GB-sec) — typically 5–10× cheaper for short workflows.

Each matview refresh execution does ~18 fan-out items × ~7 state transitions each ≈ 130 transitions. At 17 executions/day (4/23 number) = 2,200 transitions/day = $0.05/mo. Trivial. **At 168 executions/day (4/22)** = 22,000 transitions/day = $16/mo. The STANDARD type is fine if T1-B drops execution count to 1/day; it's expensive only if the volatility persists.

**Decide (user):** Ship T1-B first. If post-T1-B execution count is sustained ≤ 5/day, leave STANDARD. If it stays >50/day, switch to EXPRESS.

**Code (Claude, conditional):** `state_machine_type=sfn.StateMachineType.EXPRESS` and add `logs.LogGroup` for execution logs (EXPRESS requires explicit log destination if you want history).

**Savings:** $0–$15/mo depending on T1-B outcome.

---

### T2-C. Verify orphan Aurora + PublicIPv4 after staging tail clears `[manual]`

**Evidence:** On 2026-04-24 there was still $0.016 of `USW2-Aurora:ServerlessV2Usage` and 2.77 avg PublicIPv4 in use (production should be exactly 2). These are likely staging tail charges since staging was destroyed mid-day 4/24.

**Check on 2026-04-26 (full post-staging day):**

```bash
# Aurora must be zero
aws ce get-cost-and-usage --time-period Start=2026-04-26,End=2026-04-27 \
  --granularity DAILY --metrics UnblendedCost \
  --filter '{"Dimensions":{"Key":"USAGE_TYPE","Values":["USW2-Aurora:ServerlessV2Usage","USW2-Aurora:StorageUsage","USW2-Aurora:StorageIOUsage"]}}'

# Public IPv4 should be exactly 2 (fck-nat × 2 AZ)
aws ec2 describe-network-interfaces --region us-west-2 \
  --filters Name=association.public-ip,Values=* \
  --query 'NetworkInterfaces[].[NetworkInterfaceId,Description,Association.PublicIp,Status]' \
  --output table

# Orphan Aurora snapshots (final snapshots default to retain — DESTRUCTIVE if deleted)
aws rds describe-db-cluster-snapshots --region us-west-2 \
  --query 'DBClusterSnapshots[?contains(DBClusterIdentifier, `staging`)].[DBClusterSnapshotIdentifier,SnapshotCreateTime]' \
  --output table
```

**Act:** Release any unattached EIP. If you don't need staging snapshots for restore, delete them — but confirm before running, snapshot deletion is irreversible.

**Savings:** $3.60/mo per orphan IP; <$1/mo per snapshot kept.

---

## Tier 3 — small wins, mostly cleanup

### T3-A. RDS backup retention review `[decide→code]`

**Evidence:** RDS `ChargedBackupUsage` was $0.53 on 4/23 (one day's snapshot creation). Round 2 didn't touch retention. Pre-launch, 7-day RPO is generous.

**Decide (user):** 3 / 5 / 7 days.

**Code:** Update `backup_retention=cdk.Duration.days(N)` on the RDS instance in `infra/stacks/data_stack.py`.

**Savings:** $3–6/mo for going 7→3 days.

---

### T3-B. Don't run Cost Explorer on cron `[manual]`

**Evidence:** Cost Explorer charges **$0.01 per programmatic API call**. On 4/24 the `AWS Cost Explorer` line was $0.18 — much higher than 4/23's $0.04. Some of that is from this investigation; the rest may be a scheduled cost-tracking script.

**Investigate:** Search for any scheduled job calling `aws ce get-cost-and-usage` (cron, GitHub Action, scheduled Lambda). Common patterns: Slack daily-cost bot, Datadog/Grafana cost ingestor.

**Savings:** $1–5/mo.

---

### T3-C. Lambda Powertools `Tracer` decorator cleanup `[code]`

**Evidence:** Round 2 T3-A disabled X-Ray on hot-path Lambdas but the `@tracer.capture_lambda_handler` decorator may still be in handler code. With tracing off, the decorator is a no-op — but the import + decorator chain adds cold-start ms. Free perf win.

**Files:** Grep `src/lambda-functions/` for `tracer.capture_lambda_handler` on functions whose CDK config now has `tracing=lambda_.Tracing.DISABLED`.

**Savings:** Negligible $; small cold-start improvement.

---

## Intentionally out of scope

- Items already shipped in `env-cost-reduction.md` (matview consolidation, SpokeIngest 1024→512, X-Ray off hot paths, log retention, dashboard audit, Aurora staging removal, secrets cleanup, t4g.nano EC2, Public IPv4 audit). T1-B above re-opens matview *only because the data shows it didn't fully take*.
- **fck-nat × 2** ($9/mo) — structurally correct for HA. Matches `feedback_fixed_cost_infra.md`.
- **RDS t4g.small** ($22/mo) — already smallest reasonable.
- **12-region spoke architecture** — product decision, not a cost bug.
- **Bedrock / Anthropic** — separate invoice. Audit per `feedback_llm_cadence_economics.md`.

---

## Verification

7 days after Tier 1+2 deploy, expect:

| Metric | Pre | Target |
|---|---:|---:|
| Daily Lambda cost | $3.69 | < $2.10 (ARM 20% + SpokeIngest 50%) |
| Daily CloudWatch cost | $1.13 | < $0.40 (drop 11 spoke alarms) |
| Daily total | $7.35 | **< $4.50** |
| Matview SFN executions/day | 17–168 | 1 |

```bash
aws ce get-cost-and-usage --time-period Start=2026-04-25,End=2026-05-02 \
  --granularity DAILY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE
```

Aggregate potential: **~$70/mo off** ($220 → $150 run rate), without architectural change.

---

## Critical files

- `infra/stacks/compute_stack.py:82` — `PythonLayerVersion` (ARM compat)
- `infra/stacks/compute_stack.py:510` — `SpokeIngestFn` memory
- `infra/stacks/compute_stack.py:677` — `MatviewRefreshWorkerFn`
- `infra/stacks/compute_stack.py:775` — `MatviewRefreshMachine` STANDARD/EXPRESS
- `infra/stacks/compute_stack.py:1008` — `CatalogRefreshRule` cron
- `infra/stacks/messaging_stack.py:243` — `cache_invalidation_queue` SNS subscriptions (verify only `catalog-refresh-complete` remains)
- `infra/stacks/spoke_stack.py` — spoke alarms + spoke crawler ARM
- `infra/stacks/data_stack.py` — RDS backup retention
- `src/lambda-functions/lambda_functions/matview_refresh/trigger.py` — verify only one event path remains
