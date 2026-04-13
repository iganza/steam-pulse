# Precompute Audience Overlap as a Materialized View

## Problem

`GET /api/games/{appid}/audience-overlap` runs a self-join across the `reviews` table
on every request. The query caps reviewer pools at 10k rows per game but the join still
scans the full `reviews` table for matching `author_steamid` values. In production this
exceeds the 30-second Lambda timeout and the endpoint times out for every game.

All other expensive analytics queries (price positioning, release timing, platform
distribution, tag trends, etc.) already use materialized views — audience overlap is the
only outlier. Fix: precompute it into `mv_audience_overlap` and serve from there.

## What the Matview Stores

One row per `(appid, overlap_appid)` pair — precomputed overlap counts between every
pair of games that share at least one reviewer. Only store the top 50 overlapping games
per appid (by `overlap_count DESC`) to keep the table manageable.

Schema:
```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_audience_overlap AS
WITH reviewer_sample AS (
    -- Cap at 10k reviewers per game to keep the self-join bounded
    SELECT appid, author_steamid
    FROM (
        SELECT appid, author_steamid,
               ROW_NUMBER() OVER (PARTITION BY appid ORDER BY author_steamid) AS rn
        FROM reviews
        WHERE author_steamid IS NOT NULL
    ) ranked
    WHERE rn <= 10000
),
reviewer_counts AS (
    SELECT appid, COUNT(*) AS total_reviewers
    FROM reviewer_sample
    GROUP BY appid
),
overlap_raw AS (
    SELECT a.appid,
           b.appid AS overlap_appid,
           COUNT(*) AS overlap_count,
           ROUND(COUNT(*) FILTER (WHERE r_b.voted_up)::numeric
                 / NULLIF(COUNT(*), 0) * 100, 1) AS shared_sentiment_pct
    FROM reviewer_sample a
    JOIN reviewer_sample b ON a.author_steamid = b.author_steamid AND a.appid != b.appid
    JOIN reviews r_b ON r_b.appid = b.appid AND r_b.author_steamid = a.author_steamid
    GROUP BY a.appid, b.appid
),
ranked AS (
    SELECT o.appid, o.overlap_appid, o.overlap_count, o.shared_sentiment_pct,
           rc.total_reviewers,
           ROUND(o.overlap_count::numeric / NULLIF(rc.total_reviewers, 0) * 100, 1) AS overlap_pct,
           ROW_NUMBER() OVER (PARTITION BY o.appid ORDER BY o.overlap_count DESC) AS rank
    FROM overlap_raw o
    JOIN reviewer_counts rc ON o.appid = rc.appid
)
SELECT appid, overlap_appid, overlap_count, total_reviewers, overlap_pct, shared_sentiment_pct
FROM ranked
WHERE rank <= 50;
```

Indexes:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS mv_audience_overlap_pk
    ON mv_audience_overlap(appid, overlap_appid);
CREATE INDEX IF NOT EXISTS mv_audience_overlap_appid_rank
    ON mv_audience_overlap(appid, overlap_count DESC);
```

**Note:** This matview is expensive to build (~minutes on a large reviews table). It must
use `REFRESH MATERIALIZED VIEW` (not `CONCURRENTLY`) on first build since a CONCURRENT
refresh requires a unique index to exist first. After the first build, use CONCURRENTLY.

## Files to Change

### 1. `src/library-layer/library_layer/schema.py`
Add a new migration entry (after the last existing one) with:
- `CREATE MATERIALIZED VIEW IF NOT EXISTS mv_audience_overlap AS ...` (SQL above)
- Both index CREATE statements

### 2. `src/library-layer/library_layer/repositories/matview_repo.py`
Add `"mv_audience_overlap"` to the `_MATVIEWS` list. **Order matters** — it must come
after `"mv_review_counts"` since it depends on `reviews` (not another matview), but
should be last or near-last since it's the most expensive refresh.

Also add a helper method:
```python
def get_audience_overlap(self, appid: int, limit: int = 20) -> dict:
    """Serve precomputed audience overlap from matview."""
    total_row = self._fetchone(
        "SELECT total_reviewers FROM mv_audience_overlap WHERE appid = %s LIMIT 1",
        (appid,),
    )
    total = int(total_row["total_reviewers"]) if total_row else 0
    if total == 0:
        return {"total_reviewers": 0, "overlaps": []}

    rows = self._fetchall(
        """
        SELECT o.overlap_appid AS appid, g.name, g.slug, g.header_image,
               g.positive_pct, g.review_count,
               o.overlap_count, o.overlap_pct, o.shared_sentiment_pct
        FROM mv_audience_overlap o
        JOIN games g ON o.overlap_appid = g.appid
        WHERE o.appid = %s
        ORDER BY o.overlap_count DESC
        LIMIT %s
        """,
        (appid, limit),
    )
    return {
        "total_reviewers": total,
        "overlaps": [
            {
                "appid": r["appid"],
                "name": r["name"],
                "slug": r["slug"],
                "header_image": r["header_image"],
                "positive_pct": r["positive_pct"],
                "review_count": r["review_count"],
                "overlap_count": int(r["overlap_count"]),
                "overlap_pct": float(r["overlap_pct"]),
                "shared_sentiment_pct": float(r["shared_sentiment_pct"]),
            }
            for r in rows
        ],
    }
```

### 3. `src/library-layer/library_layer/repositories/analytics_repo.py`
Remove the `find_audience_overlap` method entirely — it is replaced by the matview-backed
version in `matview_repo.py`.

### 4. `src/lambda-functions/lambda_functions/api/handler.py`
Update the `/api/games/{appid}/audience-overlap` route:
- Import `_matview_repo` (already initialized as `MatviewRepository(get_conn)`)
- Change the handler body to call `_matview_repo.get_audience_overlap(appid, ...)` instead of `_analytics_repo.find_audience_overlap(...)`

The route signature and return shape stay identical — no frontend changes needed.

### 5. `src/lambda-functions/lambda_functions/admin/matview_refresh_handler.py`
No changes needed — `refresh_all()` will automatically pick up `mv_audience_overlap`
once it's added to `_MATVIEWS` in `matview_repo.py`.

## Local Migration

After making the code changes, apply the schema migration locally:

```bash
# Apply migration (run schema changes)
poetry run python scripts/sp.py migrate

# Build the matview (first time — takes a few minutes locally)
psql "postgresql://steampulse:dev@localhost:5432/steampulse" \
  -c "REFRESH MATERIALIZED VIEW mv_audience_overlap;"

# Verify
psql "postgresql://steampulse:dev@localhost:5432/steampulse" \
  -c "SELECT COUNT(*) FROM mv_audience_overlap;" \
  -c "SELECT * FROM mv_audience_overlap WHERE appid=2358720 LIMIT 5;"
```

## Production Notes

- First-time build will be slow (~5-15 min depending on review table size). Run manually
  via tunnel after deploy: `REFRESH MATERIALIZED VIEW mv_audience_overlap;`
- Subsequent refreshes via `matview_refresh_fn` (every 6 hours) will use CONCURRENTLY
  and be much faster since only new reviews need to be reflected
- The `mv_audience_overlap` refresh should be last in the `_MATVIEWS` list since it is
  the most compute-intensive — failing it shouldn't block the others

## Tests to Update

- `tests/repositories/test_analytics_repo.py` — remove test for `find_audience_overlap`
  (method is deleted)
- Add a test in `tests/repositories/test_matview_repo.py` for `get_audience_overlap`
  covering: (1) appid with no reviews returns `{"total_reviewers": 0, "overlaps": []}`,
  (2) appid with precomputed data returns correct shape with `overlap_pct` as float
