# Pre-compute: eliminate reviews scan from trend matviews (EA flag)

## Parent prompt
Broken out from `precompute-detail-and-dashboard-queries.md` (Tier 3b).
See also: `precompute-wire-trend-matviews.md`, `precompute-game-metrics-cache.md`.

## Context

The three trend matviews (`mv_trend_catalog`, `mv_trend_by_genre`, `mv_trend_by_tag`)
embedded an `ea_flags` CTE that scanned ALL reviews
(`BOOL_OR(written_during_early_access) ... GROUP BY appid`) on every matview refresh.

## What was done (migration 0046)

Instead of adding a denormalized column + write-path latch (the original plan), we
replaced the `ea_flags` CTE with an `EXISTS` subquery on `game_genres` checking for
genre 70 (Early Access). This is simpler — no new column, no write-path changes, no
model changes — and `game_genres` is small, indexed, and already maintained by the
crawl path with delete-and-replace semantics.

The semantic difference ("is tagged Early Access" vs "has EA-era reviews") is
negligible: a game tagged EA on Steam will have EA reviews. The edge case where
genre 70 is removed but old EA reviews exist is not worth a dedicated column and
write-path maintenance.

### Changes

1. **Migration `0046_trend_matviews_ea_genre_lookup.sql`**: drop + recreate all three
   trend matviews with the `ea_flags` CTE replaced by
   `EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70)`.
2. **`schema.py`**: mirrored the same change in all three matview DDL strings.
3. **Test**: updated `test_find_trend_ea_trend_rows` to seed genre 70 instead of
   inserting a review with `written_during_early_access`.

### What did NOT change

- No new columns on `games`, no Game model changes
- No write-path changes (`review_repo.py`, `crawl_service.py`)
- `find_trend_ea_trend_rows()` reads from matviews — output columns unchanged
- API endpoints / frontend unchanged

## Verification

1. `bash scripts/dev/migrate.sh`
2. `EXPLAIN ANALYZE REFRESH MATERIALIZED VIEW mv_trend_catalog` — confirm no reviews scan
3. `poetry run pytest -v` — 556 passed
