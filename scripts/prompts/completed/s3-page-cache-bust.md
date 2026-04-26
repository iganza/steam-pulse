# Direct S3 Page-Cache Bust (Workaround for OpenNext Dynamic-Route Limitation)

## Context

After landing all four prior cache PRs (`feature/game-report-cache-invalidation` → `feature/opennext-revalidation-pipeline` → `feature/pin-next-build-id` → `feature/revalidate-page-and-tag`), end-to-end production testing proved the loop **still doesn't bust the rendered page HTML**.

Hands-on diagnostics:

- `revalidateTag('game-${appid}', 'max')` writes a fresh `revalidatedAt` to DynamoDB → confirmed in the table → page still `HIT`.
- `revalidatePath('/games/${appid}/${slug}')` runs without error → no DynamoDB write happens for that path → page still `HIT`.
- Manual `aws s3 rm cache/{BUILD_ID}/{BUILD_ID}/games/{appid}/{slug}.cache` → next hit is `MISS` → re-renders fresh → next hit is `HIT` ✅.

**Root cause** (OpenNext architectural limitation): `dynamodb-cache.json` is only pre-populated with `_N_T_/<route>` entries for routes whose paths are known at build time. Dynamic routes with empty `generateStaticParams` (`/games/[appid]/[slug]`) get *zero* page-tag entries. So neither `revalidateTag` nor `revalidatePath` has anything to mark stale at the page-cache level. The `__fetch/...` entries do get tagged at runtime (and `revalidateTag` correctly busts them), but the page HTML lives in S3 with no DynamoDB linkage and persists indefinitely.

This is the *fifth* loop revealed by testing. Each prior fix was correct in isolation. The only reliable way to bust the dynamic-page S3 cache is to delete the file directly.

**Goal**: extend `RevalidateFrontendFn` to also `s3:DeleteObject` the page cache file (and its `.meta` companion) for `/games/${appid}/${slug}` after the existing `/api/revalidate` POST succeeds. Two side effects per message; both must succeed for the message to ack.

**Non-goal**: removing `revalidateTag`/`revalidatePath`. They remain useful (tag busts the shared fetches so the re-render gets fresh data; path call is a no-op today but costs nothing and stays defensive against future OpenNext fixes). Just add the S3 delete.

## Best-practice foundation

- **OpenNext's S3 cache key format** (verified): `${CACHE_BUCKET_KEY_PREFIX}${NEXT_BUILD_ID}/games/${appid}/${slug}.cache` plus a `.cache.meta` companion. After `feature/pin-next-build-id`, both prefix and BUILD_ID equal the git short SHA — they're the same value, written once per deploy.
- **`s3:DeleteObject` on a missing key is idempotent** — 204 No Content, no error. Safe to call when the page was never cached.
- **Order matters slightly**: do `/api/revalidate` (busts fetches) *before* `s3:DeleteObject` (busts page). On the next request, the re-render then uses fresh fetches. Reverse order opens a microscopic race window where a request between delete and tag-bust could re-render with stale fetch data.
- **Both calls must succeed** before the SQS message acks — partial success would leave the page entry stale-but-undeletable, which is exactly the bug we're fixing.

## Design

### 1. Env wiring on `RevalidateFrontendFn`

`infra/stacks/compute_stack.py` — extend the existing `RevalidateFrontendFn` block:

- Add env vars (so the Lambda can construct the S3 path at runtime):
  ```python
  FRONTEND_BUCKET=frontend_bucket.bucket_name,
  CACHE_BUCKET_KEY_PREFIX=f"cache/{self.node.try_get_context('build-id') or 'local'}/",
  ```
  The prefix has to match `FrontendFn`'s value exactly so we point at the same files.
- Grant S3 delete permission scoped to the cache prefix:
  ```python
  frontend_bucket.grant_delete(revalidate_fn, f"cache/*")
  ```
  Or a tighter `grant` if `bucket.grant_delete` doesn't support prefix scoping — fall back to a manual `iam.PolicyStatement` with `s3:DeleteObject` on `arn:.../cache/*`.

No DeliveryStack changes. Bucket already exists; the path glob covers all build IDs (so this works across deploys).

### 2. Lambda handler — add S3 delete after POST

`src/lambda-functions/lambda_functions/revalidate_frontend/handler.py`:

- At cold start: `_FRONTEND_BUCKET = os.environ["FRONTEND_BUCKET"]`, `_CACHE_PREFIX = os.environ["CACHE_BUCKET_KEY_PREFIX"]`. Construct a `boto3.client("s3")` once.
- After `_post_revalidate(appid, slug)` succeeds, call `_delete_page_cache(appid, slug)`:
  ```python
  build_id = _CACHE_PREFIX.removeprefix("cache/").rstrip("/")  # "b6d74d6"
  base_key = f"{_CACHE_PREFIX}{build_id}/games/{appid}/{slug}"  # cache/b6d74d6/b6d74d6/games/3205380/omelet-you-cook-3205380
  s3.delete_objects(
      Bucket=_FRONTEND_BUCKET,
      Delete={"Objects": [
          {"Key": f"{base_key}.cache"},
          {"Key": f"{base_key}.cache.meta"},
      ]},
  )
  ```
  `delete_objects` is idempotent at the per-key level: deleting non-existent keys returns 200 with no `Errors` array. We don't need to inspect `Errors` unless we want a strict mode.
- Add a `PageCacheBust` metric increment alongside the existing `OriginRevalidationsSucceeded` (the per-record origin success counter; renamed from `RevalidationsSucceeded` in `feature/game-report-cloudfront-invalidation` once full-pipeline success became a separate `CdnInvalidations` metric).
- Failure handling unchanged — exceptions bubble, SQS retries, eventual DLQ.

### 3. Tests

`tests/handlers/test_revalidate_frontend_handler.py`:

- Add `_FRONTEND_BUCKET` env + `mock_aws` S3 bucket in the autouse fixture (extend `_seed_ssm` to create the bucket).
- Modify the happy-path test to assert `delete_objects` was called with the expected two keys (use `boto3.client("s3").list_objects_v2` after invocation, or inspect the moto bucket directly).
- Add a "delete fails → batch failure" case (use `monkeypatch` to make the s3 client raise).
- The existing token-failure / non-2xx HTTP / missing-slug tests stay valid — they short-circuit before reaching the S3 delete.

### 4. Out of scope

- Touching `/api/revalidate`, `frontend/lib/api.ts`, the page tsx, or any other PR's diff. Pure additive change to the Lambda + IAM.
- CloudFront edge invalidation (separate prompt: `game-report-cloudfront-invalidation.md` — *landed*; `RevalidateFrontendFn` now also issues `cloudfront:CreateInvalidation` after the S3 delete succeeds).
- Migrating off the workaround once OpenNext supports dynamic-route tag invalidation upstream — file an issue and revisit.

## Critical files

**Edit:**
- `infra/stacks/compute_stack.py` — add `FRONTEND_BUCKET` + `CACHE_BUCKET_KEY_PREFIX` env vars and `s3:DeleteObject` grant on the existing `RevalidateFrontendFn` block.
- `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py` — add `_delete_page_cache(appid, slug)`; call after `_post_revalidate`; add metric.
- `tests/handlers/test_revalidate_frontend_handler.py` — extend fixture for S3; assert delete keys; add failure case.

**Reference (no edits):**
- `frontend/.open-next/server-functions/default/...` — confirms the S3 path format used by OpenNext for cached pages.
- `infra/stacks/compute_stack.py` (existing FrontendFn block) — `CACHE_BUCKET_KEY_PREFIX` is the same value we mirror onto the revalidate Lambda.

## Verification

**Local**:
```sh
poetry run pytest tests/handlers/test_revalidate_frontend_handler.py
poetry run pytest tests/infra/
ENVIRONMENT=production poetry run cdk synth --quiet
```
All green; synth includes the new IAM policy + env vars on `RevalidateFrontendFn`.

**Production** (after deploy):
1. Hit `/games/3205380/omelet-you-cook-3205380` via Function URL → `MISS` then `HIT`.
2. Synthetic invoke `RevalidateFrontendFn` (payload includes appid + slug).
3. Confirm `RevalidateFrontendFn` logs show both the POST success **and** the S3 delete success.
4. Confirm S3 file is gone: `aws s3 ls s3://steampulse-frontend-production/cache/<BUILD_ID>/<BUILD_ID>/games/3205380/` → empty.
5. Hit the page again → `MISS` (re-render triggered).
6. Hit a third time → `HIT` with the just-rendered fresh content.
7. Bonus: trigger a real re-analysis via Step Functions; confirm steps 3–6 happen automatically.

**Rollback**: revert the handler changes and the IAM/env additions in ComputeStack. The `/api/revalidate` POST keeps firing (no-op for the page cache, as we already proved). Manual `invalidate-cdn.sh` remains as the escape hatch.

## Why this is "the right end state for now"

- **Closes the loop end-to-end** — first time in five PRs that a re-analysis actually changes what viewers see (origin-side; CloudFront edge invalidation is the separate next step).
- **No OpenNext fork or custom adapter** — works around the limitation with one IAM grant + a `delete_objects` call.
- **Forward-compatible** — when OpenNext eventually supports dynamic-route page invalidation natively, we can remove the S3 delete and the system keeps working via `revalidatePath`.
- **Cheap** — `delete_objects` is fractions of a cent per call; no new infra.

## Sources

- [OpenNext caching internals (cache key layout)](https://opennext.js.org/aws/inner_workings/caching)
- [OpenNext Tag Cache override (pre-population requirement)](https://opennext.js.org/aws/config/overrides/tag_cache)
- [boto3 `delete_objects` docs](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/delete_objects.html)
- [Next.js revalidatePath (still called for forward-compat)](https://nextjs.org/docs/app/api-reference/functions/revalidatePath)
