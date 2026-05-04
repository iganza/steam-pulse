# sqs-long-polling

Enable long polling (`receive_message_wait_time_seconds=20`) on every SQS queue defined in `infra/stacks/messaging_stack.py` and `infra/stacks/spoke_stack.py`. The default short polling (WaitTimeSeconds=0) is generating ~303K ReceiveMessage calls per day across the fleet, which blew through 91% of the AWS Free Tier 1M-request/month allowance in the first 3 days of May 2026.

## Why

AWS Free Tier alert (2026-05-03) reported 910,209 SQS requests against the 1M-request monthly cap, with 28 days of the billing window remaining. Investigation traced the volume to Lambda event source mappings polling SQS with the AWS default `WaitTimeSeconds=0`.

Polling math:
- 6 spoke regions x `max_concurrency=3` = 18 spoke pollers
- Primary `app_crawl_queue` and `review_crawl_queue` x `max_concurrency=3` = 6 pollers
- ~24 concurrent short pollers issuing ~1 ReceiveMessage/sec each when their queue has any traffic
- Inline review dispatch (commit `8cce4b1`, 2026-04-27) keeps `review_crawl_queue` warm continuously, so pollers rarely back off

Long polling reduces idle ReceiveMessage volume by ~95% (a 20-second wait per call instead of immediate return), is free, and works transparently with Lambda event source mappings. AWS recommends `WaitTimeSeconds=20` as the default for any queue that is not latency-critical.

## Goal

After this prompt:
- Every `sqs.Queue(...)` construct in `messaging_stack.py` and `spoke_stack.py` declares `receive_message_wait_time_seconds=cdk.Duration.seconds(20)`.
- DLQs included (rare but cheap; consistency beats per-queue exception lists).
- No application code or Lambda handler change required; long polling is a queue-attribute change.
- `cdk diff` shows only `ReceiveMessageWaitTimeSeconds: 20` deltas on the affected queues, no IAM or behavioral diffs.

## Scope

**In:**
- `infra/stacks/messaging_stack.py`: 16 queue constructs (8 main + 8 DLQs).
- `infra/stacks/spoke_stack.py`: 2 queue constructs per spoke (1 main + 1 DLQ); applied to the construct definition, not per-region.

**Out:**
- Changing `max_concurrency` on event source mappings. Long polling is sufficient; throttling concurrency would slow legitimate work.
- Reworking the inline review dispatch in `crawl_service.py:546-583`. The dispatch pattern is correct; it was just exposing the short-polling issue.
- Migrating any queue to FIFO or to a different service. Standard queues + long polling is the right shape.
- Touching the OpenNext-managed queues (the OpenNext construct owns their config; not in `messaging_stack.py` directly).
- Adding CloudWatch alarms on ReceiveMessage rate. Worth doing later, but a separate prompt.
- Any commit, push, or deploy. Operator handles those.

## Decisions

1. **Why 20 seconds and not 10?** 20s is the AWS-documented maximum and the standard recommendation for long polling. It minimizes empty-receive billing without adding noticeable latency to message delivery (Lambda event source mappings receive the message the moment it arrives, regardless of `WaitTimeSeconds`).

2. **Why apply to DLQs too?** DLQs are rarely drained, but when an operator runs a redrive script the script issues ReceiveMessage calls. Long polling on the DLQ keeps redrive cheap and removes a foot-gun (a redrive loop with short polling can rack up requests fast). Cost of applying it to DLQs: zero.

3. **Will Lambda event source mappings still work?** Yes. AWS Lambda's SQS poller respects the queue's `ReceiveMessageWaitTimeSeconds` attribute. With long polling, the poller's empty-receive rate drops; message delivery latency stays sub-second because SQS returns immediately when a message arrives.

4. **Why not also lower `max_concurrency`?** Concurrency is a throughput knob; reducing it would slow review crawls. The right fix is to stop paying per empty poll, not to poll less often when there's work to do.

## Changes

### 1. `infra/stacks/messaging_stack.py`

For every `sqs.Queue(self, "...", ...)` construct in this file (lines 41-160, 16 queues total), add:

```python
receive_message_wait_time_seconds=cdk.Duration.seconds(20),
```

Example diff for `review_crawl_queue` (lines 93-102):

```python
self.review_crawl_queue = sqs.Queue(
    self,
    "ReviewCrawlQueue",
    queue_name=f"steampulse-review-crawl-{env}",
    visibility_timeout=cdk.Duration.minutes(10),
    receive_message_wait_time_seconds=cdk.Duration.seconds(20),
    dead_letter_queue=sqs.DeadLetterQueue(
        max_receive_count=3,
        queue=self.review_crawl_dlq,
    ),
)
```

Apply the same parameter to:
- `metadata_enrichment_dlq` (line 41)
- `review_crawl_dlq` (line 46)
- `batch_staging_dlq` (line 51)
- `cache_invalidation_dlq` (line 56)
- `spoke_results_dlq` (line 61)
- `email_dlq` (line 66)
- `frontend_revalidation_dlq` (line 71)
- `opennext_revalidation_dlq` (line 76)
- `app_crawl_queue` (line 83)
- `review_crawl_queue` (line 93)
- `batch_staging_queue` (line 103)
- `cache_invalidation_queue` (line 112)
- `spoke_results_queue` (line 121)
- `email_queue` (line 132)
- `frontend_revalidation_queue` (line 142)
- `opennext_revalidation_queue` (line 152)

### 2. `infra/stacks/spoke_stack.py`

Apply the same parameter to:
- `spoke_dlq` (line 107)
- `spoke_crawl_queue` (line 117)

Each spoke region instantiates this stack, so the change propagates to all 6 spokes via a single edit.

## Files Modified

| File | Change |
|------|--------|
| `infra/stacks/messaging_stack.py` | Add `receive_message_wait_time_seconds=cdk.Duration.seconds(20)` to 16 `sqs.Queue` constructs |
| `infra/stacks/spoke_stack.py` | Add `receive_message_wait_time_seconds=cdk.Duration.seconds(20)` to 2 `sqs.Queue` constructs |

## Verification

After deploy (operator runs the deploy):

1. Confirm the queue attribute is live on the high-volume queues:
   ```bash
   for q in steampulse-app-crawl-production steampulse-review-crawl-production; do
     url=$(aws sqs get-queue-url --queue-name "$q" --query QueueUrl --output text)
     echo "--- $q ---"
     aws sqs get-queue-attributes \
       --queue-url "$url" \
       --attribute-names ReceiveMessageWaitTimeSeconds \
       --query 'Attributes.ReceiveMessageWaitTimeSeconds' \
       --output text
   done
   ```
   Expect `20` for both.

2. Watch the SQS request rate for 24 hours via Cost Explorer or CloudWatch `NumberOfEmptyReceives` metric on `app_crawl_queue` and `review_crawl_queue`. Empty-receive rate should drop by ~20x.

3. Confirm Lambda event source mappings are still draining queues. `aws lambda list-event-source-mappings` should show `State: Enabled`, and ApproximateNumberOfMessages on the queues should not climb.

4. Re-check Free Tier dashboard at end of May; total SQS requests should be well under 100K/month with the change active for a full billing window.

## What NOT To Do

- Do NOT change `WaitTimeSeconds` per-call on the consumer side. This is a queue-attribute change, not a client change; touching the consumer is unnecessary churn.
- Do NOT lower `max_concurrency` on Lambda event source mappings. That throttles real work; long polling is the right lever.
- Do NOT skip the DLQs. Consistency is cheaper than maintaining a per-queue exception list, and operator redrive scripts benefit.
- Do NOT add a feature flag or env-var override for the wait time. Pre-launch; just ship the new value.
- Do NOT migrate any queue to FIFO. Out of scope and unrelated.
- Do NOT add unit tests for CDK constructs. Per-project convention; `cdk diff` is the verification.
- Do NOT commit, push, or deploy. Operator handles those.

## Existing Code Reference

- `infra/stacks/messaging_stack.py:41-160` is the block holding all 16 queue definitions
- `infra/stacks/spoke_stack.py:107-122` is the per-spoke DLQ + crawl queue definition
- `infra/stacks/compute_stack.py:470-477` is the Lambda event source mapping wiring (`batch_size=10`, `max_concurrency=3`); unchanged
- `src/library-layer/library_layer/services/crawl_service.py:546-583` is `_dispatch_review_crawl()`, the inline review enqueue introduced 2026-04-27 that drove the queue-warmth pattern; unchanged
- `.env.production` lists the 6 spoke regions: us-west-2, us-east-1, eu-west-1, eu-central-1, ap-northeast-1, ap-southeast-1
