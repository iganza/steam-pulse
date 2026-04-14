# Pre-compute: wire trend methods to matviews

## Parent prompt
Broken out from `precompute-detail-and-dashboard-queries.md` (Tier 3a).
See also: `precompute-denormalize-ea-reviews.md`, `precompute-game-metrics-cache.md`.

## Context

The `mv_trend_catalog`, `mv_trend_by_genre`, and `mv_trend_by_tag` matviews already existed
(migration 0024) with most columns these methods needed. The `query_metrics()` method
already read from them correctly for the Builder lens. But the 8 legacy `find_*_rows()`
methods ran live `GROUP BY` + `JOIN` against `games` on every request.

## What was done

### Migration 0045: extend trend matviews

Dropped and recreated all three matviews with:

1. **`avg_reviews`** — `ROUND(AVG(review_count), 0)` added to serve the release-volume endpoint.
2. **`avg_price_incl_free`** — `ROUND(AVG(CASE WHEN is_free THEN 0 ELSE price_usd END), 2)` added to serve the pricing endpoint (free games count as $0; paid games with unknown price are excluded).
3. **`game_type` dimension** — `'game'`, `'dlc'`, and `'all'` are pre-computed as rows via a
   `game_types` CTE cross-joined with the base data. The base CTE now includes both `game`
   and `dlc` types (`g.type IN ('game', 'dlc')`), and the `WHERE` clause
   `gt.game_type = 'all' OR b.src_type = gt.game_type` puts each row in its type-specific
   bucket AND in the `'all'` bucket. Unique indexes include `game_type` as the leading column.

### Repository: `_trend_matview_query()` shared helper

Encapsulates matview routing (no filter → `mv_trend_catalog`, genre → `mv_trend_by_genre`,
tag → `mv_trend_by_tag`) and filter validation (genre + tag combined raises `ValueError`).
Accepts `game_type` and adds `AND game_type = %s` to all queries. Empty-string slugs are
normalised to `None` so `?genre=` doesn't silently route to `mv_trend_by_genre`.

### 8 methods rewritten as `find_trend_*_rows()`

| Method | Source | Notes |
|--------|--------|-------|
| `find_trend_release_volume_rows()` | matview | `releases`, `avg_steam_pct`, `avg_reviews`, `free_count` |
| `find_trend_sentiment_distribution_rows()` | matview | Renames `releases` → `total` for service compat |
| `find_trend_genre_share_rows()` | `mv_trend_by_genre` | JOINs `genres` for display name; custom query (not via helper) |
| `find_trend_velocity_distribution_rows()` | matview | Uses `review_velocity_lifetime` with COALESCE fallback to `review_count / days_since_release` |
| `find_trend_price_trend_rows()` | matview | `avg_paid_price`, `avg_price_incl_free`, `free_count` |
| `find_trend_ea_trend_rows()` | matview | Biggest win — eliminates full `reviews` scan via `ea_flags` CTE |
| `find_trend_platform_trend_rows()` | matview | Returns pct columns directly (service reads them as-is) |
| `find_trend_category_trend_rows()` | live query | No matview — hard-coded 8-category filter, low traffic. Supports `game_type` via dynamic type clause |

All methods accept `game_type` (`'game'`, `'dlc'`, `'all'`), `genre_slug`, `tag_slug`
(where applicable), `granularity`, and `limit`.

### `query_metrics()` refactored

Now delegates to `_trend_matview_query()` instead of duplicating the routing logic.
Accepts `game_type`.

### Service + API handler

- `game_type` flows from the `type` query param through service → repo for all trend endpoints.
- Invalid `game_type` values raise `ValueError` at the repo layer → 400 at the API.
- `tag_slug` support added to all endpoints that previously only had `genre_slug`.
- `get_platform_trend()` reads pct columns directly from the matview (no count → pct conversion).

### `find_engagement_depth_rows()`

Unchanged — already reads from `index_insights`.

## Verification

1. Start local DB + API: `./scripts/dev/start-local.sh && ./scripts/dev/run-api.sh`
2. Hit each trend endpoint with `?type=game`, `?type=dlc`, `?type=all` and verify responses
3. `poetry run pytest tests/repositories/test_analytics_repo.py tests/services/test_analytics_service.py -v`
4. Check query plans with `EXPLAIN ANALYZE` to confirm matview reads
