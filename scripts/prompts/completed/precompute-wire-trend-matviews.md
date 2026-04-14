# Pre-compute: wire trend methods to matviews

## Parent prompt
Broken out from `precompute-detail-and-dashboard-queries.md` (Tier 3a).
See also: `precompute-denormalize-ea-reviews.md`, `precompute-game-metrics-cache.md`.

## Context

The `mv_trend_catalog`, `mv_trend_by_genre`, and `mv_trend_by_tag` matviews already exist
(migration 0024) with all the columns these methods need. The `query_metrics()` method
(analytics_repo.py:767) already reads from them correctly for the Builder lens. But the
8 legacy `find_*_rows()` methods still run live `GROUP BY` + `JOIN` against `games` on
every request.

## What to do

Rewrite these 8 methods in `analytics_repo.py` to `SELECT` from the trend matviews
instead of computing aggregates from base tables:

| Method | Lines | Matview columns it needs |
|--------|-------|--------------------------|
| `find_release_volume_rows()` | 445-484 | `releases`, `avg_steam_pct`, `free_count` + AVG reviews (see note) |
| `find_sentiment_distribution_rows()` | 486-523 | `positive_count`, `mixed_count`, `negative_count`, `avg_steam_pct`, `avg_metacritic` |
| `find_genre_share_rows()` | 525-565 | N/A — reads `mv_trend_by_genre` already has per-genre `releases` |
| `find_velocity_distribution_rows()` | 567-616 | `velocity_under_1`, `velocity_1_10`, `velocity_10_50`, `velocity_50_plus` |
| `find_price_trend_rows()` | 618-653 | `avg_paid_price`, `free_count`, `releases` (derive `avg_price_incl_free`) |
| `find_ea_trend_rows()` | 655-695 | `ea_count`, `ea_avg_steam_pct`, `non_ea_avg_steam_pct`, `releases` |
| `find_platform_trend_rows()` | 697-734 | mac/linux/deck pct columns (counts can be derived from pct × releases) |
| `find_category_trend_rows()` | 849+ | Not in matview — see note |

### Notes

- **`find_release_volume_rows()`** needs `avg_reviews` which is not in the matview.
  Either add the column to `mv_trend_catalog` (preferred — extend the matview DDL in a
  new migration) or drop it from the response if the frontend doesn't use it.

- **`find_genre_share_rows()`** can read from `mv_trend_by_genre` — one row per
  (granularity, period, genre_slug) already has `releases`.

- **`find_category_trend_rows()`** has no matching matview (categories aren't in
  `mv_trend_by_genre`). Either: (a) add a `mv_trend_by_category` matview, or
  (b) leave this one as a live query since category trends are low-traffic.
  Decide based on query cost — if it's cheap, skip it.

- **`find_ea_trend_rows()`** currently does a full `reviews` scan via `ea_flags` CTE.
  The matview already has `ea_count`, `ea_avg_steam_pct`, `non_ea_avg_steam_pct`
  pre-computed (including the reviews scan at refresh time). This is the biggest win.

- **Filter support**: Several methods accept `genre_slug` and/or `tag_slug` filters.
  Use the same matview-routing logic as `query_metrics()`: no filter → `mv_trend_catalog`,
  genre → `mv_trend_by_genre`, tag → `mv_trend_by_tag`.

- **`game_type` filter**: The matviews are built with `g.type = 'game'` hardcoded.
  The live methods accept `game_type` param. If no caller ever passes a non-default
  value, drop the param. If they do, document the limitation.

- **`find_engagement_depth_rows()`** already reads from `index_insights` — no change needed.

## Verification

1. Start local DB + API: `./scripts/dev/start-local.sh && ./scripts/dev/run-api.sh`
2. Hit each trend endpoint and verify responses match the current output
3. `poetry run pytest tests/repositories/ -v` — ensure no repo tests break
4. Check query plans with `EXPLAIN ANALYZE` to confirm matview reads
