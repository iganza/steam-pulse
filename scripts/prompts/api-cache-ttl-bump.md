# api-cache-ttl-bump

Cut Lambda invocations on the four `/api/games/{appid}/*` SSR-fanout endpoints by ~7x by raising their CloudFront edge TTL from 24h to 7 days. The pipeline-driven CloudFront invalidation already covers every legitimate cache-bust trigger (analysis-complete SNS event), so a longer `s-maxage` is safe. The 24h ceiling is a relic from before that invalidation existed.

## Why

Production verification on `d1mamturmn55fm.cloudfront.net` (2026-04-30) shows the cache layers behave as intended:

```
GET /api/games/3265700/report
  1st hit: x-cache: Miss from cloudfront, cache-control: s-maxage=86400, stale-while-revalidate=604800
  2nd hit: x-cache: Hit from cloudfront, age: 46
```

CloudFront is correctly serving from the edge for 24h. After that window, the next visitor in any edge POP forces a Lambda invocation + Postgres read for the `report`, `review-stats`, `benchmarks`, and `related-analyzed` endpoints (4 invocations per game per POP per 24h).

Originally, 24h was the safe ceiling because there was no end-to-end invalidation pipeline. That's no longer true. `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py:120-143` already issues a single CloudFront invalidation covering all four API paths plus `/games/{appid}/*` whenever the analysis pipeline emits a `ReportReadyEvent`. So the only thing the 24h `s-maxage` protects against is the edge case where a developer (or a future operator script) edits the DB out-of-band and expects the page to reflect within a day. That edge case is rare, and the typical response to it ("delete the report row, kick off a fresh pipeline run") already triggers the SNS-driven invalidation when the new analysis completes.

Net effect of the change: Lambda invocations on these four endpoints drop from `~3 × 4 = 12` per popular game per day per warm POP to `~3 × 4 = 12` per popular game per *week* per warm POP. For a low-traffic game served from one POP, that's the difference between 1,460 invocations/year and 209 invocations/year, with no observable behavior change.

## Goal

After this prompt:
- `_GAME_PAGE_CACHE_CONTROL` in `src/lambda-functions/lambda_functions/api/handler.py` carries `s-maxage=604800` (7 days).
- `stale-while-revalidate` extends to 30 days so a cache-expiry visitor never blocks on a Lambda cold start; revalidation happens asynchronously in the background.
- No change to the pipeline-driven invalidation. Analyses that complete still flush all four endpoints within seconds.
- No change to HTML page caching (`s-maxage=31536000` stays; ISR + post-deploy warmer + per-game invalidation cover it).
- A short comment update so the next reader understands why 7d is safe.

## Scope

**In:**
- One-line constant change in `src/lambda-functions/lambda_functions/api/handler.py`.
- Update the comment above `_GAME_PAGE_CACHE_CONTROL` to call out the invalidation pipeline as the real freshness signal.

**Out:**
- HTML page cache headers. They already use `revalidate = 31536000` and OpenNext ISR; not touched.
- The non-game-page caches in the same file (`_NEW_RELEASES_CACHE`, `_DISCOVERY_CACHE`, `_REPORTS_CACHE`, `_HOME_INTEL_CACHE`, etc.). Different access patterns, different freshness needs, and they already have appropriate sub-day TTLs for hot listing pages.
- CloudFront cache-policy changes in `infra/stacks/delivery_stack.py`. The `api_cache_policy` `max_ttl` is already 365 days; `s-maxage` from origin is what's binding.
- The OpenNext incremental cache. Already wired correctly via `compute_stack.py:270-345`.
- Multi-POP warming. The existing `scripts/warm_game_pages.py` runs from a single machine and only warms one edge POP; broader coverage is a separate, larger prompt.
- Scheduling `scripts/warm_game_pages.py` on EventBridge. The TODO in that script's docstring is real but out of scope here; with 7d TTL it's also less urgent.
- Any change to `_get_report` / repository code.
- No commits, pushes, or deploys. Operator handles those.

## Decisions

1. **Why 7 days specifically?** It matches the existing `stale-while-revalidate` window and the OpenNext S3 cache lifecycle (7-day prefix retention noted in `compute_stack.py:304-307`). Same operational rhythm across layers. Could go longer (30d) but 7d is the round number that aligns with everything else.

2. **Why bump `stale-while-revalidate` to 30 days?** With it set equal to `s-maxage` (7d), a cache-expiry visitor blocks on a Lambda hit. With SWR=30d, that visitor sees an instant edge response and revalidation happens asynchronously. Latency floor matters more than freshness for this class of endpoint. The pipeline still issues a hard CloudFront invalidation when content actually changes.

3. **What about manual DB edits?** Acknowledged risk: if someone runs `DELETE FROM reports WHERE appid = X` and doesn't trigger the pipeline, the page can keep showing the deleted report at the edge for up to 7 days. Mitigation already exists if needed: re-run the analysis pipeline (which fires the SNS-driven invalidation), or hit the `/api/revalidate` endpoint directly with the auth token + a manual CloudFront invalidation. A future "operator manual-revalidate script" is a separate prompt if this becomes a frequent pattern.

## Changes

### 1. `src/lambda-functions/lambda_functions/api/handler.py:54-56`

Replace:

```python
# Edge-cache header for the four SSR-fanout endpoints feeding /games/{appid}/{slug}.
# CloudFront honors s-maxage; the warmer + per-game push invalidation keep it fresh.
_GAME_PAGE_CACHE_CONTROL = "s-maxage=86400, stale-while-revalidate=604800"
```

With:

```python
# Edge-cache header for the four SSR-fanout endpoints feeding /games/{appid}/{slug}.
# 7d s-maxage is safe: revalidate_frontend issues a CloudFront invalidation
# covering all four /api/games/{appid}/* paths whenever an analysis completes.
# SWR=30d so a cache expiry never blocks a visitor on a Lambda cold start.
_GAME_PAGE_CACHE_CONTROL = "s-maxage=604800, stale-while-revalidate=2592000"
```

That's the only file change.

## Files Modified

| File | Change |
|------|--------|
| `src/lambda-functions/lambda_functions/api/handler.py` | Bump `_GAME_PAGE_CACHE_CONTROL` from 24h/7d to 7d/30d; update comment |

## Verification

After deploy (operator runs the deploy):

1. Confirm the new headers are live:
   ```bash
   curl -sI 'https://d1mamturmn55fm.cloudfront.net/api/games/3265700/report' \
     | grep -iE 'cache-control|x-cache|age'
   ```
   Expect `cache-control: s-maxage=604800, stale-while-revalidate=2592000`.

2. Hit each of the four SSR-fanout endpoints twice; second hit should be `x-cache: Hit from cloudfront`:
   ```bash
   for path in report review-stats benchmarks related-analyzed; do
     for i in 1 2; do
       echo "--- $path hit $i ---"
       curl -sI "https://d1mamturmn55fm.cloudfront.net/api/games/3265700/$path" \
         | grep -iE 'x-cache|age|cache-control'
     done
   done
   ```

3. Confirm pipeline-driven invalidation still busts the new cache. Trigger a re-analysis for a game with cached endpoints, wait for the analysis-complete event, then re-curl: should be `x-cache: Miss from cloudfront, age: 0` immediately after invalidation completes.

4. CloudFront invalidation history should show the four `/api/games/{appid}/*` paths in the most-recent batch:
   ```bash
   aws cloudfront list-invalidations --distribution-id $(aws ssm get-parameter \
     --name /steampulse/production/delivery/distribution-id \
     --query 'Parameter.Value' --output text) --max-items 5
   ```

## What NOT To Do

- Do NOT lower `s-maxage` further than its current 24h. The whole point is to reduce Lambda invocations.
- Do NOT remove or shorten `stale-while-revalidate`. Removing it makes cache-expiry visitors block on a Lambda cold start.
- Do NOT touch the HTML page cache (`revalidate = 31536000` in `frontend/app/games/[appid]/[slug]/page.tsx:359`). That layer is already optimal and is invalidated by the same pipeline.
- Do NOT add a feature flag, env-var override, or per-environment branching for the TTL. Pre-launch project; just ship the new value.
- Do NOT bump the other cache constants in this file (`_NEW_RELEASES_CACHE`, `_DISCOVERY_CACHE`, etc.). Different access patterns; out of scope.
- Do NOT change the CloudFront `max_ttl` (already 365d) or `api_cache_policy` in `infra/stacks/delivery_stack.py`. The binding TTL is `s-maxage` from the origin response.
- Do NOT add unit tests for this constant change. Operator scripts and HTTP header constants don't need test coverage; per-project convention.

## Existing Code Reference

- `src/lambda-functions/lambda_functions/api/handler.py:54-56` is the constant being changed
- `src/lambda-functions/lambda_functions/api/handler.py:364, 374, 403, 516` are the four endpoints that emit this header (`/api/games/*/report`, `/review-stats`, `/benchmarks`, `/related-analyzed`)
- `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py:120-143` is the pipeline-driven CloudFront invalidation covering the same four API paths plus `/games/{appid}/*`
- `infra/stacks/delivery_stack.py:99-116` is the `api_cache_policy` (`max_ttl=365d`, no change needed)
- `infra/stacks/delivery_stack.py:198-201` is the behavior routing for the four cached API paths
- `frontend/app/games/[appid]/[slug]/page.tsx:359` is the page-level `revalidate = 31536000` (HTML layer, untouched)
- `infra/stacks/compute_stack.py:270-345` is the OpenNext ISR cache + DynamoDB tag table + revalidation Lambda (untouched)
- `scripts/warm_game_pages.py` is the post-deploy warmer (untouched; TODO to schedule it is a separate, lower-priority prompt)
