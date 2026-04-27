# SEO: warm and edge-cache non-analyzed game pages

## Context

We want the entire qualifying Steam catalog (~3–5k games with ≥10 reviews) indexable
by Google. Today the cold render of a non-analyzed game page is slow enough that
Googlebot will see degraded TTFB on its first crawl.

What works already:
- OpenNext ISR cache is **persistent** in S3 + DynamoDB
  (`infra/stacks/compute_stack.py:270-349`, `infra/stacks/data_stack.py:194-198`).
  Once an HTML page is rendered it lives in S3 with `revalidate = 31536000`
  (`frontend/app/games/[appid]/[slug]/page.tsx:374`).
- Sitemap covers all qualifying games (`frontend/app/sitemap.ts:50-118`,
  `MIN_REVIEWS=10`, `MAX_URLS=49000`).

What hurts cold render:
- SSR for `/games/{appid}/{slug}` issues 4 internal API calls
  (`frontend/app/games/[appid]/[slug]/page.tsx:129-206`):
  `/api/games/{appid}/report`, `/review-stats`, `/benchmarks`, `/related-analyzed`.
- CloudFront `/api/*` behavior is `CACHING_DISABLED` (`infra/stacks/delivery_stack.py`)
  → every internal SSR fetch goes Lambda → RDS, even on repeat requests within seconds.
- `find_related_analyzed_games` runs a tag-overlap CTE
  (`src/lambda-functions/lambda_functions/api/repo/report_repo.py:108-177`).
- Cold-start FrontendFn + ApiFn adds ≈1–2 s on top.
- Realistic cold TTFB: 2–5 s.

Googlebot crawls each URL once and rarely re-crawls thin pages. "Once rendered, fast
forever" doesn't help SEO unless something other than Googlebot triggers the first
render. So: pre-warm before Googlebot arrives, and shrink the cold cost.

## What to do

### 1. Edge-cache the four SSR API endpoints

Add `Cache-Control: s-maxage=86400, stale-while-revalidate=604800` to the response of
these handlers in `src/lambda-functions/lambda_functions/api/handler.py:260-344`:

- `get_game_report`
- `get_review_stats`
- `get_benchmarks`
- `get_related_analyzed_games`

In `infra/stacks/delivery_stack.py`, add CloudFront behaviors for the path patterns
`/api/games/*/report`, `/api/games/*/review-stats`, `/api/games/*/benchmarks`,
`/api/games/*/related-analyzed` that use a cache policy honoring origin
`Cache-Control` (mirror the existing `html_cache_policy` pattern). Keep
`CACHING_DISABLED` as the default for the rest of `/api/*` so writes/admin endpoints
stay uncached.

Cache invalidation: extend the existing per-game push-invalidation flow
(`cache_invalidation_queue` → `cloudfront.create_invalidation(["/games/{appid}/*"])`,
see `docs/frontend-data-flow.txt:327`) to also invalidate
`/api/games/{appid}/report`, `/review-stats`, `/benchmarks`, and `/related-analyzed`
for the same appid. Without this, fresh analyses would serve stale API data for up
to 24 h. Deploy-time `/*` invalidation in `scripts/deploy.sh:197` and
`infra/pipeline_stack.py:131` stays as-is — the warmer re-populates after.

### 2. Post-deploy cache warmer

New script: `scripts/warm_game_pages.py`. It should:

1. Page through the same `/api/games?sort=review_count&min_reviews=10&limit=1000`
   source the sitemap uses (`frontend/app/sitemap.ts:50-65`).
2. Build `https://<prod-domain>/games/{appid}/{slug}` URLs (same slug logic as the
   sitemap so we hit the canonical URL).
3. `GET` each one with bounded concurrency (5–10 workers) and a short read timeout.
4. Log success / TTFB / failure to stdout for ad-hoc runs; don't fail loudly on
   single-page errors.

Inline any sp/config helpers it needs — do not `from sp import …`
(see `feedback_sp_py_import_side_effects.md`).

Run manually after deploys initially. Once stable, wire as an EventBridge → CodeBuild
or Lambda step gated on `config.is_production` (see `feedback_no_staging_schedules.md`).

For 3–5k URLs at 5 concurrent workers and ≈3 s per cold render → ≈30 minutes for a
full warm.

### 3. Drop the deploy-time `/*` CloudFront invalidation

Remove the invalidation step from `scripts/deploy.sh:186-203` (Step 4) and
`infra/pipeline_stack.py:126-144` (`InvalidateCDN` CodeBuildStep). Most deploys are
backend-only and don't change rendered HTML — three backend pushes shouldn't nuke the
cache three times. BUILD_ID rotation already gives the ISR S3 namespace a fresh start;
per-game push invalidations cover content updates. When a frontend change does affect
rendered HTML, run `scripts/invalidate-cdn.sh` manually and re-run the warmer.

### 4. Confirm pages are indexable

While in `frontend/app/games/[appid]/[slug]/page.tsx`, verify (no edit expected):

- No `noindex` is emitted for non-analyzed games.
- Canonical points to self.
- The non-analyzed branch still SSRs Steam metadata + tags + JSON-LD `VideoGame`
  schema (already present at `page.tsx:210-317`) and a `related-analyzed` carousel.

If the non-analyzed page is too thin to be worth indexing, we'd rather know now than
after warming 5k URLs.

## What this does NOT change

- No provisioned concurrency on Lambdas (would break the fixed-cost envelope —
  see `feedback_fixed_cost_infra.md`).
- No move to build-time `generateStaticParams()` — would couple deploys to catalog
  size and lengthen builds. On-demand ISR + warmer is more flexible.

## Verification

1. Local: hit a non-analyzed game URL twice; second-hit TTFB < 200 ms.
2. API caching: `curl -I https://<prod-domain>/api/games/<appid>/report` twice;
   second response shows `x-cache: Hit from cloudfront`.
3. Run the warmer in production after a deploy; sample 20 random game URLs and
   confirm cold-cache TTFB < 500 ms.
4. Google Search Console → Crawl stats: average response time should drop and
   "Pages indexed" should trend toward the sitemap total over 2–4 weeks.
5. `curl https://<prod-domain>/sitemap.xml | grep -c '<loc>'` matches expected
   catalog count (within `MAX_URLS=49000` cap).
6. `poetry run pytest -v` (lambda-functions package) passes.
