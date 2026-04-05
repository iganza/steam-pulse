# Remove COUNT(*) OVER() — use pre-computed counts from matviews

## Context

`COUNT(*) OVER()` in `list_games()` forces PostgreSQL to scan ALL matching rows before returning 24. For a genre like "Indie" with 50k+ games, this means a full scan of the games+reports join on every page load — completely defeating the LIMIT. On a small RDS instance with cold cache, this takes minutes and causes the connection stampede we're seeing in production.

The genre/tag game counts are already pre-computed in `mv_genre_counts` and `mv_tag_counts`. We should use those instead.

## Changes

### 1. `game_repo.py` — `list_games()` (line 269-309)

**Remove `COUNT(*) OVER()`** from the SELECT. Run only the paginated data query:

```python
sql = f"""
    SELECT g.appid, g.name, g.slug, g.developer, g.header_image,
           g.review_count, g.review_count_english, g.positive_pct, g.price_usd, g.is_free,
           g.release_date, g.deck_compatibility,
           r.report_json->>'hidden_gem_score' AS hidden_gem_score,
           r.report_json->>'sentiment_score'  AS sentiment_score,
           EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = {EARLY_ACCESS_GENRE_ID}) AS is_early_access
    FROM games g
    LEFT JOIN reports r ON r.appid = g.appid
    WHERE {where}
    ORDER BY {order}
    LIMIT %s OFFSET %s
"""
```

Remove total_count extraction. Return `{"total": None, "games": result}` — the caller provides total from the matview.

### 2. `handler.py` — `GET /api/games` endpoint (line 271-304)

The handler becomes the coordinator. It reads the pre-computed count from the matview when a simple genre or tag filter is active, and passes it through:

```python
@app.get("/api/games")
async def list_games(...) -> dict:
    limit = min(limit, 100)
    result = _game_repo.list_games(...)

    # Use pre-computed count from matviews for simple filters
    if genre and not any([q, tag, developer, year_from, year_to,
                          min_reviews, has_analysis, sentiment,
                          price_tier, deck]):
        total = _matview_repo.get_genre_count(genre)
    elif tag and not any([q, genre, developer, year_from, year_to,
                          min_reviews, has_analysis, sentiment,
                          price_tier, deck]):
        total = _matview_repo.get_tag_count(tag)
    else:
        total = result["total"]  # None for complex filters

    return {"total": total, "games": result["games"]}
```

### 3. `matview_repo.py` — add single-genre/tag count lookups

Add two focused methods to avoid fetching all rows:

```python
def get_genre_count(self, genre_slug: str) -> int | None:
    row = self._fetchone(
        "SELECT game_count FROM mv_genre_counts WHERE slug = %s",
        (genre_slug,),
    )
    return int(row["game_count"]) if row else None

def get_tag_count(self, tag_slug: str) -> int | None:
    row = self._fetchone(
        "SELECT game_count FROM mv_tag_counts WHERE slug = %s",
        (tag_slug,),
    )
    return int(row["game_count"]) if row else None
```

### 4. Update pagination tests

Update `test_list_games_total_matches_result_count`, `test_list_games_offset_beyond_results`, `test_list_games_no_results_offset_zero` — total is now `None` from `list_games()` since the repo no longer computes it.

## Files

| File | Change |
|------|--------|
| `src/library-layer/library_layer/repositories/game_repo.py` | Remove COUNT(*) OVER() and fallback COUNT from `list_games()` |
| `src/library-layer/library_layer/repositories/matview_repo.py` | Add `get_genre_count()` and `get_tag_count()` |
| `src/lambda-functions/lambda_functions/api/handler.py` | Coordinate: call matview for count, game_repo for data |
| `tests/repositories/test_game_repo.py` | Update 3 pagination tests |
| `tests/test_api.py` | Add `get_genre_count`/`get_tag_count` to `_MemMatviewRepo` |

## API response contract

`GET /api/games` now returns `total`, `has_more`, and `games`:

- **Genre-only / tag-only**: `total` = pre-computed count from matview (exact), `has_more` derived from total
- **Unfiltered browse**: `total` = estimated count from `pg_class.reltuples` (instant), `has_more` derived from total
- **Complex filters**: `total` = `null` (exact count unknown), `has_more` = `true` if result set equals limit (more pages likely exist)

## Verification

1. `poetry run pytest -v` — all tests pass
2. `poetry run ruff check src/ tests/`
3. Test locally: `GET /api/games?genre=indie` returns `total` from matview + `has_more` + 24 games instantly
4. `GET /api/games?genre=indie&sentiment=positive` returns `total: null` + `has_more: true/false` + filtered games
