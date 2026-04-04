# Replace Lambda Async Invoke with Per-Spoke SQS Queues

## Problem

The primary crawler dispatches to spoke Lambdas using `InvocationType="Event"` (async fire-and-forget). Each spoke has `reserved_concurrent_executions=3` to avoid Steam rate limits. During a bulk backfill of 27k games, the primary floods all 12 spokes with async invocations simultaneously. Lambda's internal async queue overflows, invocations are retried twice, then silently dropped — losing those games entirely with no error surfaced.

Root cause: We're using Lambda async invocation as a queue, but it has no backpressure. The async queue is not durable.

Additionally, review pagination re-queues take an unnecessary round-trip: ingest → `review_crawl_queue` → primary crawler → re-dispatch to spoke. Direct re-queue to the spoke's queue eliminates this.

## Solution

Replace the async Lambda invocation with a per-spoke SQS queue. Each of the 12 spoke regions gets its own SQS queue. The primary puts messages there instead of invoking the spoke directly. The spoke Lambda has an SQS event source mapping on its local queue with `max_concurrency=3`. Messages sit patiently in SQS (durable, 14-day retention, DLQ on failure) and are consumed at the spoke's own pace. Re-queuing for paginated review crawls goes directly to the per-spoke queue, bypassing the primary crawler dispatcher.

## Scope of Changes

### Infrastructure (CDK)

**`infra/stacks/spoke_stack.py`**
- Add `spoke_crawl_queue` with deterministic name `steampulse-spoke-crawl-{region}-{env}`
  - `visibility_timeout=Duration.minutes(12)` (> 10min Lambda timeout)
  - `retention_period=Duration.days(14)`
  - DLQ: repurpose existing `spoke_dlq` (keep CDK construct ID to avoid replacement), `max_receive_count=3`
- Add SQS event source mapping: `batch_size=1`, `max_concurrency=3`, `report_batch_item_failures=True`
- Remove `reserved_concurrent_executions=3` from spoke Lambda
- Remove `configure_async_invoke(on_failure=..., retry_attempts=2)`
- Add SSM parameter for crawl queue URL

**`infra/application_stage.py`**
- Construct deterministic spoke queue URLs before compute stack
- Pass `spoke_crawl_queue_urls` string to ComputeStack

**`infra/stacks/compute_stack.py`**
- Accept `spoke_crawl_queue_urls` constructor param
- Replace `lambda:InvokeFunction` IAM policy with `sqs:SendMessage` on spoke queue ARNs
- Pass `SPOKE_CRAWL_QUEUE_URLS` env var to crawler and ingest Lambdas

### Handler Code

**`src/library-layer/library_layer/config.py`**
- Add `SPOKE_CRAWL_QUEUE_URLS: str = ""` field
- Add `spoke_crawl_queue_url_list` property (mirrors `spoke_region_list`)

**`src/lambda-functions/lambda_functions/crawler/handler.py`**
- Replace `_spoke_targets` (Lambda clients) with `_spoke_sqs_targets` (SQS clients + queue URLs)
- Replace `_dispatch_to_spoke()`: `sqs_client.send_message()` instead of `client.invoke(InvocationType="Event")`
- Same modulo routing: `appid % len(targets)`

**`src/lambda-functions/lambda_functions/crawler/spoke_handler.py`**
- Add Powertools `BatchProcessor` for SQS record unwrap
- Handler receives SQS event with `Records[]` instead of raw payload
- Remove `SpokeResponse` returns (SQS ESM doesn't use return values)

**`src/lambda-functions/lambda_functions/crawler/ingest_handler.py`**
- Build spoke SQS targets at cold start (same pattern as primary crawler)
- Review re-queue sends `ReviewSpokeRequest` directly to spoke queue instead of `review_crawl_queue`
- Eliminates round-trip through primary crawler for pagination

**`src/lambda-functions/lambda_functions/crawler/events.py`**
- Remove `SpokeResponse` model (dead code after spoke_handler change)

### Config Files
- `.env.staging`, `.env.production`, `.env.example` — Add `SPOKE_CRAWL_QUEUE_URLS=` placeholder (CDK overrides at deploy)

### Tests
- `tests/handlers/test_spoke_handler.py` — SQS event envelope wrapping, `BatchProcessingError` assertions
- `tests/handlers/test_crawler_handler.py` — `_spoke_sqs_targets` + `send_message` instead of `_spoke_targets` + `invoke`
- `tests/handlers/test_ingest_handler.py` — Mock spoke SQS targets for re-queue assertions
- `tests/infra/test_spoke_stack.py` — Assert ESM exists, queue exists, no reserved concurrency, 2 SSM params
- `tests/infra/test_compute_stack.py` — Pass `spoke_crawl_queue_urls` to constructor
- `tests/conftest.py` — Add `SPOKE_CRAWL_QUEUE_URLS` to test env defaults

## Deployment

Clean cutover — single `bash scripts/deploy.sh --env staging`. CDK dependency order ensures spoke stacks (with new queues) deploy before compute stack.

## Verification

1. `poetry run cdk synth` — no errors
2. `poetry run pytest -v` — all tests pass
3. Deploy to staging, seed 50 games, verify spoke queues drain and DLQs are empty
4. Seed 1000 games, verify backpressure: `ApproximateNumberOfMessagesVisible` grows then drains at 3 concurrent
