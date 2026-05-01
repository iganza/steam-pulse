# revalidate-frontend-discover-inner-build-id

Fix the silent OpenNext page-cache delete bug in `revalidate_frontend`. After every analysis, the Lambda issues an S3 `delete_objects` against a key that does not exist, so the stale page-cache file lingers and CloudFront re-caches stale HTML on the very next request. The pipeline appears to work end-to-end (Lambda logs "Revalidated", invalidation completes) but visitors keep seeing the pre-analysis page.

## Why

OpenNext writes page-cache files under `cache/{OUTER}/{INNER}/games/{appid}/{slug}.cache`. The Lambda assumes `OUTER == INNER` ("the inner BUILD_ID matches after pinning", per the comment at `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py:53-54`). In the live production deploy they do not match.

Reproduced 2026-04-30 for appid 3265700 (vampire-crawlers):

```
$ aws lambda get-function-configuration ... | jq .Environment.Variables.CACHE_BUCKET_KEY_PREFIX
"cache/b5e1077/"

$ aws s3 ls --recursive s3://steampulse-frontend-production/cache/b5e1077/ | grep 3265700
2026-04-30 15:31:57   cache/b5e1077/2b12bbe/games/3265700/vampire-crawlers-the-turbo-wildcard-from-vampire-survivors-3265700.cache
2026-04-30 15:42:52   cache/b5e1077/2b12bbe/games/3265700/vampire-crawlers.cache
```

The Lambda computes the delete key as `cache/b5e1077/b5e1077/games/3265700/...cache` (built from `_CACHE_KEY_PREFIX + _BUILD_ID + ...`), which does not exist. `delete_objects` returns success for missing keys, no S3 `Errors` are surfaced, the Lambda logs "Revalidated", and the actual stale file at `cache/b5e1077/2b12bbe/...` is never touched.

End-to-end consequence after the latest analysis (synthesis 21:56:45, revalidate-frontend "Revalidated" 21:57:10, CloudFront invalidation `IA25K7BS2J2VIF7TDFFA7BZQXH` Completed):
- `/api/games/3265700/report` returns the fresh JSON (one_liner "A dangerously addictive first-person deckbuilder…").
- `/games/3265700/...` HTML returns `x-nextjs-cache: STALE`, `x-cache: Hit from cloudfront`, with the pre-analysis Steam description.
- The stale file's mtime (15:31) is from a prior render; OpenNext re-served it because the delete missed.

This affects every game re-analyzed since the OUTER/INNER build IDs diverged — not just vampire-crawlers.

## Goal

After this prompt:
- `revalidate_frontend` discovers the inner build ID(s) at module load by listing `cache/{OUTER}/` with `Delimiter="/"` and using the returned `CommonPrefixes`.
- `_delete_page_cache` deletes `.cache` and `.cache.meta` keys under **every** discovered inner build ID, so the same Lambda is correct whether the build IDs match (future) or diverge (today).
- Cold start raises loudly if no inner build IDs are found, so a misconfigured deploy can't silently fail again.
- A short comment update so the next reader understands the OUTER/INNER distinction.

## Scope

**In:**
- `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py`: replace the static `_BUILD_ID` parsing with a dynamic discovery, update `_delete_page_cache` to iterate, refresh the comment.
- Update `tests/lambda_functions/revalidate_frontend/test_handler.py` (or wherever the existing tests live) so the new discovery + multi-inner-id delete is covered.

**Out:**
- The `_post_revalidate` flow (POST to `/api/revalidate`). Already correct.
- The CloudFront invalidation (`_invalidate_cdn`). Already correct.
- The `ReportReadyEvent` publish path in `analysis/handler.py` and `batch_analysis/collect_phase.py`. Already correct.
- The OpenNext build itself. Pinning OUTER == INNER would also fix this, but it's a deeper change in the frontend build pipeline and is brittle to future regressions; making the Lambda tolerate the divergence is the durable fix.
- One-time cleanup of stale `.cache` files for previously-broken games. Out of scope here; tracked separately under "Fix-forward cleanup" below.
- No commits, pushes, or deploys. Operator handles those.

## Decisions

1. **Discover at cold start, not per-invocation.** One ListObjectsV2 at module load, cached for the life of the Lambda container. Inner build IDs only change on a new frontend deploy, which replaces the container anyway.

2. **Iterate over all inner IDs, not just the latest.** Cheap defense against a build that leaves multiple inner directories sitting in the bucket (e.g., a partial deploy). Each delete batch is at most ~`2 * len(_INNER_BUILD_IDS)` keys; in practice that's 2 to 4 keys per call.

3. **Fail cold start if zero inner IDs are found.** Same posture as the existing `_require_param`: better to crash visibly than to silently no-op forever.

4. **Keep `_parse_cache_key_prefix` for format validation, but stop returning the inner ID.** The function's value now is "fail fast on a malformed env var", not "give us the inner ID".

5. **No feature flag.** Pre-launch project; just ship the new path forward (per `feedback_no_pre_launch_flags.md`).

## Changes

### 1. `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py`

Replace the current `_parse_cache_key_prefix` + `_CACHE_KEY_PREFIX, _BUILD_ID = ...` block (lines 43-55) with:

```python
def _validate_cache_key_prefix(prefix: str) -> str:
    """Fail loud if CACHE_BUCKET_KEY_PREFIX is malformed."""
    if not prefix.startswith("cache/") or not prefix.endswith("/"):
        raise ValueError(f"CACHE_BUCKET_KEY_PREFIX must match 'cache/{{BUILD_ID}}/': {prefix!r}")
    outer = prefix[len("cache/") : -1]
    if not outer or "/" in outer:
        raise ValueError(f"CACHE_BUCKET_KEY_PREFIX must match 'cache/{{BUILD_ID}}/': {prefix!r}")
    return prefix


_CACHE_KEY_PREFIX = _validate_cache_key_prefix(os.environ["CACHE_BUCKET_KEY_PREFIX"])
_HTTP_TIMEOUT_SECONDS = 5.0
_s3 = boto3.client("s3")
_cloudfront = boto3.client("cloudfront")


def _discover_inner_build_ids() -> list[str]:
    """List subdirs of cache/{OUTER}/ to find OpenNext's inner build ID(s)."""
    response = _s3.list_objects_v2(
        Bucket=_FRONTEND_BUCKET,
        Prefix=_CACHE_KEY_PREFIX,
        Delimiter="/",
    )
    common = response.get("CommonPrefixes") or []
    inner_ids = [p["Prefix"][len(_CACHE_KEY_PREFIX) : -1] for p in common]
    inner_ids = [i for i in inner_ids if i]
    if not inner_ids:
        raise RuntimeError(
            f"No inner build IDs found under s3://{_FRONTEND_BUCKET}/{_CACHE_KEY_PREFIX} "
            "— frontend deploy may be incomplete."
        )
    return inner_ids


# OpenNext writes pages to cache/{OUTER}/{INNER}/... where OUTER comes from
# CACHE_BUCKET_KEY_PREFIX and INNER is OpenNext's own build id; the two do
# not always match, so discover INNER from S3 instead of assuming.
_INNER_BUILD_IDS = _discover_inner_build_ids()
```

Replace `_delete_page_cache` (lines 97-117) with:

```python
def _delete_page_cache(appid: int, slug: str) -> None:
    """Delete OpenNext S3 page-cache files for this game across all inner build IDs.

    Required workaround: OpenNext doesn't tag dynamic-route page entries
    in DynamoDB, so revalidatePath/revalidateTag don't bust them.
    """
    objects = []
    for inner in _INNER_BUILD_IDS:
        base = f"{_CACHE_KEY_PREFIX}{inner}/games/{appid}/{slug}"
        objects.append({"Key": f"{base}.cache"})
        objects.append({"Key": f"{base}.cache.meta"})
    response = _s3.delete_objects(
        Bucket=_FRONTEND_BUCKET,
        Delete={"Objects": objects},
    )
    errors = response.get("Errors") or []
    if errors:
        raise RuntimeError(f"S3 delete_objects errors: {errors}")
```

### 2. Tests

Update the existing `revalidate_frontend` tests:

- Replace any test that asserted `_BUILD_ID` parsing with one that mocks `s3.list_objects_v2` to return `CommonPrefixes` and asserts `_INNER_BUILD_IDS` is populated.
- Add a test that calls `_delete_page_cache` with two mocked inner IDs and asserts the resulting `delete_objects` call lists 4 keys (`.cache` and `.cache.meta` for each inner ID).
- Add a test that mocks `list_objects_v2` returning empty `CommonPrefixes` and asserts module import / `_discover_inner_build_ids` raises `RuntimeError`.

Per `feedback_test_db.md` this Lambda has no DB dependency, so no DB fixture work needed. Per `feedback_no_script_tests.md` only the Lambda code is tested, not operator scripts.

## Files Modified

| File | Change |
|------|--------|
| `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py` | Discover inner build IDs from S3 at cold start; iterate them in `_delete_page_cache`; rename `_parse_cache_key_prefix` to `_validate_cache_key_prefix`; refresh comment |
| `tests/.../test_revalidate_frontend.py` (path TBD by implementer) | Cover the new discovery + multi-inner-id delete; replace any `_BUILD_ID`-coupled assertions |

## Verification

After deploy (operator runs the deploy):

1. **Confirm the Lambda still cold-starts cleanly.** Trigger a synthetic invocation (or wait for the next analysis) and check the log group for the cold-start INIT_START. No `RuntimeError` from `_discover_inner_build_ids`.

2. **Pick a game with a known stale page** (vampire-crawlers, appid 3265700 today) and re-trigger revalidation. Easiest path: re-publish a synthetic `ReportReadyEvent` to the SQS queue, or re-run the analysis pipeline for that appid.

3. **Confirm the S3 stale file was actually deleted:**
   ```bash
   aws s3 ls "s3://steampulse-frontend-production/cache/b5e1077/2b12bbe/games/3265700/"
   ```
   Both `.cache` and `.cache.meta` for the long slug should be gone.

4. **Confirm the page now serves fresh content:**
   ```bash
   curl -sI 'https://d1mamturmn55fm.cloudfront.net/games/3265700/vampire-crawlers-the-turbo-wildcard-from-vampire-survivors-3265700' \
     | grep -iE 'x-cache|x-nextjs-cache|cache-control'
   curl -s 'https://d1mamturmn55fm.cloudfront.net/games/3265700/vampire-crawlers-the-turbo-wildcard-from-vampire-survivors-3265700' \
     | grep -c 'dangerously addictive'
   ```
   Expect: first request `x-cache: Miss from cloudfront`, `x-nextjs-cache: HIT` (fresh render); the grep should return at least 1 (the new one_liner is in the SSR output).

5. **Confirm the API path is unaffected** (sanity, since this prompt does not touch it):
   ```bash
   curl -s 'https://d1mamturmn55fm.cloudfront.net/api/games/3265700/report' | head -c 300
   ```

## Fix-forward cleanup (operator, separate from the code change)

Pages already cached under the wrong-inner-id path will keep serving stale HTML until they're either re-rendered or the stale `.cache` file is removed. Two ways to flush:

- **Targeted (one game):** delete the stale `.cache`/`.cache.meta` and invalidate `/games/{appid}/*` in CloudFront. Same commands as in the previous chat session.
- **Bulk (everything under the divergent inner ID):**
  ```bash
  aws s3 rm --recursive s3://steampulse-frontend-production/cache/b5e1077/2b12bbe/games/
  aws cloudfront create-invalidation --distribution-id E38HJSG1GLX042 --paths '/games/*'
  ```
  Next.js will re-render each page on demand. Safe (no data loss) but cold-renders the next visitor for each page.

The fixed Lambda will keep things correct from the next deploy onward, so this cleanup is only needed once.

## What NOT To Do

- Do NOT pin OPENNEXT_BUILD_ID = git SHA in the frontend build to make OUTER == INNER. It's a different layer and the Lambda fix is more robust (the assumption being violated is the bug; encoding the inverse assumption elsewhere is brittle).
- Do NOT cache `_INNER_BUILD_IDS` to disk or DynamoDB. Module-level cache for the container's lifetime is sufficient and self-healing across deploys.
- Do NOT add a feature flag, env-var override, or "fall back to the old key shape if discovery fails". Either discovery works (then we use it) or it doesn't (then we crash visibly).
- Do NOT widen the prefix-listing call to recurse the whole bucket. Top-level `Delimiter="/"` is fast; a recursive list of `cache/` would scan every page-cache file.
- Do NOT silence the `RuntimeError` on empty `CommonPrefixes`. That's the alarm telling us the deploy is broken.
- Do NOT touch `_post_revalidate`, `_invalidate_cdn`, or the SNS/SQS wiring. Confirmed working end-to-end on 2026-04-30.
- Do NOT bundle the bulk S3 cleanup into the Lambda code change. One-shot operator action; keep the Lambda PR focused.

## Existing Code Reference

- `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py:43-55` — current `_parse_cache_key_prefix` + `_BUILD_ID` (the broken assumption)
- `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py:97-117` — `_delete_page_cache` (the no-op delete)
- `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py:120-143` — `_invalidate_cdn` (correct, untouched)
- `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py:146-177` — handler (correct, untouched)
- `src/lambda-functions/lambda_functions/batch_analysis/collect_phase.py:566-578` — where `ReportReadyEvent` is published from the batch path (correct, untouched)
- `src/lambda-functions/lambda_functions/analysis/handler.py:145-157` — where `ReportReadyEvent` is published from the per-game path (correct, untouched)
- `infra/stacks/compute_stack.py:1042-1043` — where `REVALIDATE_TOKEN_PARAM` and `DISTRIBUTION_ID_PARAM` env vars are wired (untouched, but useful context for `CACHE_BUCKET_KEY_PREFIX` provenance)
