# OpenNext Revalidation Pipeline

## Context

`feature/game-report-cache-invalidation` (PR #130) wired `revalidateTag('game-${appid}', 'max')` into the OpenNext data cache. It works — `RevalidateFrontendFn` is firing, the route handler is calling `revalidateTag`, the tag is being marked invalidated in the OpenNext DynamoDB cache table.

But end-to-end testing on production reveals the cache **never actually refreshes**. Every hit on a previously-cached page returns `x-nextjs-cache: STALE` indefinitely, and the rendered HTML keeps the pre-invalidation `last_analyzed`. CloudWatch logs on `FrontendFn` show why:

```
ERROR Failed to revalidate stale page /games/3205380/omelet-you-cook-3205380
QueueDoesNotExist: The specified queue does not exist.
```

OpenNext's design splits the data cache from the re-render path:

1. Server function checks the data cache. Fresh → serve. Stale → serve stale + **enqueue** a re-render request to an internal SQS queue.
2. A separate `revalidation-function` Lambda consumes from that queue, re-renders the page, writes the fresh entry back to the data cache.

We provisioned the cache (DynamoDB + S3) but never provisioned (a) the revalidation queue or (b) the `revalidation-function` Lambda. So step 2 throws `QueueDoesNotExist`, the cache entry stays stale forever, and viewers see pre-invalidation HTML.

**Goal**: provision the missing OpenNext revalidation pipeline so that `revalidateTag` actually leads to a re-render. After this lands, the full cache-until-changed loop closes:

- `report-ready` SNS → SQS → `RevalidateFrontendFn` → POST `/api/revalidate` → `revalidateTag(...)` → mark stale in DynamoDB → next hit serves stale **and** enqueues re-render → revalidation Lambda re-renders → next hit after that returns fresh.

**Scope**: just the OpenNext revalidation queue + Lambda + env wiring. Do not touch the existing `RevalidateFrontendFn`, the SNS topic, the `frontend_revalidation_queue`, or the route handler — those are working.

**Non-goal**: CloudFront edge invalidation. Tracked separately in `scripts/prompts/game-report-cloudfront-invalidation.md`.

## Best-practice foundation

- **OpenNext bundle is already built**: `frontend/.open-next/revalidation-function/` exists after `open-next build`. The Lambda only needs an `aws_lambda.Function` pointing at that bundle, plus the right env vars.
- **OpenNext's expected env var**: the server function reads `REVALIDATION_QUEUE_URL` (and `REVALIDATION_QUEUE_REGION`) at runtime to know where to enqueue. Without those set, it falls back to a default name that doesn't exist → `QueueDoesNotExist`.
- **Queue config**: long visibility timeout (≥ render budget; matches OpenNext's recommended 60s+), DLQ to surface render failures, FIFO not required (OpenNext deduplicates by path internally).
- **Concurrency**: revalidation is bursty when many tags invalidate at once (e.g., a re-analyze cycle). `reserved_concurrent_executions` of 5–10 keeps cost bounded; OpenNext's queue tolerates backpressure.
- **Same env as `FrontendFn`**: revalidation function reads/writes the same OpenNext cache → it needs the same `CACHE_BUCKET_NAME`, `CACHE_BUCKET_REGION`, `CACHE_BUCKET_KEY_PREFIX`, `CACHE_DYNAMO_TABLE`, `API_URL`. Use the same values literally.

## Design

### 1. Messaging — new SQS queue

`infra/stacks/messaging_stack.py`:

```python
self.opennext_revalidation_dlq = sqs.Queue(
    self,
    "OpenNextRevalidationDlq",
    retention_period=cdk.Duration.days(14),
)
self.opennext_revalidation_queue = sqs.Queue(
    self,
    "OpenNextRevalidationQueue",
    visibility_timeout=cdk.Duration.minutes(5),
    dead_letter_queue=sqs.DeadLetterQueue(
        max_receive_count=3,
        queue=self.opennext_revalidation_dlq,
    ),
)
# Tag both with steampulse:service=frontend.
# Export queue URL + ARN to SSM for the compute stack.
```

Deliberately **not** subscribed to any SNS topic — the producer is `FrontendFn` itself (via the OpenNext runtime), not an external event source. OpenNext sends messages directly via the AWS SDK.

### 2. Compute — revalidation Lambda + env on FrontendFn

`infra/stacks/compute_stack.py`:

- Accept the new queue as a constructor param: `opennext_revalidation_queue: sqs.IQueue`.
- After the existing `frontend_fn = lambda_.Function(...)` block:
  - Grant `frontend_fn.role` permission to send to `opennext_revalidation_queue` (`opennext_revalidation_queue.grant_send_messages(frontend_fn)`).
  - Add `REVALIDATION_QUEUE_URL` and `REVALIDATION_QUEUE_REGION` to the FrontendFn `environment` dict.
- Add a new Lambda mirroring the FrontendFn pattern (Node.js 22, no VPC, OpenNext bundle):

```python
_OPEN_NEXT_REVALIDATION = "frontend/.open-next/revalidation-function"
if os.path.isdir(_OPEN_NEXT_REVALIDATION):
    revalidation_code = lambda_.Code.from_asset(_OPEN_NEXT_REVALIDATION)
    revalidation_runtime = lambda_.Runtime.NODEJS_22_X
else:
    revalidation_code = lambda_.Code.from_inline(
        "exports.handler = async () => ({ statusCode: 200 });"
    )
    revalidation_runtime = lambda_.Runtime.NODEJS_22_X

opennext_revalidation_fn = lambda_.Function(
    self,
    "OpenNextRevalidationFn",
    runtime=revalidation_runtime,
    handler="index.handler",
    code=revalidation_code,
    memory_size=512,
    timeout=cdk.Duration.minutes(2),
    reserved_concurrent_executions=5,
    log_group=logs.LogGroup(
        self,
        "OpenNextRevalidationLogs",
        log_group_name=f"/steampulse/{env}/opennext-revalidation",
        retention=logs.RetentionDays.ONE_WEEK,
        removal_policy=cdk.RemovalPolicy.DESTROY,
    ),
    environment={
        "NODE_ENV": "production",
        "API_URL": self.api_fn_url.url,
        "CACHE_BUCKET_NAME": frontend_bucket.bucket_name,
        "CACHE_BUCKET_REGION": self.region,
        "CACHE_BUCKET_KEY_PREFIX": f"cache/{self.node.try_get_context('build-id') or 'local'}/",
        "CACHE_DYNAMO_TABLE": opennext_cache_table.table_name,
    },
)
frontend_bucket.grant_read_write(opennext_revalidation_fn)
opennext_cache_table.grant_read_write_data(opennext_revalidation_fn)
opennext_revalidation_fn.add_event_source(
    event_sources.SqsEventSource(
        opennext_revalidation_queue,
        batch_size=5,
        max_batching_window=cdk.Duration.seconds(2),
        report_batch_item_failures=True,
    )
)
```

Tag the function with `steampulse:service=frontend`, `steampulse:tier=critical` (a stuck revalidation queue means stale pages forever).

### 3. ApplicationStage — wire the queue through

`infra/application_stage.py`:

```python
opennext_revalidation_queue=messaging.opennext_revalidation_queue,
```

In the `ComputeStack(...)` call alongside the existing queue params.

### 4. CDK / DeliveryStack / SNS — no changes

This pipeline is fully internal to OpenNext; no CloudFront, SNS, or external integration changes are required.

## Critical files

**Edit:**
- `infra/stacks/messaging_stack.py` — add `opennext_revalidation_queue` + DLQ + SSM exports
- `infra/stacks/compute_stack.py` — accept queue param; add env vars + send permission to `FrontendFn`; add `OpenNextRevalidationFn` + SQS event source
- `infra/application_stage.py` — pass the new queue from MessagingStack to ComputeStack
- `tests/infra/test_compute_stack.py` and `tests/infra/test_messaging_stack.py` — update fixtures and subscription/queue counts

**Reference (no edits):**
- `frontend/.open-next/revalidation-function/` — bundle output by `open-next build`; the Lambda code lives here
- `frontend/.open-next/open-next.output.json` — OpenNext's declaration of the function and its expected wiring

## Verification

**Local synth**:

```sh
ENVIRONMENT=production poetry run cdk synth --quiet
grep -l OpenNextRevalidation cdk.out/assembly-SteamPulse-Production/*.template.json
```

Should match in both Compute and Messaging templates.

**Production smoke test** (requires deploy):

1. After deploy, confirm `REVALIDATION_QUEUE_URL` appears in `aws lambda get-function-configuration --function-name <FrontendFn>` env vars.
2. Re-run the proof loop from the prior cache-until-changed test:
   - Bump `games.last_analyzed` for appid 3205380 in the prod DB
   - Invoke `RevalidateFrontendFn` with a synthetic SQS event
   - Hit `https://<frontend-fn-url>/games/3205380/...` once → `x-nextjs-cache: STALE` (expected, this enqueues the re-render)
   - Wait 5–10 seconds
   - Hit again → `x-nextjs-cache: HIT` and the rendered HTML shows the new `last_analyzed`
3. Tail `/steampulse/production/opennext-revalidation` — should see one invocation per re-rendered path.
4. Confirm DLQ depth stays at 0.

**Rollback**: revert the messaging + compute stack edits. The OpenNext server function falls back to `QueueDoesNotExist` errors but the rest of the system keeps working — pages just stay STALE again.

## Cost notes

- SQS: free tier covers ≪1M requests/month; one revalidation per re-analysis × ~200 wedge games × <30 cycles/month = ~6,000 messages — free.
- Lambda: per render = same cost as a normal SSR request (~1s × 512MB). At wedge volume, well under $1/month.
- DynamoDB: revalidation reads/writes the existing `OpenNextCacheTable` — already pay-per-request, marginal.

Total expected delta: under $5/month at 10× scale.

## Out of scope

- CloudFront edge invalidation (separate prompt: `scripts/prompts/game-report-cloudfront-invalidation.md`)
- Migrating the existing `RevalidateFrontendFn` or messaging plumbing
- Genre / tag / developer / publisher pages (same fix lands automatically once they adopt the data-cache pattern)
- OpenNext warmer function (separate concern; reduces cold-start latency, not correctness)

## Sources

- [OpenNext AWS revalidation flow](https://opennext.js.org/aws/inner_workings/components/revalidation_function)
- [OpenNext open-next.output.json schema](https://opennext.js.org/aws/inner_workings/architecture)
- [Next.js revalidateTag](https://nextjs.org/docs/app/api-reference/functions/revalidateTag)
