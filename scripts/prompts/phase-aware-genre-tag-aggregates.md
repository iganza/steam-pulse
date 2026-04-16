# Phase-aware genre/tag sentiment aggregates

## Context

The cross-game sentiment aggregates that drive genre/tag trend listings currently
read `games.positive_pct` (Steam's English all-time value):

- `mv_trend_catalog` — cross-catalog trend (migration 0046)
- `mv_trend_by_genre` — genre-scoped trend (migration 0046, extended 0045)
- `mv_trend_by_tag` — tag-scoped trend (migration 0046, extended 0045)
- `mv_discovery_feeds` — homepage discovery (migration 0047)
- `mv_genre_counts` / `mv_tag_counts` — sentiment-aware facet counts

For games that transitioned out of Early Access, `positive_pct` conflates EA-era and
post-release sentiment. In a genre rollup — say "Roguelike Deckbuilder" — a post-EA
game with 10,000 EA reviews (90% positive) and 50 post-release reviews (60% positive)
contributes 90% to the genre average, masking the post-release reception that newer
buyers actually see.

Once `split-ea-post-release-reviews.md` lands, each post-EA game has
`positive_pct_post_release` (English post-release only). This prompt teaches the
aggregate matviews to prefer that value when available.

## Scope

Change the aggregation expression in the five listed matviews from
`g.positive_pct` to:

```sql
COALESCE(g.positive_pct_post_release, g.positive_pct)
```

Same substitution for any expression that multiplies or averages on `positive_pct`
inside these matviews. Review counts follow the same rule:

```sql
COALESCE(g.review_count_post_release, g.review_count_english, g.review_count)
```

For games that never had EA (`has_early_access_reviews = FALSE` and therefore
`positive_pct_post_release IS NULL`), the COALESCE falls through to today's value —
no behavioural change for those games.

No new matviews created. Existing read paths (repositories, API, frontend) don't
change — they consume the same matview columns, which now reflect the corrected
value.

## Approach

### 1. Matview rebuild migration

Single migration `00NN_phase_aware_trend_matviews.sql` that rebuilds all five
matviews following the drop-before-create pattern. For each:

```sql
DROP MATERIALIZED VIEW IF EXISTS mv_trend_catalog;

CREATE MATERIALIZED VIEW mv_trend_catalog AS
SELECT
    ...,
    -- Phase-aware: prefer post-release English sentiment when available; fall back
    -- to Steam's English all-time otherwise. Non-EA games and games without a
    -- post-release split stay on the all-time value.
    AVG(COALESCE(g.positive_pct_post_release, g.positive_pct)) AS avg_positive_pct,
    SUM(COALESCE(g.review_count_post_release, g.review_count_english, g.review_count)) AS total_reviews,
    ...
FROM games g
WHERE ...;

CREATE UNIQUE INDEX mv_trend_catalog_pk_idx ON mv_trend_catalog(...);
-- plus any partial / GIN indexes that previously existed — copy them verbatim.
```

**Mandatory** per CLAUDE.md matview rules:
- `DROP ... IF EXISTS` first (self-heals persistent dev/staging DBs).
- Re-create every index, **especially the unique index** required for
  `REFRESH MATERIALIZED VIEW CONCURRENTLY`. Missing it = blocking refresh = outage.
- Re-create any GIN indexes on `text[]` filter columns (e.g.
  `mv_new_releases_genre_slugs_gin` pattern).

### 2. Schema mirror

Append the rebuild DDL to `src/library-layer/library_layer/schema.py`
`MATERIALIZED_VIEWS`, and add the five matview names to the drop-before-rebuild list
in `create_matviews()` so test DBs pick up future shape changes automatically.

### 3. Refresh cadence — no change

`MATVIEW_NAMES` in `src/library-layer/library_layer/repositories/matview_repo.py`
already includes these five. The existing refresh Lambda
(`admin/matview_refresh_handler.py`) picks up the new projection automatically:
- SQS-triggered on `report-ready` / `catalog-refresh-complete` (5-min debounce).
- EventBridge every 6h as fallback.

Do not add new triggers.

### 4. Cache headers

API endpoints reading these matviews already return `Cache-Control` with
`s-maxage=300, stale-while-revalidate=600` (or tighter). No change.

### 5. Tests

- `tests/repositories/test_matview_repo.py` — seed two games in the same genre:
  one post-EA with `positive_pct=90`, `positive_pct_post_release=60`,
  `has_early_access_reviews=TRUE`; one non-EA with `positive_pct=80`,
  `positive_pct_post_release=NULL`. Refresh the matviews. Assert
  `avg_positive_pct = (60 + 80) / 2 = 70`, confirming the COALESCE resolved as
  expected.
- Analogous test for `mv_discovery_feeds` and the `_counts` matviews.
- `tests/infra/test_compute_stack.py` — no change (refresh rule unchanged).

## Files to modify / create

- `src/lambda-functions/migrations/00NN_phase_aware_trend_matviews.sql` — rebuild
  all five matviews with the `COALESCE` expression (and re-create every index).
- `src/library-layer/library_layer/schema.py` — mirror the DDL + add names to the
  drop-before-rebuild list.
- `tests/repositories/test_matview_repo.py` — phase-aware aggregate case.
- Smoke tests — no change expected (shape identical).

## Out of scope

- Changes to the matview read path (repositories, API, frontend). The column names
  stay the same; callers consume corrected values transparently.
- Refresh-cadence or triggering changes.
- Per-game endpoints (`review-stats`, `review-velocity`, etc.) — handled in
  `ea-aware-timeline-endpoints.md`.
- Synthesis / narrative changes — handled in `analyzer-ea-awareness.md`.

## Verification

- Local: `bash scripts/dev/migrate.sh` → `psql -c '\d mv_trend_by_genre'` shows
  same column list. `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_trend_by_genre;`
  succeeds (proves unique index preserved).
- `poetry run pytest tests/repositories/test_matview_repo.py -v` — phase-aware case
  passes.
- Staging: after migration, compare `avg_positive_pct` for a genre with known
  post-EA games before/after; the delta should align with the post-release
  sentiment of the affected games.
- Frontend: homepage listings and genre trend pages render unchanged in structure;
  values shift for genres rich in EA-transition games.

## Dependencies

- `split-ea-post-release-reviews.md` must ship first — the `_post_release` columns
  referenced by the COALESCE expression are introduced there.
- Ideally lands **after** `post-ea-accelerated-review-recrawl.md` so most
  recently-released post-EA games already have `positive_pct_post_release`
  populated. Not a hard dependency — the COALESCE handles NULL gracefully.
