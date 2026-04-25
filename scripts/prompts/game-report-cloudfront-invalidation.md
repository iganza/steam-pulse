# CloudFront Edge Invalidation for Game Report Pages

## Context

`feature/game-report-cache-invalidation` (PR #130) closed the Next.js
data-cache half of "cache-until-changed" for `/games/[appid]/[slug]`:
re-analysis fires `ReportReadyEvent` → SQS → `RevalidateFrontendFn` →
POST `/api/revalidate` → `revalidateTag('game-${appid}', 'max')`. The
OpenNext data cache (S3 + DynamoDB) is now correctly busted.

**The remaining gap**: CloudFront edge HTML cache is *not* invalidated.
With `revalidate = 31536000` on the page, OpenNext emits
`Cache-Control: s-maxage=31536000, stale-while-revalidate=…`. CloudFront
honors that and caches the rendered HTML at every PoP for one year.
`revalidateTag` mutates state *inside the Lambda's storage* — CloudFront
never sees it. So:

- A viewer in Tokyo who loads the page on day 1 will keep seeing day-1
  HTML until either (a) `s-maxage` expires (1 year), (b) someone runs
  `scripts/invalidate-cdn.sh`, or (c) they happen to hit a different
  edge node that hasn't cached the page.
- `stale-while-revalidate` only kicks in *after* `s-maxage` expires, so
  it doesn't help here.

**Goal**: when a report re-analyses, both the Next.js data cache *and*
the CloudFront edge cache invalidate within seconds, so the next viewer
at any edge sees the fresh report. Zero manual intervention, no
technical debt left behind.

**Non-goal**: changing the on-origin caching strategy. The 1-year
`revalidate` window is intentional — we want CloudFront to hold HTML
indefinitely for unchanged reports. We just need a precise
invalidation signal when *something* does change.

## Best-practice foundation

- **CloudFront invalidations are by path**, not by tag — the API call
  is `create_invalidation(Paths=['/games/123/*'])`. Wildcards are fine.
- **Pricing**: first 1,000 invalidation paths/month are free; $0.005
  per path after. At our wedge volume (~200 games × ~30 re-analyses
  /month = ~6,000 paths) that's ~$25/month — acceptable, and we can
  batch to reduce API-call pressure (CloudFront caps at 15 concurrent
  invalidations per distribution).
- **One path per appid covers everything**: `/games/${appid}/*` matches
  the canonical page (`/games/${appid}/${slug}`) and any RSC/segment
  payloads under it. The HTML cache policy already varies on RSC
  headers, but invalidation operates on the path key, not the variant.
- **Distribution ID lives in SSM already**: `DeliveryStack` exports
  `/steampulse/{env}/delivery/distribution-id` at line 169-174.
  ComputeStack synth-time can't read it (DeliveryStack depends on
  ComputeStack — circular), so the Lambda must fetch it at runtime.

## Design

Extend the existing `RevalidateFrontendFn` to also fire a CloudFront
invalidation after the `/api/revalidate` POST succeeds. Single Lambda,
single SQS event source, two side effects in sequence.

### 1. ComputeStack — IAM + env

`infra/stacks/compute_stack.py` (within the existing
`# ── Revalidate-Frontend Lambda` block):

- Add to `revalidate_role`:
  ```python
  revalidate_role.add_to_policy(
      iam.PolicyStatement(
          actions=["cloudfront:CreateInvalidation"],
          resources=[
              f"arn:aws:cloudfront::{self.account}:distribution/*"
          ],
      )
  )
  ```
  CloudFront IAM only supports `*` for distribution resources or full
  ARNs — we use `*` because the distribution ID is resolved at
  runtime, not synth time.
- Add to `revalidate_role` SSM read scope (already grants the token
  param; widen to also read the distribution ID):
  ```python
  resources=[
      f"arn:aws:ssm:{self.region}:{self.account}:parameter/steampulse/{env}/frontend/revalidate-token",
      f"arn:aws:ssm:{self.region}:{self.account}:parameter/steampulse/{env}/delivery/distribution-id",
  ],
  ```
- Add to `revalidate_fn.environment`:
  ```python
  DISTRIBUTION_ID_PARAM=f"/steampulse/{env}/delivery/distribution-id",
  ```

No DeliveryStack changes needed — the SSM export already exists.

### 2. Lambda handler — sequence the two side effects

`src/lambda-functions/lambda_functions/revalidate_frontend/handler.py`:

- At cold start, alongside the existing token fetch, also fetch the
  distribution ID from SSM and construct a boto3 CloudFront client.
- For each SQS record: after `_post_revalidate(appid)` succeeds, call
  `_invalidate_cdn(appid)` which issues
  `create_invalidation(DistributionId=…, InvalidationBatch={...})` with
  `Paths=['/games/${appid}/*']` and `CallerReference=f"{appid}-{ts}"`.
- Both calls must succeed for the message to be acked. If
  `revalidateTag` succeeds but CloudFront fails, the message goes to
  DLQ — operationally the data cache is fresh but the edge is stale,
  which the DLQ alarm will surface.
- **Batching optimization** (worth doing now, not later): collect
  appids across all records in the batch; issue one
  `create_invalidation` covering all paths. CloudFront accepts up to
  3,000 paths per invalidation; our SQS batch_size=10 fits trivially.
  Reduces concurrent-invalidation pressure under burst.

### 3. CDK / DeliveryStack — no changes needed

The distribution ID is already exported. The CloudFront cache policy
stays as-is (HTML `default_ttl=0`, origin's `Cache-Control` drives
behavior). The 1-year `s-maxage` from OpenNext stays — we want long
edge caching, just with precise invalidation on change.

## Critical files

**Edit:**
- `infra/stacks/compute_stack.py` — IAM permission, SSM scope, env var
  on the existing `RevalidateFrontendFn` block
- `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py`
  — fetch distribution ID at cold start, batch appids, call
  `create_invalidation` after `/api/revalidate` POSTs succeed

**Reference (no edits):**
- `infra/stacks/delivery_stack.py:169-174` — distribution-id SSM export
  is already there
- `scripts/invalidate-cdn.sh` — keep as manual escape hatch

## Verification

**Local**: not feasible — CloudFront only exists in deployed envs. The
boto3 mock isn't worth wiring for this.

**Staging**:
1. Deploy. Confirm IAM policy on `RevalidateFrontendFn` includes
   `cloudfront:CreateInvalidation`.
2. Pick a known appid. Hit `/games/${appid}/${slug}` from at least
   two distinct geographic locations (curl with `-H 'CloudFront-Viewer-Country: …'`
   or actual browsers from VPN endpoints) until both report
   `x-cache: Hit from cloudfront`.
3. Trigger a re-analysis for that appid via Step Functions.
4. Watch CloudWatch logs for `RevalidateFrontendFn` — expect both the
   `/api/revalidate` POST and the `create_invalidation` call within
   seconds of the `ReportReadyEvent`.
5. List invalidations: `aws cloudfront list-invalidations
   --distribution-id $(aws ssm get-parameter --name
   /steampulse/staging/delivery/distribution-id --query
   Parameter.Value --output text)`. Most-recent should reference
   `/games/${appid}/*`.
6. Re-fetch from both locations. Both should now report
   `x-cache: Miss from cloudfront` then `Hit` on the subsequent
   request, with the fresh report content.

**Rollback**: revert the handler changes and the IAM/env additions in
ComputeStack. The SQS → revalidate-frontend → /api/revalidate path
keeps working; only the CloudFront invalidation stops firing. Manual
escape hatch (`scripts/invalidate-cdn.sh`) remains.

## Cost & operational notes

- **At wedge volume (~200 tracked games)**: assuming each gets
  re-analysed ≤30×/month, that's ~6,000 invalidation paths/month →
  ~$25/month after the 1,000-path free tier. Worth it to close the
  gap.
- **At 10× scale (2,000 games, monthly cadence)**: ~2,000 paths/month
  → ~$5/month. Still cheap.
- **CloudFront invalidation latency**: typically 30s–5min to propagate
  globally. Acceptable for analyst-facing reports.
- **Failure mode**: if CloudFront throws (rate limit, transient AWS
  error), the SQS message retries up to 3× then lands in the DLQ. The
  DLQ alarm should already exist via MonitoringStack — confirm during
  staging deploy.

## Explicitly out of scope

- Changing the data-cache `revalidate` TTL or the OpenNext cache
  policy
- Moving the revalidate token from synth-time SSM resolution to
  runtime fetch (separate cleanup, not load-bearing)
- Genre / tag / developer / publisher pages (same pattern will apply
  when we extend the data-cache PR to those routes; do then)
- Homepage / catalog / discovery feeds (short-TTL time-based caching
  by design)
- CloudFront tag-based invalidation (CloudFront doesn't support it;
  paths are sufficient for our key shape)

## Sources

- [CloudFront invalidation pricing](https://aws.amazon.com/cloudfront/pricing/)
- [CreateInvalidation API reference](https://docs.aws.amazon.com/cloudfront/latest/APIReference/API_CreateInvalidation.html)
- [boto3 CloudFront.Client.create_invalidation](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudfront/client/create_invalidation.html)
- [OpenNext caching internals](https://opennext.js.org/aws/inner_workings/caching)
