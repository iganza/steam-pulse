# Plan: api-cache-ttl-bump

## Context

The four `/api/games/{appid}/*` SSR-fanout endpoints (`report`, `review-stats`, `benchmarks`, `related-analyzed`) currently emit `s-maxage=86400, stale-while-revalidate=604800`. CloudFront serves them from the edge for 24h, then the next visitor in any POP forces a Lambda + Postgres hit. The 24h ceiling predates the analysis-pipeline-driven CloudFront invalidation in `revalidate_frontend/handler.py:120-143`, which already busts these exact paths whenever a `ReportReadyEvent` fires. Bumping `s-maxage` to 7d (and SWR to 30d) cuts cold-revalidation Lambda invocations on these endpoints by ~7x with no behavior change, since the freshness signal is push-based, not TTL-based.

Verified in production today (2026-04-30): `cache-control: s-maxage=86400, stale-while-revalidate=604800` and `x-cache: Hit from cloudfront` both present, confirming the cache layer behaves as intended.

## Change

Single file, single constant, plus the comment above it.

### `src/lambda-functions/lambda_functions/api/handler.py:54-56`

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

That is the only edit.

## Files Modified

| File | Change |
|------|--------|
| `src/lambda-functions/lambda_functions/api/handler.py` | Bump `_GAME_PAGE_CACHE_CONTROL` from 24h/7d to 7d/30d; refresh comment |

## Out of Scope (per prompt)

- HTML page cache headers in `frontend/app/games/[appid]/[slug]/page.tsx`.
- Other cache constants in the same file (`_NEW_RELEASES_CACHE`, `_DISCOVERY_CACHE`, `_REPORTS_CACHE`, `_HOME_INTEL_CACHE`).
- CloudFront `api_cache_policy` in `infra/stacks/delivery_stack.py` (already `max_ttl=365d`).
- OpenNext incremental cache wiring in `compute_stack.py`.
- `scripts/warm_game_pages.py` scheduling / multi-POP coverage.
- Unit tests for the constant (per `feedback_no_script_tests.md` and explicit prompt instruction).
- No commits, no pushes, no deploys (operator handles those, per `feedback_no_commit_push.md` and `feedback_no_deploy.md`).

## Verification (operator runs after deploy)

1. `curl -sI 'https://d1mamturmn55fm.cloudfront.net/api/games/3265700/report' | grep -iE 'cache-control|x-cache|age'` should report `cache-control: s-maxage=604800, stale-while-revalidate=2592000`.
2. Loop over the four endpoints (`report`, `review-stats`, `benchmarks`, `related-analyzed`) and confirm second hit returns `x-cache: Hit from cloudfront`.
3. Trigger a re-analysis for a cached game; after the analysis-complete event, re-curl should show `x-cache: Miss from cloudfront, age: 0` (pipeline invalidation still wins).
4. `aws cloudfront list-invalidations` should still show the four `/api/games/{appid}/*` paths in the most-recent batch.

## Critical References

- `src/lambda-functions/lambda_functions/api/handler.py:54-56` (the constant)
- `src/lambda-functions/lambda_functions/api/handler.py:364, 374, 403, 516` (the four endpoints emitting it)
- `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py:120-143` (push invalidation that makes the longer TTL safe)
- `infra/stacks/delivery_stack.py:99-116, 198-201` (CloudFront cache policy + behavior routing — untouched)
