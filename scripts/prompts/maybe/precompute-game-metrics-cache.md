# Pre-compute: game metrics cache for detail pages

## Parent prompt
Broken out from `precompute-detail-and-dashboard-queries.md` (Tier 2b).
See also: `precompute-wire-trend-matviews.md`, `precompute-denormalize-ea-reviews.md`.

## Context

Four detail-page methods in `review_repo.py` run live aggregate queries against the
`reviews` table on every request. These are per-game queries so the row counts are
bounded by a single game's reviews, but they still involve multiple round-trips with
`GROUP BY`, `PERCENTILE_CONT`, and histogram bucketing.

## Methods to pre-compute

| Method | Lines | Queries | What it computes |
|--------|-------|---------|------------------|
| `find_review_stats()` | 85-159 | 2 | Weekly sentiment timeline + playtime buckets |
| `find_playtime_sentiment()` | 161-255 | 2 | Playtime histogram + percentile |
| `find_early_access_impact()` | 257-346 | 1 | EA-era vs post-launch sentiment split |
| `find_review_velocity()` | 348-429 | 2-3 | Monthly review volume trend (24mo) |

`find_top_reviews()` (431-465) is already indexed and acceptable — leave it as-is.

## What to do

### 1. New table: `game_review_metrics`
```sql
CREATE TABLE IF NOT EXISTS game_review_metrics (
    appid       INTEGER PRIMARY KEY REFERENCES games(appid),
    metrics     JSONB NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

The `metrics` JSONB holds the pre-computed output of all four methods, keyed by method
name (e.g. `{"review_stats": {...}, "playtime_sentiment": {...}, ...}`).

### 2. Compute path
Add a function that runs all four queries for a given appid and writes the result to
`game_review_metrics`. This should be called:
- After analysis completes (in the post-analysis event handler), OR
- During matview refresh (as a per-game computation for recently-analyzed games)

The compute function runs the same SQL as the current repo methods but writes
the result to the cache table instead of returning it.

### 3. Refactor repo methods
Each of the four methods should:
1. Read from `game_review_metrics` first
2. If cache miss (no row or stale), fall back to the live query
3. Return the same response shape as today

### 4. Cache invalidation
The cache is invalidated when new reviews are ingested for a game. The simplest
approach: the review ingest path deletes the `game_review_metrics` row for the appid,
so the next request triggers a live query + cache write. Or: re-compute eagerly after
review ingest.

## Priority
This is the lowest priority of the three precompute prompts. Detail pages are lower
traffic than dashboard/trend pages. Implement when detail page latency becomes a concern.

## Verification

1. Run migration locally
2. Compute metrics for a test game, verify JSONB content matches live query output
3. Hit detail-page API endpoints, verify responses unchanged
4. `poetry run pytest -v`
