# Pre-compute detail page and dashboard queries

## Status: PARTIALLY COMPLETE — remaining work broken out

### Completed items

- **Tier 1: `mv_price_summary`** — migration 0020, wired into `find_price_positioning()`
- **Tier 2a: `mv_audience_overlap`** — migration 0044, `MatviewRepository.get_audience_overlap()`.
  See `completed/audience-overlap-matview.md`.
- **Tier 3a (partial): trend matviews created** — migrations 0024-0025 created
  `mv_trend_catalog`, `mv_trend_by_genre`, `mv_trend_by_tag`. The `query_metrics()` Builder
  lens method reads from them. But the 8 legacy `find_*_rows()` methods were NOT rewired.

### Broken out into focused prompts (prefix: `precompute-`)

| Prompt | Covers | Priority |
|--------|--------|----------|
| `precompute-wire-trend-matviews.md` | Tier 3a: rewrite 8 trend methods to read from existing matviews | High — biggest perf win |
| `precompute-denormalize-ea-reviews.md` | Tier 3b: `has_early_access_reviews` column on games, remove reviews scan from matview DDL | High — eliminates full reviews scan |
| `precompute-game-metrics-cache.md` | Tier 2b: cache detail-page review metrics in `game_review_metrics` table | Low — detail pages are lower traffic |

---

## Original spec (for reference)

### Context

Browse pages are now fast (matviews for genre/tag listings, denormalized scores, pre-joined
game matviews). The remaining expensive queries are on detail pages and dashboards. These are
lower traffic but still hit base tables on every request.

### Tier 1: Browse page — one remaining item

#### `find_price_positioning()` summary query
- **File:** `analytics_repo.py:151-168`
- **Problem:** JOINs games→game_genres→genres for AVG/MEDIAN/COUNT on every genre browse page
- **Fix:** Add summary columns to a `mv_price_summary` matview (one row per genre)

### Tier 2: Detail pages (per-game)

#### `find_audience_overlap()` — most expensive query
- **File:** `analytics_repo.py:37-111`
- **Problem:** Self-join on 3.6M reviews via author_steamid. O(10k × 3.6M)
- **Fix:** Pre-compute during batch analysis into `game_overlap` table

#### Per-game review metrics
- **File:** `review_repo.py:85-391` — 5 methods
- `find_review_stats()` — weekly timeline + playtime buckets (2 queries)
- `find_playtime_sentiment()` — histogram + PERCENTILE_CONT (2 queries)
- `find_early_access_impact()` — GROUP BY ea flag
- `find_review_velocity()` — monthly rollup (3 queries)
- `find_top_reviews()` — indexed, acceptable
- **Fix:** Pre-compute during analysis, store in `game_metrics_cache` table (appid → JSONB)

### Tier 3: Dashboard analytics

#### Nine trend methods
- **File:** `analytics_repo.py:500-858`
- `find_release_volume_rows`, `find_sentiment_distribution_rows`, `find_genre_share_rows`,
  `find_velocity_distribution_rows`, `find_price_trend_rows`, `find_ea_trend_rows`,
  `find_platform_trend_rows`, `find_engagement_depth_rows` (already optimized),
  `find_category_trend_rows`
- **Problem:** Catalog-wide JOINs + aggregations on every request
- **Fix:** Pre-compute into trend matviews, refresh on schedule

#### `find_ea_trend_rows()` — full reviews scan
- **File:** `analytics_repo.py:710-750`
- **Problem:** CTE scans ALL 3.6M reviews to compute `BOOL_OR(written_during_early_access)`
- **Fix:** Denormalize `has_early_access_reviews` boolean onto games table

### Priority

1. Tier 1 is a quick win (one matview)
2. Tier 2 should be done when detail page performance becomes a priority
3. Tier 3 is for when the Pro analytics dashboard sees traffic
