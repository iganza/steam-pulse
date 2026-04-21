# Unblock `spoke-results-production` Ingest

## Goal

Stop `spoke_results_queue` from falling behind in production by (1) finishing
the in-flight infra bumps in `compute_stack.py` / `data_stack.py`, (2) giving
the ingest Lambda enough CPU to keep up, and (3) removing the row-by-row
`INSERT` amplifier in the review repository that no settings tune can fix.

## Problem

The `SpokeIngestFn` Lambda consumes `steampulse-spoke-results-production`
(SQS) and writes spoke results (metadata / reviews / tags) to RDS Postgres.
Queue depth is climbing faster than the Lambda drains it.

Per message, the handler (`src/lambda-functions/lambda_functions/crawler/ingest_handler.py`)
does: S3 GET → `gzip.decompress` → `json.loads` → DB upserts → commit → S3
DELETE → (for reviews) SQS send for next-page cursor. All of this runs on a
**256 MB Lambda (~0.15 vCPU)**.

The repo fix for review ingest (`ReviewRepository.bulk_upsert`,
`src/library-layer/library_layer/repositories/review_repo.py:15-61`) is
misnamed — it loops `cur.execute()` per row. A single 1000-review message
costs 1000 network round-trips to RDS. No combination of `batch_size`,
`max_concurrency`, or instance size beats that amplifier.

There's also an in-flight edit in `compute_stack.py` (lines 440-445) that
dropped the `)` closing `crawler_role.add_to_policy(...)` — the file won't
parse, so nothing in the stack deploys until it's fixed.

## Current pending diff (user already staged these)

```diff
# infra/stacks/compute_stack.py  (SQS event source)
-    batch_size=10,
-    max_concurrency=2,
+    batch_size=100,
+    max_batching_window=cdk.Duration.seconds(5),
+    max_concurrency=4,
     report_batch_item_failures=True,

# infra/stacks/data_stack.py  (prod RDS)
-    instance_type=ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO),
+    instance_type=ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.SMALL),
```

Directionally correct but under-powered. Keep them, add the changes below.

## Changes

### 1. Fix dropped `)` — blocking

`infra/stacks/compute_stack.py` lines 440-445 — restore the `)` closing
`add_to_policy(`:

```python
crawler_role.add_to_policy(
    iam.PolicyStatement(
        actions=["sqs:SendMessage"],
        resources=spoke_queue_arns,
    )
)
```

Without this the CDK synth fails; nothing else in this prompt can ship.

### 2. Lambda memory: `256` → `1024` MB

`infra/stacks/compute_stack.py:461`

```python
memory_size=1024,
```

Lambda vCPU scales linearly with memory. 256 MB → ~0.15 vCPU; 1024 MB →
~0.58 vCPU (≈4× more compute). The handler is CPU-sensitive (gzip,
JSON parse, psycopg2 round-trips) and network-sensitive (S3 GET/DELETE,
DB chatter) — both scale with memory in Lambda. Cost is roughly
break-even because invocations finish ~4× faster. Skip 512 (half-measure);
don't go to 1769+ until post-deploy metrics justify it.

### 3. SQS `max_concurrency`: `4` → `6`

`infra/stacks/compute_stack.py:485`

```python
max_concurrency=6,
```

Each warm Lambda holds 1 psycopg2 connection; 6 concurrent = 6 conns, well
under `t4g.small`'s ~170 default `max_connections`. The real ceiling at
higher concurrency is lock contention on the `reviews` primary key during
overlapping `ON CONFLICT` upserts, which starts to show past ~8. 6 is the
sweet spot without RDS Proxy.

Leave `batch_size=100` and `max_batching_window=5s` as-is — already in the
pending diff and appropriate for the 15-minute visibility timeout.

### 4. Refactor `ReviewRepository.bulk_upsert` → `execute_values`

`src/library-layer/library_layer/repositories/review_repo.py` lines 15-61.

Today's loop runs one `cur.execute()` per review. Replace with
`psycopg2.extras.execute_values`, which emits a single `INSERT … VALUES
(...), (...), … ON CONFLICT …` statement. Expected 10-20× speedup on the
review path; `ON CONFLICT` semantics are preserved.

```python
from psycopg2.extras import execute_values

def bulk_upsert(self, reviews: list[dict]) -> int:
    """INSERT ... ON CONFLICT (steam_review_id) DO UPDATE.

    Returns:
        Number of rows processed (not deduplicated count).
    """
    if not reviews:
        return 0
    rows = [
        (
            r["appid"],
            r["steam_review_id"],
            r.get("author_steamid"),
            r["voted_up"],
            r.get("playtime_hours", 0),
            r.get("body", ""),
            r.get("posted_at"),
            r.get("language"),
            r.get("votes_helpful", 0),
            r.get("votes_funny", 0),
            r.get("written_during_early_access", False),
            r.get("received_for_free", False),
        )
        for r in reviews
    ]
    with self.conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO reviews (
                appid, steam_review_id, author_steamid, voted_up, playtime_hours,
                body, posted_at, language, votes_helpful, votes_funny,
                written_during_early_access, received_for_free
            ) VALUES %s
            ON CONFLICT (steam_review_id) DO UPDATE SET
                voted_up                    = EXCLUDED.voted_up,
                playtime_hours              = EXCLUDED.playtime_hours,
                body                        = EXCLUDED.body,
                author_steamid              = EXCLUDED.author_steamid,
                language                    = EXCLUDED.language,
                votes_helpful               = EXCLUDED.votes_helpful,
                votes_funny                 = EXCLUDED.votes_funny,
                written_during_early_access = EXCLUDED.written_during_early_access,
                received_for_free           = EXCLUDED.received_for_free
            """,
            rows,
            page_size=500,
        )
    self.conn.commit()
    return len(rows)
```

`page_size=500` chunks the emitted VALUES clause — keeps planner cost
bounded on very large messages without hurting smaller ones. Return value
stays `len(rows)` to match the docstring's "rows processed (not
deduplicated count)" contract.

### 5. Update infra test

`tests/infra/test_compute_stack.py:107`

```diff
-            "ScalingConfig": {"MaximumConcurrency": 2},
+            "ScalingConfig": {"MaximumConcurrency": 6},
```

The rest of `test_compute_stack_batches_spoke_ingest_sqs_events` already
asserts `BatchSize: 100`, the 5s batching window, and
`ReportBatchItemFailures` — no other changes needed.

## Verification

1. **CDK synth / type check** — after the `)` fix and the two numeric
   bumps, `poetry run pytest tests/infra/` should pass clean.

2. **Repo tests** against `steampulse_test` — the `execute_values` refactor
   is a behavior-preserving change; existing `ReviewRepository` tests
   should pass unchanged:
   ```
   poetry run pytest src/library-layer/tests/repositories/
   ```

3. **Post-deploy CloudWatch** (user applies to prod):
   - `ApproximateNumberOfMessagesVisible` on `steampulse-spoke-results-production`
     trends down; expect a clear inflection within 30-60 min.
   - `SpokeIngestFn` `Duration` drops sharply (memory bump +
     `execute_values` together).
   - `ConcurrentExecutions` hovers at 4-6, not pinned at 6.
   - `SteamPulse/GamesUpserted` + `TagsIngested` counts rise proportionally.
   - RDS `CPUUtilization` stays <70%; watch `CPUCreditBalance` for burst
     drain (signal to right-size, not a current concern).
   - `steampulse-spoke-results-dlq-production` stays flat. Any growth =
     regression from the refactor, investigate first.

## Out of scope

- **RDS Proxy** — unnecessary at ~6 conns used vs. 170 limit. Adds latency
  and cost for no win here. Revisit only if ingest concurrency grows past
  ~10 or a second conn-hungry service lands.
- **Custom `max_connections` parameter group** — defaults are already
  >20× current usage.
- **Further RDS instance size bump** — the repo fix changes the
  performance envelope enough that `t4g.small` should hold for another
  quarter. Re-measure before sizing up.
- **Tightening `max_batching_window` below 5s** — wait for post-deploy
  metrics.
- **Multi-AZ** — separate reliability decision, not a throughput lever.
- **Bulk-ifying metadata / tag paths** — reviews are the dominant row-count
  path (up to ~1000 rows/message vs. tens for tags, one for metadata).
  Only revisit if metrics show tags/metadata dominating after this change.
