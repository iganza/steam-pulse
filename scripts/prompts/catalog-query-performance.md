# Plan: Catalog Query Performance Optimization

## Context

Production RDS is showing 20+ active connections with 2-3 minute BufferIO waits on catalog browse queries. Root causes:

1. **Missing indexes** on junction tables (`game_genres`, `game_tags`) and lookup columns (`genres.slug`, `tags.slug`) — every `EXISTS` subquery in `list_games()` does sequential scans
2. **Double-query pattern** — `list_games()` runs COUNT + data query separately (two round-trips with identical expensive WHERE)
3. **No caching** — genre counts, tag counts, and analytics aggregates are computed from scratch on every request, including sidebar data that hits on every page load

## Phase 1: Missing Indexes (migration)

**New file:** `src/lambda-functions/migrations/0015_catalog_query_indexes.sql`

```sql
-- depends: 0014_add_tag_category
-- transactional: false

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_game_genres_genre_appid ON game_genres(genre_id, appid);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_game_tags_tag_appid ON game_tags(tag_id, appid);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_genres_slug ON genres(slug);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tags_slug ON tags(slug);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_games_review_count ON games(review_count DESC NULLS LAST);
```

- Composite `(genre_id, appid)` and `(tag_id, appid)` enable index-only scans for the EXISTS subqueries
- `genres(slug)` and `tags(slug)` speed up the JOIN inside EXISTS
- `games(review_count DESC)` covers the default sort order

**Also update:** `src/library-layer/library_layer/schema.py` — add 5 indexes to the `INDEXES` tuple (lines 245-253)

## Phase 2: Query Optimization

**Modify:** `src/library-layer/library_layer/repositories/game_repo.py` — `list_games()` (lines 268-300)

Replace the separate COUNT query + data query with a single query using `COUNT(*) OVER()`:

- Remove lines 268-276 (count query)
- Add `COUNT(*) OVER() AS total_count` to the SELECT list in the data query
- Extract `total` from the first row, strip `total_count` from result dicts
- Fallback: when `offset > 0` and rows are empty (paged past results), run a standalone COUNT to still return total for the paginator

This saves one DB round-trip per `/api/games` request.

## Phase 3: Materialized Views + Refresh Lambda

### 3a. Migration for materialized views

**New file:** `src/lambda-functions/migrations/0016_materialized_views.sql`

Six materialized views, each with a unique index for `REFRESH CONCURRENTLY`:

| View | Replaces | Unique Key |
|------|----------|------------|
| `mv_genre_counts` | `list_genres()` live GROUP BY | `id` |
| `mv_tag_counts` | `list_tags()` / `list_tags_grouped()` live GROUP BY | `id` |
| `mv_price_positioning` | `find_price_positioning()` live aggregate | `(genre_slug, price_range)` |
| `mv_release_timing` | `find_release_timing()` live aggregate | `(genre_slug, month)` |
| `mv_platform_distribution` | `find_platform_distribution()` live aggregate | `genre_slug` |
| `mv_tag_trend` | `find_tag_trend()` live aggregate | `(tag_slug, year)` |

Plus a refresh tracking table:
```sql
CREATE TABLE IF NOT EXISTS matview_refresh_log (
    id SERIAL PRIMARY KEY,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    duration_ms INTEGER,
    views_refreshed TEXT[]
);
```

### 3b. New repository for matview access

**New file:** `src/library-layer/library_layer/repositories/matview_repo.py`

- `MatviewRepository` with read methods for each matview (simple SELECTs, no aggregation)
- `refresh_all()` — runs `REFRESH MATERIALIZED VIEW CONCURRENTLY` for each view (requires autocommit)
- `get_last_refresh_time()` — reads `matview_refresh_log` for debounce checks
- `log_refresh()` — inserts into `matview_refresh_log`

### 3c. Wire matview reads into API endpoints

**Modify:** `src/lambda-functions/lambda_functions/api/handler.py`

- Add `_matview_repo = MatviewRepository(_conn)` at module level
- Route these endpoints to matview_repo instead of game_repo/analytics_repo:
  - `GET /api/genres` → `_matview_repo.list_genre_counts()`
  - `GET /api/tags/top` → `_matview_repo.list_tag_counts()`
  - `GET /api/tags/grouped` → `_matview_repo.list_tags_grouped()`

**Modify:** `src/library-layer/library_layer/repositories/analytics_repo.py`

- `find_price_positioning()` (line 103) → read from `mv_price_positioning`, compute summary in Python
- `find_release_timing()` (line 194) → read from `mv_release_timing`, compute best/worst/busiest in Python
- `find_platform_distribution()` (line 269) → read from `mv_platform_distribution`
- `find_tag_trend()` (line 339) → read from `mv_tag_trend`

These methods keep their existing return shape — only the SQL source changes from live tables to matviews. The Python post-processing logic (sweet_spot calculation, month name mapping, platform gap detection) stays in the repo methods.

### 3d. Refresh Lambda

**New file:** `src/lambda-functions/lambda_functions/admin/matview_refresh_handler.py`

- Triggered by SQS messages from `cache_invalidation_queue` (already exists, already receives `report-ready` from content-events topic, **has no consumer yet**)
- Also triggered by EventBridge schedule (every 6h fallback)
- Debounce: skip refresh if last refresh was < 5 minutes ago
- `reserved_concurrent_executions=1` prevents parallel refreshes
- Logs duration and results

### 3e. CDK changes

**Modify:** `infra/stacks/compute_stack.py`
- Add `MatviewRefreshFn` Lambda (same VPC/SG/layer as other admin Lambdas)
- Add SQS event source from `cache_invalidation_queue`
- Add EventBridge schedule rule (every 6h)
- Set `reserved_concurrent_executions=1`

**Modify:** `infra/stacks/messaging_stack.py`
- Add SNS subscription: `system_events_topic` → `cache_invalidation_queue` filtered on `catalog-refresh-complete`
- (The `content-events` → `cache_invalidation_queue` filtered on `report-ready` already exists at line 208)

### 3f. Schema reference update

**Modify:** `src/library-layer/library_layer/schema.py`
- Add `MATERIALIZED_VIEWS` tuple with the matview DDL + unique indexes
- Add `create_matviews(conn)` function for test suite
- Add `matview_refresh_log` table to TABLES

## Files Changed Summary

| File | Change |
|------|--------|
| `src/lambda-functions/migrations/0015_catalog_query_indexes.sql` | **New** — 5 indexes |
| `src/lambda-functions/migrations/0016_materialized_views.sql` | **New** — 6 matviews + unique indexes + refresh log table |
| `src/library-layer/library_layer/repositories/game_repo.py` | `list_games()` → COUNT(*) OVER() |
| `src/library-layer/library_layer/repositories/matview_repo.py` | **New** — matview reads + refresh logic |
| `src/library-layer/library_layer/repositories/analytics_repo.py` | 4 methods → read from matviews |
| `src/library-layer/library_layer/schema.py` | Add indexes to INDEXES, add MATERIALIZED_VIEWS, add refresh log table |
| `src/lambda-functions/lambda_functions/api/handler.py` | Wire `_matview_repo`, route genre/tag endpoints |
| `src/lambda-functions/lambda_functions/admin/matview_refresh_handler.py` | **New** — refresh Lambda |
| `infra/stacks/compute_stack.py` | Add MatviewRefreshFn + EventBridge schedule |
| `infra/stacks/messaging_stack.py` | Add system-events → cache_invalidation_queue subscription |

## Verification

1. **Phase 1 — Indexes:** Run migration locally (`bash scripts/dev/migrate.sh`), then `EXPLAIN ANALYZE` on the catalog query with a genre filter to confirm index usage
2. **Phase 2 — Window function:** Run `poetry run pytest tests/repositories/` to verify list_games returns correct shape, then test API locally (`./scripts/dev/run-api.sh`) and confirm `/api/games?genre=indie` returns correct total
3. **Phase 3 — Matviews:** Run migration locally, verify matviews are populated (`SELECT COUNT(*) FROM mv_genre_counts`), test refresh with `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_genre_counts`, verify API endpoints return same data as before
4. **Full stack:** `poetry run pytest -v` + `poetry run ruff check .` + `poetry run ruff format .`
