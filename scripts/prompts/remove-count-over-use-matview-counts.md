# Remove COUNT(*) OVER() — use pre-computed counts from matviews

## Context

`COUNT(*) OVER()` in `list_games()` forces PostgreSQL to scan ALL matching rows before returning
24. For a genre like "Indie" with 50k+ games, this means a full scan of the games+reports join on
every page load — completely defeating the LIMIT. On a small RDS instance with cold cache, this
takes minutes and causes the connection stampede we're seeing in production.

The genre/tag game counts are already pre-computed in `mv_genre_counts` and `mv_tag_counts`. We
should use those instead.

## Research: why this is the correct approach

### Industry patterns — nobody computes exact counts live

- **Elasticsearch**: Since v7.0, `track_total_hits` defaults to 10,000. Beyond that, returns
  `"relation": "gte"` ("10,000+ results") rather than an exact count. Computing exact totals is
  explicitly documented as a performance anti-pattern.
- **Amazon**: Limits to 20 pages. Shows "1-48 of over 10,000 results" — always approximate.
- **Algolia**: Hard pagination limit of 1,000 hits. Counts can be inaccurate beyond that.
- **Steam Store**: Uses infinite scroll (no total count needed). When paginated, totals come from
  the pre-built catalog index, not per-query computation.
- **Google Search**: Shows "About X results" — always an estimate.

### PostgreSQL pagination best practices

- `COUNT(*) OVER()` is strictly worse than a separate `COUNT(*)` — it must scan the entire
  filtered result set before returning any row. Confirmed anti-pattern by Citus Data, CYBERTEC,
  and pganalyze.
- `pg_class.reltuples` gives instant (~0ms) table-size estimates accurate to within 1-2% when
  autovacuum is running (it is on RDS by default).
- Pre-computed counts via materialized views are the standard approach for faceted catalog browse.
- EXPLAIN-based row estimates (`EXPLAIN (FORMAT JSON)` → `Plan Rows`) can give ~20% accurate
  counts for any arbitrary query in <1ms, if we ever need "About X results" for complex filters.

### Why NOT Redis/ElastiCache

| Factor | Materialized Views | ElastiCache (t4g.micro) |
|--------|-------------------|------------------------|
| Monthly cost | $0 | ~$12/month minimum |
| Operational complexity | Zero (SQL only) | New service, VPC config, invalidation logic |
| Cache invalidation | Explicit REFRESH (simple) | Must invalidate on writes (complex, race conditions) |
| Failure modes | If Postgres is down, app is down anyway | Additional failure surface |

ElastiCache makes sense at 10k+ req/sec. At our scale (160k rows, moderate traffic), matviews
solve the same problem at zero cost and complexity.

### Keyset vs offset pagination

Keyset pagination is O(1) at any depth vs offset's O(n). But our frontend shows page numbers
(which keyset can't support), and users rarely browse past page 20 (offset 480). At 160k rows
with proper indexes, the offset penalty at page 20 is ~2-3ms. Switch to keyset only when/if
implementing infinite scroll.

## Changes

### 1. `game_repo.py` — `list_games()`

Remove `COUNT(*) OVER()`. Run only the paginated data query with LIMIT/OFFSET. Return
`{"total": None, "games": result}` — the handler provides the count from matviews.

### 2. `handler.py` — `GET /api/games` endpoint

The handler resolves total count based on the filter type:

- **Genre-only**: `matview_repo.get_genre_count(slug)` — single-row matview lookup, <1ms
- **Tag-only**: `matview_repo.get_tag_count(slug)` — single-row matview lookup, <1ms
- **Unfiltered**: `matview_repo.get_total_games_count()` — `pg_class.reltuples`, <1ms
- **Complex filters**: `total = None`, `has_more = len(games) == limit`

Uses explicit `is not None` checks for filter detection (not truthiness) to handle `year_from=0`,
`min_reviews=0` correctly. `limit`/`offset` validated via FastAPI `Query(ge=1, le=100)` /
`Query(ge=0)`.

### 3. `matview_repo.py` — count lookup methods

- `get_genre_count(slug)` — single-row SELECT from `mv_genre_counts`
- `get_tag_count(slug)` — single-row SELECT from `mv_tag_counts`
- `get_total_games_count()` — `pg_class.reltuples` with `'public.games'::regclass`, fallback to
  `pg_stat_user_tables.n_live_tup`

## API response contract

`GET /api/games` returns `total`, `has_more`, and `games`:

| Filter type | `total` | `has_more` |
|-------------|---------|------------|
| Genre-only | Pre-computed from matview (exact) | Derived from total |
| Tag-only | Pre-computed from matview (exact) | Derived from total |
| Unfiltered | Estimated from pg_class (~1-2% accurate) | Derived from total |
| Complex filters | `null` | `true` if result set == limit |

## Files

| File | Change |
|------|--------|
| `src/library-layer/library_layer/repositories/game_repo.py` | Remove COUNT(*) OVER(), return total=None |
| `src/library-layer/library_layer/repositories/matview_repo.py` | Add count lookup methods |
| `src/lambda-functions/lambda_functions/api/handler.py` | Resolve total from matviews, add has_more |
| `tests/repositories/test_game_repo.py` | Update pagination tests |
| `tests/test_api.py` | Add total/has_more API tests for all filter paths |

## Verification

1. `poetry run pytest -v` — all tests pass
2. `poetry run ruff check src/ tests/`
3. `GET /api/games?genre=indie` → `total` from matview + `has_more: true` + 24 games, instantly
4. `GET /api/games?genre=indie&sentiment=positive` → `total: null` + `has_more` + filtered games
5. `GET /api/games` (unfiltered) → `total` from pg_class estimate + `has_more: true`

## Sources

- [Faster PostgreSQL Counting — Citus Data](https://www.citusdata.com/blog/2016/10/12/count-performance/)
- [Five ways to paginate in Postgres — Citus Data](https://www.citusdata.com/blog/2016/03/30/five-ways-to-paginate/)
- [Pagination and the problem of the total result count — CYBERTEC](https://www.cybertec-postgresql.com/en/pagination-problem-total-result-count/)
- [PostgreSQL count(*) made fast — CYBERTEC](https://www.cybertec-postgresql.com/en/postgresql-count-made-fast/)
- [Count estimate — PostgreSQL wiki](https://wiki.postgresql.org/wiki/Count_estimate)
- [PostgREST Pagination and Count](https://docs.postgrest.org/en/v12/references/api/pagination_count.html)
- [Speeding up partial COUNT(*) with LIMIT — pganalyze](https://pganalyze.com/blog/5mins-postgres-limited-count)
- [Keyset Cursors, Not Offsets — Sequin](https://blog.sequinstream.com/keyset-cursors-not-offsets-for-postgres-pagination/)
- [Elasticsearch track_total_hits — Nextbrick](https://nextbrick.com/elasticsearchs-track_total_hits-for-efficient-search-results/)
