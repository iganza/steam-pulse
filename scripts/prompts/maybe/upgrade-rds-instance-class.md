# Upgrade RDS Instance Class — `t4g.small` → `m7g.large`

> **Status: possibly-do-later.** Not required to ship the current feature set.
> Parked because the immediate ingest backlog (the incident that uncovered this)
> was expected to drain on its own at baseline CPU within a few hours. Revisit
> if the next large crawl blitz exhibits the same symptoms, or once business
> model justifies the ~$35/mo cost increase.

## Goal

Stop RDS CPU credit exhaustion from bottlenecking the spoke-results ingest path
during catalog refresh blitzes. Switch production RDS from a burstable instance
class (`db.t4g.small`) to a non-burstable general-purpose one (`db.m7g.large`)
so sustained ingest load can use real CPU instead of being throttled to the
baseline once credits are depleted.

## Problem

The `SpokeIngestFn` Lambda (SQS → S3 → RDS) was observed draining its backlog
at ~60–200 msg/min even after all upstream fixes (idempotent S3 GET, bumped
memory/concurrency, `execute_values` refactor). Root cause was **not** in the
Lambda, queue, or app code:

- `AWS/RDS` `CPUCreditBalance` on `steampulse-production-data-*` sat at **0**
  for 25+ min.
- `CPUUtilization` stuck at 15–25% — i.e. exactly the `t4g.small` baseline
  (~20% per vCPU × 2 vCPUs ≈ 40% ceiling). Not "low usage" — *throttled*.
- `WriteLatency` was 0.03–0.06 ms (individual writes fine).
- `DatabaseConnections` = 12, matching `max_concurrency=12` (pooling fine).

Workload reality: 189/200 recent review messages carry the Steam max of
**1000 reviews each**. A 17.9k-message backlog is potentially ~10–17 M review
UPSERTs — not "a few thousand reviews." `t4g.small` baseline isn't sized for
that.

Per-message DB cost (audited):

- Reviews (≤1000 rows): ~6–8 queries. `bulk_upsert` = 2 `execute_values`
  round-trips (~80–150 ms).
- Metadata: ~18 queries — `TagRepository.upsert_genres` and `upsert_categories`
  (`src/library-layer/library_layer/repositories/tag_repo.py`) DELETE then
  loop per-row INSERTs per genre/category, not bulk.
- Tags: ~6 queries, bulk upserts.
- Connection reuse across warm Lambda invocations is correct
  (`src/library-layer/library_layer/utils/db.py` caches the psycopg2 conn
  with a `SELECT 1` health check).

Code path is reasonable. **The hard cap is DB CPU.**

## Change

### Upgrade RDS instance class

`infra/stacks/data_stack.py:75`:

```python
-    instance_type=ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.SMALL),
+    instance_type=ec2.InstanceType.of(ec2.InstanceClass.M7G, ec2.InstanceSize.LARGE),
```

Why `m7g.large`:

- **Non-burstable** Graviton general-purpose. 2 vCPU at a constant 100% — no
  credit games, no throttling under sustained load. The ingest-blitz pattern
  (which recurs whenever the crawler kicks a large catalog refresh) is exactly
  where burstable bites you.
- 8 GB RAM vs `t4g.small`'s 2 GB — headroom for Postgres `shared_buffers`;
  the `reviews` table is already large and growing, so more buffer cache
  = fewer disk reads on the UPSERT path.
- Cost delta: ~$15/mo → ~$50/mo on-demand Single-AZ us-west-2. ~$35/mo more.

Alternatives considered (not recommended):

- **`t4g.medium`** — still burstable; credits will hit zero again on the next
  big crawl. Cheaper (~$30/mo) but kicks the can.
- **`t4g.large`** — 30% baseline × 2 vCPU = 60% baseline. Better than small
  but still burstable. ~$60/mo, worse price/perf than `m7g.large`.
- **Wait it out** — baseline drain clears a given incident in ~3 h, but
  doesn't prevent the next one.

RDS instance-class modification applies in ~5–10 min and triggers a brief
reboot (~30–60 s). The ingest Lambda's `get_conn()` SELECT-1 health check
will reconnect transparently; SQS will retry any in-flight records whose DB
work didn't commit.

### Deferred sub-improvement (don't do unless #1 under-delivers)

`TagRepository.upsert_genres` / `upsert_categories` currently loop per-row
INSERTs (~13 of the ~18 queries on the metadata path). Collapsing to
`execute_values` bulk INSERTs with `ON CONFLICT DO NOTHING` + a single
batched join-table UPSERT would bring metadata-path query count from ~18 → ~4.
Wall-time savings ~15–20 ms per metadata message — trivial next to the
instance-class bump. Revisit only if post-upgrade throughput still
disappoints.

## Verification

1. **Local**:
   ```
   poetry run pytest tests/infra/
   ```
   No handler/repo changes; this is a smoke test that the CDK still synths.

2. **Post-deploy** (user deploys):
   - RDS `CPUCreditBalance` metric stops publishing (non-burstable instances
     don't have one) — that alone confirms the class switched.
   - `CPUUtilization` can peak above 40% during heavy ingest, then settles
     low after backlog clears.
   - `spoke_results_queue` `ApproximateNumberOfMessages` drops visibly
     faster — expect 300–500 msg/min outbound at `max_concurrency=12` once
     DB CPU is no longer the cap.
   - `AWS/Lambda` `SpokeIngestFn` `Duration.Avg` drops (less time waiting
     on DB per record).

## Out of scope

- RDS Proxy, read replicas, Multi-AZ — one writer, modest connection count;
  not needed.
- Storage type (`gp3`) — fine.
- Memory/concurrency/batch tuning on the Lambda — already sized correctly
  for the new DB ceiling.
- Revisiting the metadata upsert refactor — see "Deferred sub-improvement"
  above.
