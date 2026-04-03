# Single-Writer DB Concurrency Fix

## Context

SteamPulse uses a spoke architecture: SpokeCrawler Lambdas (one per region, no
DB access) fetch from Steam API and push results to `spoke-results-queue` (SQS).
**SpokeIngest** is the single Lambda that reads from that queue and writes to RDS.

The problem: SpokeIngest's SQS event source has no `max_concurrency` cap.
With 10+ spokes pushing results concurrently, Lambda auto-scales SpokeIngest to
match queue depth — potentially 20+ concurrent instances, each holding a
psycopg2 connection. On `db.t4g.micro` (max ~45 connections) this risks
connection exhaustion, especially during bulk crawl.

## Goal

Enforce a true single-writer pattern: **1 concurrent SpokeIngest Lambda at a
time, processing up to 10 results per invocation.** Queue-based backpressure
handles bursts naturally — SpokeIngest drains the queue sequentially.

## Change

**File:** `infra/stacks/compute_stack.py`

Find the `SqsEventSource` added to `ingest_fn` (the SpokeIngest Lambda) and
update it:

```python
# Before
ingest_fn.add_event_source(
    event_sources.SqsEventSource(
        spoke_results_queue,
        batch_size=5,
        report_batch_item_failures=True,
    )
)

# After
ingest_fn.add_event_source(
    event_sources.SqsEventSource(
        spoke_results_queue,
        batch_size=10,          # SQS max; drains a full 10-spoke burst in one pass
        max_concurrency=1,      # single writer — exactly 1 DB connection at all times
        report_batch_item_failures=True,
    )
)
```

## DB Connection Budget After Fix (db.t4g.micro, max ~45 connections)

| Lambda          | Connections | Notes                     |
|-----------------|-------------|---------------------------|
| SpokeIngest     | 1           | Single writer, hard cap   |
| API             | 8–10        | Read-only, scales with traffic |
| ProcessResults  | 1           | Batch analysis only       |
| Migration       | 1           | Deploy-time only          |
| Admin           | 1           | Manual ops                |
| Buffer          | ~31         | Headroom for cold starts  |

## Throughput Impact

With `max_concurrency=1` and `batch_size=10`:
- Each invocation processes up to 10 spoke results
- Each result takes ~200–500ms (S3 fetch + DB upsert)
- Throughput: ~1,200–3,000 results/min
- A 10-spoke crawl burst drains in seconds
- For bulk seed (thousands of games), queue depth builds up and drains
  continuously — total throughput is ample for an overnight crawl

## Verification

After making the change:
1. Run `poetry run cdk synth` — should complete without errors
2. Confirm no `AWS::SecretsManager::Secret` owned resources in data templates
3. The `override_logical_id` for the SpokeIngest event source mapping (staging
   only) references the old logical ID — verify the new mapping still synthesises
   the correct override by checking the staging template
