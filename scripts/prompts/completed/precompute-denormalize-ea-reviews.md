# Pre-compute: denormalize has_early_access_reviews onto games

## Parent prompt
Broken out from `precompute-detail-and-dashboard-queries.md` (Tier 3b).
See also: `precompute-wire-trend-matviews.md`, `precompute-game-metrics-cache.md`.

## Context

`find_ea_trend_rows()` in `analytics_repo.py:655-695` runs a CTE that scans ALL reviews
(`BOOL_OR(written_during_early_access) ... GROUP BY appid`) on every request. The
`mv_trend_catalog` matview (migration 0024) also embeds this same `ea_flags` CTE in its
DDL, meaning every matview refresh scans the full reviews table too.

The fix is a denormalized boolean on `games` that the write path maintains.

## What to do

### 1. Migration: add column
New migration adding `has_early_access_reviews BOOLEAN DEFAULT FALSE` to `games`.

### 2. Backfill (same migration)
```sql
UPDATE games g
SET has_early_access_reviews = TRUE
WHERE EXISTS (
    SELECT 1 FROM reviews r
    WHERE r.appid = g.appid AND r.written_during_early_access = TRUE
);
```

### 3. Write path: maintain on review ingest
In the review upsert path (`review_repo.py` or the ingest service), after inserting
reviews for a game, if any review has `written_during_early_access = TRUE`, set
`games.has_early_access_reviews = TRUE`. This is a one-way latch — once true, never
reset to false (removing an EA review doesn't un-EA the game).

### 4. Update matview DDL
Update `mv_trend_catalog` (and `mv_trend_by_genre`, `mv_trend_by_tag`) to read
`g.has_early_access_reviews` directly instead of the `ea_flags` CTE + `LEFT JOIN`.
This eliminates the full reviews scan from every matview refresh.

New migration: `DROP MATERIALIZED VIEW` + `CREATE MATERIALIZED VIEW` for all three,
with the CTE removed and `g.has_early_access_reviews` used in its place.

Update `schema.py` to mirror.

### 5. Update find_ea_trend_rows()
If `precompute-wire-trend-matviews.md` is done first, this method already reads from
the matview and needs no further change. If not, rewrite it to use
`g.has_early_access_reviews` instead of the CTE.

## Verification

1. Run migration locally: `bash scripts/dev/migrate.sh`
2. Verify backfill: `SELECT COUNT(*) FROM games WHERE has_early_access_reviews = TRUE`
   should match `SELECT COUNT(DISTINCT appid) FROM reviews WHERE written_during_early_access`
3. Refresh matviews and verify no reviews scan in `EXPLAIN ANALYZE`
4. `poetry run pytest -v`
