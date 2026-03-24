# SteamPulse Analytics Engine — Backend Implementation

## Goal

Add 11 new API endpoints that mine high-value insights from existing game
metadata and review data. No LLM analysis needed — pure SQL aggregation.
These features transform raw crawl data into actionable intelligence for
game developers and players.

## Codebase Orientation

### File Layout
- **Repositories**: `src/library-layer/library_layer/repositories/`
  - `base.py` — `BaseRepository` with `_fetchone()`, `_fetchall()`, `_execute()`
  - `game_repo.py` — `GameRepository`
  - `review_repo.py` — `ReviewRepository`
  - `tag_repo.py` — `TagRepository`
- **API Handler**: `src/lambda-functions/lambda_functions/api/handler.py` — FastAPI app
- **Schema**: `src/library-layer/library_layer/repositories/schema.py` — `ensure_schema()`

### Implementation Pattern

Every feature follows the same three steps:

1. **Repository method** — SQL query via `self._fetchall()` or `self._fetchone()`
   returning a dict or list of dicts. Use `%s` parameterized queries (psycopg2).
2. **API endpoint** — `@app.get("/api/...")` in handler.py, calls repository,
   returns JSON response.
3. **Indexes** — add `CREATE INDEX IF NOT EXISTS` to `ensure_schema()` in schema.py.

### Existing Pattern to Follow (review_repo.py → find_review_stats)

```python
def find_review_stats(self, appid: int) -> dict:
    timeline = self._fetchall("""
        SELECT DATE_TRUNC('week', posted_at) AS week, COUNT(*) AS total,
               COUNT(CASE WHEN voted_up THEN 1 END) AS positive,
               ROUND(COUNT(CASE WHEN voted_up THEN 1 END)::numeric / COUNT(*) * 100) AS pct_positive
        FROM reviews WHERE appid = %s AND posted_at IS NOT NULL
        GROUP BY 1 ORDER BY 1
    """, (appid,))
    # ... builds response dict, returns it
```

Handler calls it:

```python
@app.get("/api/games/{appid}/review-stats")
def get_review_stats(appid: int):
    repo = ReviewRepository(db)
    return repo.find_review_stats(appid)
```

---

## Step 1: Database Indexes

Add to `ensure_schema()` in schema.py. These are critical for query performance
on the reviews table (potentially millions of rows).

```sql
-- Audience overlap: self-join on author_steamid
CREATE INDEX IF NOT EXISTS idx_reviews_author_appid
  ON reviews(author_steamid, appid) WHERE author_steamid IS NOT NULL;

-- Playtime sentiment, EA impact, integrity queries
CREATE INDEX IF NOT EXISTS idx_reviews_appid_playtime
  ON reviews(appid, playtime_hours, voted_up);
CREATE INDEX IF NOT EXISTS idx_reviews_appid_ea
  ON reviews(appid, written_during_early_access, voted_up);
-- Top reviews sort
CREATE INDEX IF NOT EXISTS idx_reviews_appid_helpful
  ON reviews(appid, votes_helpful DESC);

-- Velocity timeline
CREATE INDEX IF NOT EXISTS idx_reviews_appid_posted
  ON reviews(appid, posted_at);

-- Developer portfolio
CREATE INDEX IF NOT EXISTS idx_games_developer_slug
  ON games(developer_slug) WHERE developer_slug IS NOT NULL;
```

---

## Step 2: New Repository — AnalyticsRepository

Create `src/library-layer/library_layer/repositories/analytics_repo.py`.
This handles cross-table queries that span games, reviews, genres, and tags.

```python
from library_layer.repositories.base import BaseRepository

class AnalyticsRepository(BaseRepository):
    """Cross-cutting analytics queries spanning multiple tables."""
```

### 2a. find_audience_overlap(appid, limit=20)

The killer feature. Finds games with the most shared reviewers via author_steamid.

**Performance note:** For games with very large reviewer sets (e.g. TF2, CS2), the
self-join is expensive. Cap `game_reviewers` to 10,000 rows — sufficient for meaningful
overlap detection and prevents runaway query times.

```sql
WITH game_reviewers AS (
    SELECT DISTINCT author_steamid
    FROM reviews
    WHERE appid = %(appid)s AND author_steamid IS NOT NULL
    LIMIT 10000
),
total AS (
    SELECT COUNT(*) AS cnt FROM game_reviewers
),
overlaps AS (
    SELECT r.appid,
           COUNT(*) AS overlap_count,
           ROUND(COUNT(CASE WHEN r.voted_up THEN 1 END)::numeric
                 / NULLIF(COUNT(*), 0) * 100, 1) AS shared_sentiment_pct
    FROM reviews r
    JOIN game_reviewers gr ON r.author_steamid = gr.author_steamid
    WHERE r.appid != %(appid)s
    GROUP BY r.appid
    ORDER BY overlap_count DESC
    LIMIT %(limit)s
)
SELECT o.appid, g.name, g.slug, g.header_image,
       g.positive_pct, g.review_count,
       o.overlap_count,
       ROUND(o.overlap_count::numeric / NULLIF(t.cnt, 0) * 100, 1) AS overlap_pct,
       o.shared_sentiment_pct
FROM overlaps o
JOIN games g ON o.appid = g.appid
CROSS JOIN total t
ORDER BY o.overlap_count DESC
```

**Response shape:**

```json
{
  "total_reviewers": 5432,
  "overlaps": [
    {
      "appid": 570,
      "name": "Dota 2",
      "slug": "dota-2-570",
      "header_image": "https://...",
      "positive_pct": 82,
      "review_count": 1800000,
      "overlap_count": 342,
      "overlap_pct": 6.3,
      "shared_sentiment_pct": 78.5
    }
  ]
}
```

`shared_sentiment_pct` = of the shared reviewers, what % gave a positive
review to the OTHER game. Shows whether your audience likes the competitor.

**Edge case:** If appid has no reviews, return `{"total_reviewers": 0, "overlaps": []}`.

### 2b. find_price_positioning(genre_slug)

Price distribution + sentiment correlation within a genre.

```sql
-- Distribution by price range
SELECT
    CASE
        WHEN g.is_free THEN 'Free'
        WHEN g.price_usd < 5 THEN 'Under $5'
        WHEN g.price_usd < 10 THEN '$5-10'
        WHEN g.price_usd < 15 THEN '$10-15'
        WHEN g.price_usd < 20 THEN '$15-20'
        WHEN g.price_usd < 30 THEN '$20-30'
        WHEN g.price_usd < 50 THEN '$30-50'
        ELSE '$50+'
    END AS price_range,
    COUNT(*) AS game_count,
    ROUND(AVG(g.positive_pct), 1) AS avg_sentiment,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY g.price_usd), 2) AS median_price
FROM games g
JOIN game_genres gg ON gg.appid = g.appid
JOIN genres gn ON gg.genre_id = gn.id
WHERE gn.slug = %(genre_slug)s
  AND g.review_count >= 10
  AND (g.price_usd IS NOT NULL OR g.is_free)
GROUP BY 1
ORDER BY MIN(COALESCE(g.price_usd, 0))
```

Also query genre-wide summary stats:

```sql
SELECT
    ROUND(AVG(g.price_usd) FILTER (WHERE NOT g.is_free), 2) AS avg_price,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY g.price_usd)
          FILTER (WHERE NOT g.is_free), 2) AS median_price,
    COUNT(*) FILTER (WHERE g.is_free) AS free_count,
    COUNT(*) FILTER (WHERE NOT g.is_free) AS paid_count
FROM games g
JOIN game_genres gg ON gg.appid = g.appid
JOIN genres gn ON gg.genre_id = gn.id
WHERE gn.slug = %(genre_slug)s AND g.review_count >= 10
```

In Python, determine `sweet_spot` = the price_range with the highest
avg_sentiment that has >= 10 games.

**Response:**

```json
{
  "genre": "Action",
  "genre_slug": "action",
  "distribution": [
    {"price_range": "Free", "game_count": 45, "avg_sentiment": 72.3, "median_price": 0},
    {"price_range": "$5-10", "game_count": 120, "avg_sentiment": 68.5, "median_price": 7.99}
  ],
  "summary": {
    "avg_price": 14.99,
    "median_price": 9.99,
    "free_count": 45,
    "paid_count": 380,
    "sweet_spot": "$10-15"
  }
}
```

### 2c. find_release_timing(genre_slug)

Monthly release density and average sentiment by month, last 5 years.

```sql
SELECT
    EXTRACT(MONTH FROM g.release_date)::int AS month,
    COUNT(*) AS releases,
    ROUND(AVG(g.positive_pct), 1) AS avg_sentiment,
    ROUND(AVG(g.review_count), 0) AS avg_reviews
FROM games g
JOIN game_genres gg ON gg.appid = g.appid
JOIN genres gn ON gg.genre_id = gn.id
WHERE gn.slug = %(genre_slug)s
  AND g.release_date IS NOT NULL
  AND g.release_date >= NOW() - INTERVAL '5 years'
  AND g.review_count >= 10
GROUP BY 1
ORDER BY 1
```

In Python, map month numbers to names. Derive `best_month` (highest
avg_sentiment), `worst_month`, `quietest_month` (fewest releases),
`busiest_month` (most releases).

**Response:**

```json
{
  "genre": "Roguelike",
  "monthly": [
    {"month": 1, "month_name": "January", "releases": 28, "avg_sentiment": 74.2, "avg_reviews": 320}
  ],
  "best_month": {"month": 2, "month_name": "February", "avg_sentiment": 78.3},
  "worst_month": {"month": 11, "month_name": "November", "avg_sentiment": 64.2},
  "quietest_month": {"month": 1, "month_name": "January", "releases": 28},
  "busiest_month": {"month": 10, "month_name": "October", "releases": 85}
}
```

### 2d. find_platform_distribution(genre_slug)

Platform support breakdown and sentiment by platform within a genre.

```sql
SELECT
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE (g.platforms->>'windows')::boolean) AS windows,
    COUNT(*) FILTER (WHERE (g.platforms->>'mac')::boolean) AS mac,
    COUNT(*) FILTER (WHERE (g.platforms->>'linux')::boolean) AS linux,
    ROUND(AVG(g.positive_pct) FILTER (WHERE (g.platforms->>'windows')::boolean), 1)
      AS windows_avg_sentiment,
    ROUND(AVG(g.positive_pct) FILTER (WHERE (g.platforms->>'mac')::boolean), 1)
      AS mac_avg_sentiment,
    ROUND(AVG(g.positive_pct) FILTER (WHERE (g.platforms->>'linux')::boolean), 1)
      AS linux_avg_sentiment
FROM games g
JOIN game_genres gg ON gg.appid = g.appid
JOIN genres gn ON gg.genre_id = gn.id
WHERE gn.slug = %(genre_slug)s
  AND g.platforms IS NOT NULL
  AND g.review_count >= 10
```

In Python, compute percentages and identify the most underserved platform
(lowest percentage above 0).

**Response:**

```json
{
  "genre": "Action",
  "total_games": 500,
  "platforms": {
    "windows": {"count": 498, "pct": 99.6, "avg_sentiment": 71.2},
    "mac": {"count": 175, "pct": 35.0, "avg_sentiment": 73.5},
    "linux": {"count": 110, "pct": 22.0, "avg_sentiment": 75.1}
  },
  "underserved": "linux"
}
```

### 2e. find_tag_trend(tag_slug)

Game count per year for a specific tag, showing growth over time.

```sql
SELECT
    EXTRACT(YEAR FROM g.release_date)::int AS year,
    COUNT(*) AS game_count,
    ROUND(AVG(g.positive_pct), 1) AS avg_sentiment
FROM games g
JOIN game_tags gt ON gt.appid = g.appid
JOIN tags t ON gt.tag_id = t.id
WHERE t.slug = %(tag_slug)s
  AND g.release_date IS NOT NULL
  AND EXTRACT(YEAR FROM g.release_date) >= 2015
GROUP BY 1
ORDER BY 1
```

In Python, compute `growth_rate` = (last_year_count - first_year_count) /
first_year_count. Guard against division by zero: if `first_year_count == 0`,
set `growth_rate` to `null`. Identify `peak_year`.

**Response:**

```json
{
  "tag": "Roguelike",
  "tag_slug": "roguelike",
  "yearly": [
    {"year": 2015, "game_count": 45, "avg_sentiment": 71.2},
    {"year": 2016, "game_count": 62, "avg_sentiment": 69.8}
  ],
  "growth_rate": 0.38,
  "peak_year": 2023,
  "total_games": 850
}
```

### 2f. find_developer_portfolio(developer_slug)

All games by a developer with aggregate stats and sentiment trajectory.

```sql
-- Per-game details
SELECT
    g.appid, g.name, g.slug, g.header_image,
    g.release_date, g.price_usd, g.is_free,
    g.review_count, g.positive_pct, g.review_score_desc,
    g.metacritic_score, g.achievements_total
FROM games g
WHERE g.developer_slug = %(dev_slug)s
ORDER BY g.release_date DESC NULLS LAST
```

```sql
-- Aggregate summary
SELECT
    COUNT(*) AS total_games,
    SUM(g.review_count) AS total_reviews,
    ROUND(AVG(g.positive_pct), 1) AS avg_sentiment,
    MIN(g.release_date) AS first_release,
    MAX(g.release_date) AS latest_release,
    ROUND(AVG(g.price_usd) FILTER (WHERE NOT g.is_free), 2) AS avg_price,
    COUNT(*) FILTER (WHERE g.is_free) AS free_games,
    COUNT(*) FILTER (WHERE g.positive_pct >= 70) AS well_received,
    COUNT(*) FILTER (WHERE g.positive_pct < 50) AS poorly_received
FROM games g
WHERE g.developer_slug = %(dev_slug)s
```

In Python, compute `sentiment_trajectory`:
- Order games by release_date
- If the last 3 games avg sentiment > overall avg by 5+: "improving"
- If below by 5+: "declining"
- Else: "stable"
- Also: if only 1 game, use "single_title"

**Response:**

```json
{
  "developer": "Valve",
  "developer_slug": "valve",
  "summary": {
    "total_games": 25,
    "total_reviews": 2500000,
    "avg_sentiment": 88.5,
    "first_release": "1998-11-08",
    "latest_release": "2023-09-27",
    "avg_price": 9.99,
    "free_games": 5,
    "well_received": 22,
    "poorly_received": 0,
    "sentiment_trajectory": "stable"
  },
  "games": [
    {
      "appid": 730, "name": "Counter-Strike 2", "slug": "counter-strike-2-730",
      "header_image": "...", "release_date": "2023-09-27",
      "price_usd": null, "is_free": true,
      "review_count": 8500000, "positive_pct": 82,
      "review_score_desc": "Very Positive",
      "metacritic_score": null, "achievements_total": 168
    }
  ]
}
```

---

## Step 3: Enhance ReviewRepository

Add these methods to `review_repo.py`.

### 3a. find_playtime_sentiment(appid)

Finer-grained playtime × sentiment with churn wall detection.

```sql
SELECT
    CASE
        WHEN playtime_hours = 0 THEN '0h'
        WHEN playtime_hours < 1 THEN '<1h'
        WHEN playtime_hours < 2 THEN '1-2h'
        WHEN playtime_hours < 5 THEN '2-5h'
        WHEN playtime_hours < 10 THEN '5-10h'
        WHEN playtime_hours < 20 THEN '10-20h'
        WHEN playtime_hours < 50 THEN '20-50h'
        WHEN playtime_hours < 100 THEN '50-100h'
        WHEN playtime_hours < 200 THEN '100-200h'
        WHEN playtime_hours < 500 THEN '200-500h'
        ELSE '500h+'
    END AS bucket,
    MIN(playtime_hours) AS bucket_min,
    COUNT(*) AS total,
    COUNT(CASE WHEN voted_up THEN 1 END) AS positive,
    COUNT(CASE WHEN NOT voted_up THEN 1 END) AS negative,
    ROUND(COUNT(CASE WHEN voted_up THEN 1 END)::numeric
          / NULLIF(COUNT(*), 0) * 100, 1) AS pct_positive
FROM reviews WHERE appid = %s
GROUP BY 1
ORDER BY MIN(playtime_hours)
```

Post-process in Python:
- Detect **churn wall**: iterate buckets, find the first bucket where
  pct_positive drops ≥ 10 points from the previous bucket (require
  both buckets to have ≥ 5 reviews to filter noise).
- Compute **median_playtime**: separate query using `PERCENTILE_CONT(0.5)`.
- Compute **value_score**: `median_playtime / price_usd` (hours per dollar).
  Include only if game has a price (not free). Get `price_usd` and `is_free`
  by JOINing `games` in the median query — no extra round-trip needed:
  ```sql
  SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r.playtime_hours) AS median_playtime,
         g.price_usd, g.is_free
  FROM reviews r JOIN games g ON g.appid = r.appid
  WHERE r.appid = %s
  GROUP BY g.price_usd, g.is_free
  ```

**Response:**

```json
{
  "buckets": [
    {"bucket": "0h", "total": 50, "positive": 20, "negative": 30, "pct_positive": 40.0},
    {"bucket": "<1h", "total": 120, "positive": 60, "negative": 60, "pct_positive": 50.0}
  ],
  "churn_point": {
    "bucket": "50-100h",
    "drop_from": 78.5,
    "drop_to": 62.1,
    "delta": -16.4
  },
  "median_playtime_hours": 12,
  "value_score": 1.2
}
```

`churn_point` is null if no significant drop detected.
`value_score` is null if game is free.

### 3b. find_early_access_impact(appid)

Compare EA-era reviews vs. post-launch reviews.

```sql
SELECT
    written_during_early_access AS is_ea,
    COUNT(*) AS total,
    COUNT(CASE WHEN voted_up THEN 1 END) AS positive,
    ROUND(COUNT(CASE WHEN voted_up THEN 1 END)::numeric
          / NULLIF(COUNT(*), 0) * 100, 1) AS pct_positive,
    ROUND(AVG(playtime_hours), 1) AS avg_playtime
FROM reviews
WHERE appid = %s
GROUP BY written_during_early_access
```

**Response:**

```json
{
  "has_ea_reviews": true,
  "early_access": {"total": 500, "positive": 360, "pct_positive": 72.0, "avg_playtime": 8.5},
  "post_launch": {"total": 1200, "positive": 1020, "pct_positive": 85.0, "avg_playtime": 24.3},
  "impact_delta": 13.0,
  "verdict": "improved"
}
```

`verdict` logic:
- `"improved"` if post_launch pct > ea pct by ≥ 5 points
- `"declined"` if post_launch pct < ea pct by ≥ 5 points
- `"stable"` otherwise
- `"no_ea"` if no EA reviews exist (return nulls for early_access)

### 3c. find_review_velocity(appid)

Monthly review volume trend over last 24 months.

```sql
SELECT
    DATE_TRUNC('month', posted_at) AS month,
    COUNT(*) AS total,
    COUNT(CASE WHEN voted_up THEN 1 END) AS positive,
    ROUND(COUNT(CASE WHEN voted_up THEN 1 END)::numeric
          / NULLIF(COUNT(*), 0) * 100, 1) AS pct_positive
FROM reviews
WHERE appid = %s AND posted_at >= NOW() - INTERVAL '24 months'
GROUP BY 1
ORDER BY 1
```

Post-process:
- `avg_monthly` = mean of all months
- `last_3_months_avg` = mean of most recent 3 months
- `trend`: "accelerating" if last_3 > avg * 1.2, "decelerating" if < avg * 0.8, else "stable"
- `peak_month`: month with highest total

**Response:**

```json
{
  "monthly": [
    {"month": "2024-01", "total": 120, "positive": 95, "pct_positive": 79.2}
  ],
  "summary": {
    "avg_monthly": 85.5,
    "last_30_days": 92,
    "last_3_months_avg": 105.3,
    "peak_month": {"month": "2023-11", "total": 450},
    "trend": "accelerating"
  }
}
```

### 3d. find_top_reviews(appid, sort='helpful', limit=10)

Top reviews by helpfulness or humor votes.

```python
def find_top_reviews(self, appid: int, sort: str = "helpful", limit: int = 10) -> list:
    # Whitelist prevents SQL injection — order_col is never user input directly.
    # The endpoint must validate sort is in ("helpful", "funny") before calling this.
    order_col = "votes_helpful" if sort == "helpful" else "votes_funny"
    return self._fetchall(f"""
        SELECT steam_review_id, voted_up, playtime_hours,
               LEFT(body, 500) AS body_preview,
               votes_helpful, votes_funny, posted_at,
               written_during_early_access, received_for_free
        FROM reviews
        WHERE appid = %s AND {order_col} > 0
        ORDER BY {order_col} DESC
        LIMIT %s
    """, (appid, limit))
```

**Response:**

```json
{
  "sort": "helpful",
  "reviews": [
    {
      "steam_review_id": "1705012345_440",
      "voted_up": true,
      "playtime_hours": 450,
      "body_preview": "This game changed how I think about...",
      "votes_helpful": 1523,
      "votes_funny": 42,
      "posted_at": "2024-01-15T12:00:00Z",
      "written_during_early_access": false,
      "received_for_free": false
    }
  ]
}
```

---

## Step 4: API Endpoints

Add all endpoints to `handler.py`. Follow the existing pattern:
get a db connection, create repository instance, call method, return result.

**404 handling:** All per-game endpoints must verify the appid exists before querying.
Use `GameRepository(db).find_by_appid(appid)` (already exists) and raise
`HTTPException(status_code=404, detail="game_not_found")` if it returns `None`.

### Per-Game Review Analytics

```python
@app.get("/api/games/{appid}/audience-overlap")
def get_audience_overlap(appid: int, limit: int = 20):
    if not GameRepository(db).find_by_appid(appid):
        raise HTTPException(status_code=404, detail="game_not_found")
    repo = AnalyticsRepository(db)
    return repo.find_audience_overlap(appid, min(limit, 50))

@app.get("/api/games/{appid}/playtime-sentiment")
def get_playtime_sentiment(appid: int):
    if not GameRepository(db).find_by_appid(appid):
        raise HTTPException(status_code=404, detail="game_not_found")
    repo = ReviewRepository(db)
    return repo.find_playtime_sentiment(appid)

@app.get("/api/games/{appid}/early-access-impact")
def get_early_access_impact(appid: int):
    if not GameRepository(db).find_by_appid(appid):
        raise HTTPException(status_code=404, detail="game_not_found")
    repo = ReviewRepository(db)
    return repo.find_early_access_impact(appid)

@app.get("/api/games/{appid}/review-velocity")
def get_review_velocity(appid: int):
    if not GameRepository(db).find_by_appid(appid):
        raise HTTPException(status_code=404, detail="game_not_found")
    repo = ReviewRepository(db)
    return repo.find_review_velocity(appid)

@app.get("/api/games/{appid}/top-reviews")
def get_top_reviews(appid: int, sort: str = "helpful", limit: int = 10):
    if not GameRepository(db).find_by_appid(appid):
        raise HTTPException(status_code=404, detail="game_not_found")
    if sort not in ("helpful", "funny"):
        sort = "helpful"
    repo = ReviewRepository(db)
    return {"sort": sort, "reviews": repo.find_top_reviews(appid, sort, min(limit, 50))}
```

### Market Analytics

```python
@app.get("/api/analytics/price-positioning")
def get_price_positioning(genre: str):
    repo = AnalyticsRepository(db)
    return repo.find_price_positioning(genre)

@app.get("/api/analytics/release-timing")
def get_release_timing(genre: str):
    repo = AnalyticsRepository(db)
    return repo.find_release_timing(genre)

@app.get("/api/analytics/platform-gaps")
def get_platform_gaps(genre: str):
    repo = AnalyticsRepository(db)
    return repo.find_platform_distribution(genre)

@app.get("/api/tags/{slug}/trend")
def get_tag_trend(slug: str):
    repo = AnalyticsRepository(db)
    return repo.find_tag_trend(slug)

@app.get("/api/developers/{slug}/analytics")
def get_developer_analytics(slug: str):
    repo = AnalyticsRepository(db)
    return repo.find_developer_portfolio(slug)
```

---

## Step 5: Testing

### Test Infrastructure (already exists — follow these patterns)

- **Database**: Tests use a real PostgreSQL test DB (connection via
  `db_conn` session-scoped fixture in `tests/conftest.py`)
- **Cleanup**: `clean_tables` autouse fixture truncates all tables before
  each test via `TRUNCATE ... RESTART IDENTITY CASCADE`
- **Repository fixtures**: `game_repo`, `review_repo`, `tag_repo`, etc.
  are created as `RepoClass(db_conn)`. Add a new fixture for AnalyticsRepository.
- **Test data helpers**: Each test file defines `_seed_game()` and
  `_make_reviews()` helpers to insert test data.

### New file: tests/repositories/test_analytics_repo.py

Add a fixture to `conftest.py`:

```python
@pytest.fixture
def analytics_repo(db_conn: Any) -> AnalyticsRepository:
    return AnalyticsRepository(db_conn)
```

Define test data helpers:

```python
def _seed_game(game_repo, appid=440, name="Test Game", developer_slug="test-dev", **kw):
    game_repo.upsert({"appid": appid, "name": name, "slug": f"test-{appid}",
                       "developer": "Test Dev", "developer_slug": developer_slug,
                       "price_usd": kw.get("price_usd", 9.99),
                       "is_free": kw.get("is_free", False),
                       "release_date": kw.get("release_date", "2023-06-15"),
                       "review_count": kw.get("review_count", 100),
                       "positive_pct": kw.get("positive_pct", 75),
                       "platforms": kw.get("platforms", {"windows": True, "mac": False, "linux": False}),
                       ...})

def _seed_genre(tag_repo, db_conn, genre_name="Action", genre_slug="action"):
    # Insert into genres table and link via game_genres
    ...

def _make_reviews(appid=440, count=5, **overrides):
    # Return list of review dicts with author_steamid, voted_up, playtime_hours, etc.
    ...
```

#### Tests for find_audience_overlap

```python
def test_audience_overlap_basic(analytics_repo, game_repo, review_repo):
    """Two games sharing reviewers shows correct overlap count and pct."""
    _seed_game(game_repo, 440, "Game A")
    _seed_game(game_repo, 570, "Game B")
    # 3 reviewers review both games
    shared = [_review(440, f"shared-{i}") for i in range(3)]
    unique = [_review(440, f"unique-{i}") for i in range(2)]
    other  = [_review(570, f"shared-{i}") for i in range(3)]  # same author_steamid
    review_repo.bulk_upsert(shared + unique + other)
    result = analytics_repo.find_audience_overlap(440, limit=10)
    assert result["total_reviewers"] == 5  # 3 shared + 2 unique
    assert len(result["overlaps"]) == 1
    assert result["overlaps"][0]["appid"] == 570
    assert result["overlaps"][0]["overlap_count"] == 3
    assert result["overlaps"][0]["overlap_pct"] == 60.0  # 3/5 * 100

def test_audience_overlap_no_reviews(analytics_repo):
    """Game with no reviews returns empty result."""
    result = analytics_repo.find_audience_overlap(999, limit=10)
    assert result["total_reviewers"] == 0
    assert result["overlaps"] == []

def test_audience_overlap_no_shared(analytics_repo, game_repo, review_repo):
    """Two games with different reviewers returns empty overlaps."""
    _seed_game(game_repo, 440)
    _seed_game(game_repo, 570)
    review_repo.bulk_upsert([_review(440, "a"), _review(570, "b")])
    result = analytics_repo.find_audience_overlap(440)
    assert result["overlaps"] == []

def test_audience_overlap_respects_limit(analytics_repo, game_repo, review_repo):
    """Limit parameter caps result count."""
    # Seed 5 games sharing 1 reviewer each, request limit=3
    ...
    result = analytics_repo.find_audience_overlap(440, limit=3)
    assert len(result["overlaps"]) == 3
```

#### Tests for find_price_positioning

```python
def test_price_positioning_buckets(analytics_repo, game_repo, tag_repo, db_conn):
    """Games at different prices land in correct buckets with sentiment."""
    _seed_genre(tag_repo, db_conn, "Action", "action")
    _seed_game(game_repo, 1, price_usd=0, is_free=True, positive_pct=70)
    _seed_game(game_repo, 2, price_usd=7.99, positive_pct=80)
    _seed_game(game_repo, 3, price_usd=14.99, positive_pct=90)
    # Link all to "action" genre
    result = analytics_repo.find_price_positioning("action")
    assert len(result["distribution"]) >= 3
    assert result["summary"]["free_count"] == 1
    assert result["summary"]["paid_count"] == 2

def test_price_positioning_empty_genre(analytics_repo):
    """Non-existent genre returns empty distribution."""
    result = analytics_repo.find_price_positioning("nonexistent")
    assert result["distribution"] == []
```

#### Tests for find_release_timing

```python
def test_release_timing_monthly(analytics_repo, game_repo, tag_repo, db_conn):
    """Games in different months produce per-month aggregates."""
    _seed_genre(...)
    _seed_game(game_repo, 1, release_date="2023-01-15", positive_pct=80)
    _seed_game(game_repo, 2, release_date="2023-06-20", positive_pct=70)
    result = analytics_repo.find_release_timing("action")
    months = {m["month"]: m for m in result["monthly"]}
    assert 1 in months  # January
    assert 6 in months  # June
    assert result["best_month"] is not None
```

#### Tests for find_platform_distribution

```python
def test_platform_distribution(analytics_repo, game_repo, tag_repo, db_conn):
    """Counts platforms correctly and identifies underserved."""
    _seed_genre(...)
    _seed_game(game_repo, 1, platforms={"windows": True, "mac": True, "linux": True})
    _seed_game(game_repo, 2, platforms={"windows": True, "mac": False, "linux": False})
    result = analytics_repo.find_platform_distribution("action")
    assert result["platforms"]["windows"]["count"] == 2
    assert result["platforms"]["mac"]["count"] == 1
    assert result["platforms"]["linux"]["count"] == 1
    assert result["underserved"] in ("mac", "linux")
```

#### Tests for find_tag_trend, find_developer_portfolio

```python
def test_tag_trend_yearly(analytics_repo, game_repo, tag_repo, db_conn):
    """Tag trend counts games per year correctly."""
    ...
    result = analytics_repo.find_tag_trend("roguelike")
    assert len(result["yearly"]) >= 2
    assert result["peak_year"] is not None

def test_developer_portfolio_summary(analytics_repo, game_repo):
    """Developer portfolio aggregates across all titles."""
    _seed_game(game_repo, 1, developer_slug="valve", positive_pct=90)
    _seed_game(game_repo, 2, developer_slug="valve", positive_pct=80)
    result = analytics_repo.find_developer_portfolio("valve")
    assert result["summary"]["total_games"] == 2
    assert result["summary"]["avg_sentiment"] == 85.0
    assert len(result["games"]) == 2

def test_developer_portfolio_empty(analytics_repo):
    """Unknown developer returns empty result."""
    result = analytics_repo.find_developer_portfolio("nonexistent")
    assert result["summary"]["total_games"] == 0
    assert result["games"] == []
```

### Enhanced: tests/repositories/test_review_repo.py

Add tests for the 5 new ReviewRepository methods. Follow the existing
pattern in this file — use `_seed_game()` and `_make_reviews()` helpers.

#### Tests for find_playtime_sentiment

```python
def test_playtime_sentiment_buckets(game_repo, review_repo):
    """Reviews at different playtimes land in correct buckets with sentiment."""
    _seed_game(game_repo)
    reviews = [
        _review(playtime_hours=0, voted_up=False),
        _review(playtime_hours=1, voted_up=True),
        _review(playtime_hours=15, voted_up=True),
        _review(playtime_hours=15, voted_up=False),
        _review(playtime_hours=100, voted_up=True),
    ]
    review_repo.bulk_upsert(reviews)
    result = review_repo.find_playtime_sentiment(440)
    assert len(result["buckets"]) >= 3
    assert result["median_playtime_hours"] is not None

def test_playtime_sentiment_churn_detection(game_repo, review_repo):
    """Detects churn wall when sentiment drops significantly between buckets."""
    _seed_game(game_repo)
    # Insert 20 positive reviews at 1-5h, then 20 mostly negative at 50-100h
    ...
    result = review_repo.find_playtime_sentiment(440)
    assert result["churn_point"] is not None
    assert result["churn_point"]["delta"] < -10

def test_playtime_sentiment_no_churn(game_repo, review_repo):
    """No churn_point when sentiment is stable across buckets."""
    _seed_game(game_repo)
    # All positive reviews at various playtimes
    ...
    result = review_repo.find_playtime_sentiment(440)
    assert result["churn_point"] is None

def test_playtime_sentiment_empty(game_repo, review_repo):
    """Game with no reviews returns empty buckets."""
    _seed_game(game_repo)
    result = review_repo.find_playtime_sentiment(440)
    assert result["buckets"] == []
```

#### Tests for find_early_access_impact

```python
def test_ea_impact_improved(game_repo, review_repo):
    """Post-launch sentiment higher than EA → verdict 'improved'."""
    _seed_game(game_repo)
    ea_reviews = [_review(voted_up=i < 3, written_during_early_access=True) for i in range(5)]
    post_reviews = [_review(voted_up=True, written_during_early_access=False) for _ in range(10)]
    review_repo.bulk_upsert(ea_reviews + post_reviews)
    result = review_repo.find_early_access_impact(440)
    assert result["has_ea_reviews"] is True
    assert result["verdict"] == "improved"
    assert result["impact_delta"] > 0

def test_ea_impact_no_ea_reviews(game_repo, review_repo):
    """Game with no EA reviews → verdict 'no_ea'."""
    _seed_game(game_repo)
    review_repo.bulk_upsert([_review(written_during_early_access=False)])
    result = review_repo.find_early_access_impact(440)
    assert result["verdict"] == "no_ea"
    assert result["early_access"] is None
```

#### Tests for find_review_integrity

```python
def test_integrity_clean(game_repo, review_repo):
    """Small bias and low free-key pct → 'clean'."""
    _seed_game(game_repo)
    paid = [_review(received_for_free=False, voted_up=True) for _ in range(100)]
    free = [_review(received_for_free=True, voted_up=True)]  # 1% free, no bias
    review_repo.bulk_upsert(paid + free)
    result = review_repo.find_review_integrity(440)
    assert result["integrity_flag"] == "clean"

def test_integrity_suspicious(game_repo, review_repo):
    """High bias delta + high free-key pct → 'suspicious'."""
    _seed_game(game_repo)
    paid = [_review(received_for_free=False, voted_up=(i < 50)) for i in range(100)]
    free = [_review(received_for_free=True, voted_up=True) for _ in range(10)]
    review_repo.bulk_upsert(paid + free)
    result = review_repo.find_review_integrity(440)
    assert result["integrity_flag"] in ("notable", "suspicious")
    assert result["bias_delta"] > 0

def test_integrity_no_free_keys(game_repo, review_repo):
    """No free-key reviews → 'insufficient_data' or 'clean'."""
    ...
```

#### Tests for find_review_velocity

```python
def test_velocity_monthly_breakdown(game_repo, review_repo):
    """Monthly totals computed correctly."""
    _seed_game(game_repo)
    # Insert reviews across 3 different months
    ...
    result = review_repo.find_review_velocity(440)
    assert len(result["monthly"]) >= 2
    assert result["summary"]["trend"] in ("accelerating", "stable", "decelerating")
    assert result["summary"]["avg_monthly"] > 0

def test_velocity_empty(game_repo, review_repo):
    """No reviews returns empty monthly and zeroed summary."""
    _seed_game(game_repo)
    result = review_repo.find_review_velocity(440)
    assert result["monthly"] == []
```

#### Tests for find_top_reviews

```python
def test_top_reviews_helpful_sort(game_repo, review_repo):
    """Returns reviews ordered by votes_helpful DESC."""
    _seed_game(game_repo)
    reviews = [
        _review(votes_helpful=100, body="Great"),
        _review(votes_helpful=5, body="OK"),
        _review(votes_helpful=50, body="Good"),
    ]
    review_repo.bulk_upsert(reviews)
    result = review_repo.find_top_reviews(440, sort="helpful", limit=3)
    assert len(result) == 3
    assert result[0]["votes_helpful"] >= result[1]["votes_helpful"]

def test_top_reviews_funny_sort(game_repo, review_repo):
    """Sort by funny returns different order."""
    _seed_game(game_repo)
    reviews = [
        _review(votes_helpful=100, votes_funny=1),
        _review(votes_helpful=5, votes_funny=500),
    ]
    review_repo.bulk_upsert(reviews)
    result = review_repo.find_top_reviews(440, sort="funny", limit=2)
    assert result[0]["votes_funny"] >= result[1]["votes_funny"]

def test_top_reviews_limit(game_repo, review_repo):
    """Limit parameter is respected."""
    _seed_game(game_repo)
    review_repo.bulk_upsert([_review(votes_helpful=i) for i in range(20)])
    result = review_repo.find_top_reviews(440, limit=5)
    assert len(result) == 5

def test_top_reviews_body_truncated(game_repo, review_repo):
    """Body is truncated to 500 chars."""
    _seed_game(game_repo)
    review_repo.bulk_upsert([_review(body="x" * 1000, votes_helpful=1)])
    result = review_repo.find_top_reviews(440, limit=1)
    assert len(result[0]["body_preview"]) == 500
```

### API Integration Tests (tests/test_api.py)

Add integration tests for each new endpoint. Use the existing pattern
in `test_api.py` — the FastAPI TestClient is used to hit endpoints
directly. Seed the database with test data, then call the endpoint and
assert the response shape.

```python
def test_audience_overlap_endpoint(client, game_repo, review_repo):
    """GET /api/games/{appid}/audience-overlap returns correct shape."""
    _seed_game(game_repo, 440)
    _seed_game(game_repo, 570)
    review_repo.bulk_upsert([...])
    response = client.get("/api/games/440/audience-overlap?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert "total_reviewers" in data
    assert "overlaps" in data

def test_price_positioning_endpoint(client, game_repo, tag_repo, db_conn):
    """GET /api/analytics/price-positioning?genre=action returns distribution."""
    ...
    response = client.get("/api/analytics/price-positioning?genre=action")
    assert response.status_code == 200
    data = response.json()
    assert "distribution" in data
    assert "summary" in data

# Repeat for all 11 endpoints — verify status 200 and response keys
```

### Run all tests

```bash
poetry run pytest tests/ -v
```

All existing tests must continue to pass. New tests should follow the
same naming conventions: `test_<feature>_<scenario>`.

---

## Notes

- **No pro gating on the backend.** All endpoints return full data.
  Pro/free gating happens in the frontend UI layer.
- **No caching for v1.** Queries run on demand. If performance becomes an
  issue, we'll add materialized views or a cache table later.
- **Return empty structures, not errors**, when a game has no reviews.
  For example, audience-overlap returns `{"total_reviewers": 0, "overlaps": []}`.
- **Use NULLIF to prevent division by zero** in all percentage calculations.
- **The `db` connection** follows the existing pattern in handler.py — check
  how other endpoints obtain it and do the same.
