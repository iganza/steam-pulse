# Catalog Search — Trigram Index on `games.name`

## Goal

Fix slow/unresponsive behavior of the "search games" box (`/search?q=…`) in
production by adding a `pg_trgm` GIN index on `games.name`. No code changes
to the query — the planner will pick it up automatically.

## Problem

The search box submits to `/api/games?q=…`, which routes through
`GameRepo.list_games()` in
`src/library-layer/library_layer/repositories/game_repo.py` and filters with:

```sql
g.name ILIKE %s   -- bound to '%term%'
```

The `games` table (~100k rows) has no index on `name`, so every search is a
**sequential scan**. The existing `list_games()` fast path through
`mv_genre_games` / `mv_tag_games` is deliberately skipped whenever `q` is
present (`game_repo.py:397-399`) — a matview keyed by search term is not the
right tool. An inverted index on `name` is.

Current indexes (see `0015_catalog_query_indexes.sql`) only cover genre/tag
joins and the default `review_count DESC` sort; none accelerate text search.

## Why trigram GIN, not tsvector

- Query uses `ILIKE '%term%'` (substring) + `ILIKE 'term%'` (prefix boost
  in ORDER BY). Trigram GIN accelerates both without query changes.
- `tsvector` requires a new column, trigger-maintained updates, and a
  rewritten query shape — overkill for a short name column.
- Trigram GIN is the right tool for fuzzy/substring match on short strings;
  `tsvector` shines on long documents with stemming (as used for review
  bodies in `full-text-search-reviews.md`).

## Change — New migration

**File:** `src/lambda-functions/migrations/0051_games_name_trgm_index.sql`

```sql
-- depends: 0050_create_mv_genre_synthesis
-- transactional: false

-- Accelerate catalog search (/api/games?q=…). Current query does
-- `g.name ILIKE '%term%'` on an unindexed column, forcing a seq scan
-- over ~100k rows on every search. Trigram GIN converts that to an
-- index scan and also speeds the `ILIKE 'term%'` prefix boost used
-- in ORDER BY.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_games_name_trgm
    ON games USING GIN (name gin_trgm_ops);
```

Notes:
- `CONCURRENTLY` requires `transactional: false` (matches the pattern in
  `0015_catalog_query_indexes.sql`).
- `IF NOT EXISTS` makes re-runs safe.
- `pg_trgm` is a stock Postgres extension on RDS/Aurora — no infra change.

## No application code changes

- `game_repo.py::list_games()` — unchanged. Existing `ILIKE` filter and
  ORDER BY boost will transparently use the new index.
- `handler.py` `/api/games` route — unchanged.
- `frontend/app/search/SearchClient.tsx` — unchanged.

## Verification

1. **Tests** — repo suite against `steampulse_test` (no logic changed, should
   pass unchanged):
   ```
   poetry run pytest src/library-layer/tests/
   ```

2. **Plan flip** — on a dev DB with representative row count:
   ```sql
   EXPLAIN ANALYZE
   SELECT appid, name FROM games WHERE name ILIKE '%rogue%' LIMIT 24;
   ```
   Expect `Bitmap Index Scan on idx_games_name_trgm` after the migration
   (vs. `Seq Scan on games` before). Latency should drop from hundreds of
   ms to single-digit ms.

3. **UI smoke test** — after the user applies the migration to prod:
   - `/search?q=rogue` returns quickly.
   - `/search?q=minato` still ranks exact/prefix matches above substring
     matches (ORDER BY expressions unchanged).
   - `/search` with no `q` still returns the default browse list.

## Out of scope

- No debounce/typeahead changes in `SearchClient.tsx`. The index alone
  should resolve the perceived slowness; UX polish is a separate follow-up.
- No `tsvector` / full-text search work on `games.name`.
