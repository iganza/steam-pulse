# Fix genre page — two remaining slow queries

## Problem

The genre page (`/genre/[slug]/page.tsx`) makes 5 parallel API calls via `Promise.allSettled`.
The page doesn't render until ALL complete. Two are still slow (10-20s on cold cache):

1. **`getPricePositioning(slug)`** — summary query in `analytics_repo.py:151-168` still JOINs
   `games→game_genres→genres` for AVG/MEDIAN/COUNT on every request
2. **`getGames({ genre, sort: "sentiment_score", min_reviews: 200, limit: 3 })`** — hits the
   slow path because `min_reviews=200` makes it a "complex filter", bypassing the `mv_genre_games`
   matview fast path

The other 3 calls are fast (genres matview, release timing matview, platform matview).

## Fix 1: Price positioning summary → matview

Create `mv_price_summary` — one row per genre with pre-computed stats.

**Migration:**
```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_price_summary AS
SELECT
    gn.slug AS genre_slug,
    ROUND(AVG(g.price_usd) FILTER (WHERE NOT g.is_free), 2) AS avg_price,
    ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY g.price_usd)
           FILTER (WHERE NOT g.is_free))::numeric, 2) AS median_price,
    COUNT(*) FILTER (WHERE g.is_free) AS free_count,
    COUNT(*) FILTER (WHERE NOT g.is_free) AS paid_count
FROM games g
JOIN game_genres gg ON gg.appid = g.appid
JOIN genres gn ON gg.genre_id = gn.id
WHERE g.review_count >= 10
GROUP BY gn.slug;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_price_summary_pk ON mv_price_summary(genre_slug);
```

**Update `analytics_repo.py`** — replace the live summary query (lines 151-168) with:
```python
summary_row = self._fetchone(
    "SELECT avg_price, median_price, free_count, paid_count FROM mv_price_summary WHERE genre_slug = %s",
    (genre_slug,),
)
```

**Add `mv_price_summary` to `MATVIEW_NAMES`** in `matview_repo.py` for refresh.

## Fix 2: Add `last_analyzed` to genre/tag game matviews + extend fast path

The `mv_genre_games` and `mv_tag_games` matviews were created before `last_analyzed` was
denormalized onto `games`. Recreate them to include `last_analyzed` so `sort=last_analyzed`
works from the fast path.

**Drop and recreate matviews** (in migration 0020 or applied manually):
```sql
DROP MATERIALIZED VIEW IF EXISTS mv_genre_games;
DROP MATERIALIZED VIEW IF EXISTS mv_tag_games;
-- Recreate with last_analyzed column included
```

Also update migration 0019 to include `last_analyzed` in the CREATE statement.

The matviews now have all columns needed: `review_count`, `sentiment_score`, `hidden_gem_score`,
`price_usd`, `is_free`, `positive_pct`, `deck_compatibility`, `last_analyzed`.

**Update `game_repo.py` `_list_from_matview()`** — accept optional filter params:
- `min_reviews` → `WHERE review_count >= %s`
- `sentiment` → `WHERE sentiment_score >= 0.65` (etc)
- `has_analysis` → `WHERE last_analyzed IS NOT NULL`
- `price_tier` → same CASE logic but on matview columns

**Update the fast-path check in `list_games()`** — route to matview when genre/tag is set and
the only extra filters are ones the matview can handle (min_reviews, sentiment, has_analysis,
price_tier, deck_status). Only fall through to the slow path for search (`q`), developer,
year range, or genre+tag combined.

## Files

| File | Change |
|------|--------|
| `src/lambda-functions/migrations/0020_price_summary_matview.sql` | New — recreate mv_genre_games/mv_tag_games with last_analyzed + mv_price_summary |
| `src/library-layer/library_layer/repositories/analytics_repo.py` | Replace summary query with matview read |
| `src/library-layer/library_layer/repositories/matview_repo.py` | Add mv_price_summary to MATVIEW_NAMES |
| `src/library-layer/library_layer/repositories/game_repo.py` | Add last_analyzed to _list_from_matview, extend fast path for common filters |
| `src/library-layer/library_layer/schema.py` | Add mv_genre_games, mv_tag_games, mv_price_summary to MATERIALIZED_VIEWS |
| `src/lambda-functions/migrations/0019_genre_tag_game_matviews.sql` | Updated to include last_analyzed column |

## Verification

1. Create matview on production manually first (via psql tunnel)
2. Deploy code
3. Genre page (`/genre/indie`) loads in <2s
4. `poetry run pytest -v` — all tests pass
