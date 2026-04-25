# Review-fetch delta gating

## Context

Today the review crawler re-fetches reviews on a **time-based** tiered schedule:

| Tier | Threshold | Refresh window |
|---|---|---|
| S | ≥10k English reviews | 1 day |
| A | ≥1k reviews OR Early Access | 3 days |
| B | ≥50 reviews | 14 days |
| C | <50 reviews | exempt |

For most games, the time window elapses but the actual number of new reviews is tiny — we re-fetch entire review pages, write them to `reviews`, and trigger downstream work for ≤10–100 net-new reviews. Each fetch fans out across cross-region SQS, spoke Lambda, Steam API, S3 write, primary-region Lambda, DB insert. Expensive across multiple billed dimensions.

**Current volume:** 5,000–15,000 review-fetch jobs/day (`steampulse-review-crawl-production` queue).

**Key observation:** the metadata crawl (separate, hourly cadence) already fetches `review_count` and `review_count_english` from Steam and stores them on `games`. So we know each game's *current* review count cheaply and frequently — without ever calling the (expensive) review-fetch endpoint.

**Proposal:** before queuing a review-crawl job, gate on `current_review_count_english - review_count_english_at_last_review_fetch ≥ N` (default `N=1000`). Tier window stays as the *upper* bound on staleness; the delta gate adds a *minimum-change* requirement. Most games barely move within their tier window → most refetches get skipped.

## Goal

Reduce review-crawl fetches by ~70% with no product-facing change. Same data freshness in steady state; vastly fewer Lambda/SQS/S3/DB hits per game over time.

**Estimated impact:**
- ~70% fewer review-crawl SQS messages → SpokeIngestFn invocations drop proportionally → ~$15–20/mo Lambda
- 12-region spoke crawler Lambdas drop proportionally → ~$10–15/mo
- SQS request volume drops ~$3/mo
- S3 cross-region transfers from spokes drop ~$3/mo
- `reviews` table write churn drops → smaller daily RDS backup deltas (compounds today's matview-disable savings)
- Reduced Steam API hammering (good citizenship)

**Total: $30–45/mo direct AWS** + indirect backup-cost reduction + reduced API load.

## Approach

### 1. Schema — new column `app_catalog.review_count_at_last_fetch` `[code]`

New migration `src/lambda-functions/migrations/<next>_review_count_at_last_fetch.sql`:

```sql
ALTER TABLE app_catalog
  ADD COLUMN review_count_at_last_fetch INTEGER NOT NULL DEFAULT 0;

-- Backfill from current English review count so post-deploy gating doesn't
-- treat every previously-fetched game as "way overdue" on day 1.
UPDATE app_catalog ac
SET    review_count_at_last_fetch = COALESCE(g.review_count_english, 0)
FROM   games g
WHERE  ac.appid = g.appid
  AND  ac.review_crawled_at IS NOT NULL;
```

Backfilling means: at deploy time, every previously-fetched game starts at delta=0 and naturally re-crosses the threshold as new reviews accrue. Games that have never been fetched (`review_crawled_at IS NULL`) keep the default 0 and pass the "first-fetch always allowed" branch in the gate clause.

### 2. Repository changes — `src/library-layer/library_layer/repositories/catalog_repo.py` `[code]`

**`find_due_reviews()` (lines 155–215):** add a delta-gate to the existing tier CTE. The function still returns games "due per tier" — but the SQL now also requires *one of*:

1. `ac.review_crawled_at IS NULL` — never fetched; always allow (initial bootstrap)
2. `(g.review_count_english - ac.review_count_at_last_fetch) >= :min_review_delta` — enough new reviews to be worth refetching
3. `ac.review_crawled_at < NOW() - INTERVAL '30 days'` — safety net: max-staleness ceiling regardless of delta (catches review edits/deletions, vote shifts, score-label changes that don't move the count)

Use `review_count_english` (the eligibility field that drives every downstream surface), not `review_count` (all langs).

**`mark_reviews_complete_and_crawled()` (lines 256–276):** in the same UPDATE that sets `review_crawled_at = NOW()` and `reviews_completed_at = NOW()`, also set `review_count_at_last_fetch = (SELECT review_count_english FROM games WHERE appid = $1)`. Single statement — no extra round trip.

### 3. Config — `src/library-layer/library_layer/config.py` `[code]`

Add one setting (single global threshold; tier-specific can be a follow-up if data shows it's needed):

```python
REFRESH_REVIEWS_MIN_DELTA: int = 1000  # gate refetch on ≥N new English reviews since last fetch
```

Tunable via env var without redeploy.

### 4. AppCatalog model — `src/library-layer/library_layer/schema.py` `[code]`

Add the new column to the `AppCatalog` Pydantic model (currently lines 223–239) so reads/writes stay strongly typed.

### 5. Tests `[code]`

New cases in the existing `find_due_reviews` test file (likely `tests/repositories/test_catalog_repo.py`):

- delta below threshold AND tier-due → game **NOT** returned
- delta above threshold AND tier-due → returned
- `review_crawled_at IS NULL` → returned regardless of delta (initial fetch)
- `review_crawled_at < NOW() - INTERVAL '30 days'` → returned regardless of delta (30d safety)
- `mark_reviews_complete_and_crawled` correctly updates the new column

Update fixtures:
- `tests/conftest.py`: add `REFRESH_REVIEWS_MIN_DELTA` to the test env dict if `SteamPulseConfig` requires it
- `tests/test_config.py`: assert default value is `1000`

Per `feedback_test_db.md`, repository tests must hit `steampulse_test`, not the live dev DB.

## Critical files

- `src/lambda-functions/migrations/<next>_review_count_at_last_fetch.sql` — NEW
- `src/library-layer/library_layer/repositories/catalog_repo.py:155-215` — `find_due_reviews()` SQL
- `src/library-layer/library_layer/repositories/catalog_repo.py:256-276` — `mark_reviews_complete_and_crawled()`
- `src/library-layer/library_layer/config.py` — add `REFRESH_REVIEWS_MIN_DELTA`
- `src/library-layer/library_layer/schema.py:223-239` — `AppCatalog` model
- `tests/repositories/test_catalog_repo.py` — new test cases (verify exact path)
- `tests/conftest.py` + `tests/test_config.py` — env var + default

## Out of scope

- **Tier-specific thresholds** — defer until 1-week of post-deploy data shows whether a single global value over- or under-shoots for any tier. If skipping rate is uneven, revisit with `REFRESH_REVIEWS_MIN_DELTA_TIER_S/A/B`.
- **Changing the dispatcher schedule** — `RefreshReviewsRule` stays hourly @ :30. The dispatcher just feeds a (now-shorter) eligible set into the queue.
- **Touching `find_due_meta()`** — metadata refresh is the cheap call that *populates* `review_count_english`. Keep its current cadence; it's the prerequisite signal for delta gating.
- **Replacing the tier system** — the tier window remains the upper-bound staleness guarantee.

## Verification

### Local

```bash
poetry run pytest tests/repositories/test_catalog_repo.py -k "find_due_reviews or mark_reviews_complete" -v
poetry run pytest tests/  # full suite
```

### Post-deploy (24–48h later)

```bash
# Compare review-crawl queue volume before/after
aws cloudwatch get-metric-data --region us-west-2 \
  --start-time $(date -v-3d -u +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --metric-data-queries '[{"Id":"sent","MetricStat":{"Metric":{"Namespace":"AWS/SQS","MetricName":"NumberOfMessagesSent","Dimensions":[{"Name":"QueueName","Value":"steampulse-review-crawl-production"}]},"Period":86400,"Stat":"Sum"},"ReturnData":true}]'
# Expect 60–80% drop from baseline (5k–15k/day → 1k–4k/day)
```

DB-side check (run from `sp.py` / local psql):

```sql
-- Distribution of skipped vs eligible across the tier-B+ population
SELECT
    CASE
      WHEN ac.review_crawled_at IS NULL THEN 'never_fetched'
      WHEN g.review_count_english - ac.review_count_at_last_fetch >= 1000 THEN 'eligible_delta_met'
      WHEN ac.review_crawled_at < NOW() - INTERVAL '30 days' THEN 'eligible_30d_safety'
      ELSE 'skipped_delta_below'
    END AS bucket,
    COUNT(*) AS games
FROM app_catalog ac
JOIN games g USING (appid)
WHERE ac.review_count >= 50
GROUP BY 1
ORDER BY 2 DESC;
```

Target: `skipped_delta_below` ≥ 60% of eligible games. If much lower, threshold is too generous (try `MIN_DELTA=500`); if much higher, may be missing real freshness needs (try `MIN_DELTA=2000`).

Also confirm cost reduction the next morning:

```bash
aws ce get-cost-and-usage --time-period Start=$(date -v-2d +%Y-%m-%d),End=$(date -v-1d +%Y-%m-%d) \
  --granularity DAILY --metrics UnblendedCost \
  --filter '{"Dimensions":{"Key":"USAGE_TYPE","Values":["USW2-Lambda-GB-Second"]}}'
# Expect SpokeIngestFn-driven Lambda GB-sec to drop ~30-50% of total
```
