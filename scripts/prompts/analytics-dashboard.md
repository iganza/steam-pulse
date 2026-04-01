# Analytics — Catalog-Wide Interactive Analytics

## Background

SteamPulse currently offers per-game analytics (sentiment, velocity, playtime,
EA impact) and genre-scoped summaries (price positioning, release timing,
platform gaps). What's missing is a **catalog-wide analytics hub** — interactive
charts that let users explore patterns across the entire Steam catalog over time.

The goal: a dedicated `/analytics` page where users can see how Steam's catalog is
evolving — release volume, genre shifts, sentiment patterns, review velocity
distributions, platform ecosystem trends, player engagement depth, and feature
adoption — across configurable time windows with drill-down by genre, tag,
and price tier.

**This is the first section of the Analytics hub.** Future analytics surfaces
(developer portfolio comparisons, platform gap analysis, price positioning
explorer, tag momentum) belong here too. The page should be designed as a
container that can grow, not a one-off chart dump.

---

## Free vs Pro access model

All 9 charts are visible to every user. Free users see each chart rendered with
sensible defaults — they can hover and read tooltips. The **control bar**
(granularity toggle + genre filter) and certain per-chart extras are Pro-only.

### Tiering table

| Chart                  | Free defaults                                        | Pro extras                                                            |
|------------------------|------------------------------------------------------|-----------------------------------------------------------------------|
| Release Volume         | Monthly, all genres, bar + MA trend line             | Granularity toggle, genre/tag filter, type filter (in card header)    |
| Sentiment Distribution | Monthly, all genres, stacked % area                  | Granularity toggle, genre filter, toggle %/raw, Metacritic overlay    |
| Genre Share            | Yearly, top 5 genres                                 | Granularity toggle (quarter/year), choose top N genres (card header)  |
| Review Velocity        | Monthly, all genres, stacked bars                    | Granularity toggle, genre filter                                      |
| Pricing Trends         | Quarterly, free % bar + avg price line               | Granularity toggle, genre filter                                      |
| Early Access           | Quarterly, EA % bar                                  | Granularity toggle, EA count bar + EA/non-EA sentiment lines          |
| Platform & Deck        | Quarterly, Mac/Linux + Deck Verified % lines         | Granularity toggle, genre filter, full Deck breakdown (Play/Unsup)    |
| Engagement Depth       | Yearly, all genres, playtime band areas              | Granularity toggle, genre filter                                      |
| Feature Adoption       | Yearly, top 4 categories                             | Granularity toggle, all 8 categories                                  |

### Implementation pattern

**Prerequisite:** `pro-gating-context.md` must be implemented first. It creates
`frontend/lib/pro.tsx` with `usePro()` and mounts `ProProvider` at the app root.

In `AnalyticsClient.tsx`, consume pro status from context:

```typescript
import { usePro } from "@/lib/pro";

// Inside the component:
const isPro = usePro();
```

Pass `isPro` down as a prop to chart sections that have pro extras (same pattern
as `GameReportClient.tsx` passes it to `PlaytimeChart` and `CompetitiveBenchmark`).

**Note on `AnalyticsClient.tsx` naming:** `AnalyticsClient` is the top-level client
component for the `/analytics` page — it is distinct from the existing
`AnalyticsRepository` and the new `AnalyticsService`. The suffix `Client` (Next.js
convention) disambiguates it.

**Pro-gating the control bar:** Wrap the control bar in a `relative` container.
When `!isPro`, apply `blur-sm pointer-events-none select-none` to the controls
and render an absolute-positioned overlay:

```tsx
<div className="relative">
  <div className={isPro ? "" : "blur-sm pointer-events-none select-none"}>
    <GranularityToggle ... />
    <GenreFilter ... />
  </div>
  {!isPro && (
    <div className="absolute inset-0 flex items-center justify-center">
      <Link href="/pro" className="...">Customize with Pro →</Link>
    </div>
  )}
</div>
```

**Per-chart pro extras:** Each chart section conditionally renders its advanced
controls (e.g. the "Show as %" toggle on Sentiment, the sentiment overlay lines
on Early Access) when `isPro`. Free users see only the default view with no
toggle controls visible.

**Note:** The `PRO_ENABLED` env var on the backend gates `/api/chat` (the V2 NL
query feature) — it is unrelated to the trends dashboard. No backend changes are
needed to enable Pro features here; the gate is purely frontend.

---

## What users should be able to explore

### Release volume over time
- How many games released per week / month / quarter / year?
- Broken down by genre, tag, or price tier
- Trend line: is Steam getting more or fewer releases over time?

### Sentiment distribution over time
- Average sentiment of games released in each period
- Sentiment histogram: what % of games are Positive vs Mixed vs Negative per period?
- Are games getting better or worse reviewed over time?

### Review velocity patterns
- Average review velocity (reviews/day) of games by release cohort
- Which release periods produce the most-reviewed games?
- Velocity distribution: how many games get <1, 1–10, 10–50, 50+ reviews/day?

### Genre & tag evolution
- Genre share over time: what % of releases are in each genre per period?
- Rising genres: which genres are growing fastest in release volume?
- Tag momentum: which tags are trending up or down year-over-year?

### Price trends
- Average price by release period
- Free-to-play share over time
- Price vs sentiment correlation by period

### Early Access patterns
- What fraction of releases go through Early Access per period?
- EA sentiment improvement rate over time

### Platform ecosystem evolution
- What % of releases support Mac? Linux? Is it growing or shrinking?
- What % of releases are Steam Deck Verified vs Playable vs Unsupported?
- Is Deck verification becoming table stakes? (Verified games get Deck storefront placement)
- How does platform support vary by genre? (e.g., Linux support in indie vs AAA)

### Player engagement depth
- How long do reviewers play before writing reviews, by release cohort?
- What % of reviews come from the sub-2h refund window? Is it getting worse?
- How does engagement depth differ by genre? (Action: shorter, RPG: longer)
- Are games getting longer or shorter over time?

### Feature investment signals
- What % of releases include Multiplayer? Co-op? Workshop? VR? Controller support?
- Which features are becoming expected in each genre?
- Is VR support growing or plateauing?
- Is modding (Workshop) adoption accelerating?

---

## What already exists (reuse — do NOT rebuild)

### Backend

| Method / Endpoint                                        | File                    | What it provides                                                                                                                         |
|----------------------------------------------------------|-------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| `AnalyticsRepository.find_release_timing(genre_slug)`    | `analytics_repo.py:173` | Monthly release density by month-of-year (Jan–Dec), last 5 years, single genre. Aggregates by calendar month, NOT by actual time period. |
| `AnalyticsRepository.find_tag_trend(tag_slug)`           | `analytics_repo.py`     | Yearly game count + avg sentiment for a single tag (2015+)                                                                               |
| `AnalyticsRepository.find_price_positioning(genre_slug)` | `analytics_repo.py`     | Price distribution + sentiment by price range, single genre snapshot                                                                     |
| `GameRepository.list_games(...)`                         | `game_repo.py`          | Full filtering: genre, tag, year_from/to, sentiment, price_tier, min_reviews, sort, pagination                                           |
| `ReviewRepository.find_review_velocity(appid)`           | `review_repo.py:325`    | Per-game monthly velocity + trend (24 months)                                                                                            |
| `GET /api/analytics/release-timing?genre=`               | `api/handler.py`        | Exposes `find_release_timing`                                                                                                            |
| `GET /api/tags/{slug}/trend`                             | `api/handler.py`        | Exposes `find_tag_trend`                                                                                                                 |
| `GET /api/analytics/price-positioning?genre=`            | `api/handler.py`        | Exposes `find_price_positioning`                                                                                                         |

**Key gap:** Existing analytics are either per-game or single-genre snapshots.
None provide catalog-wide time-series with configurable granularity and
cross-genre comparison.

### Frontend

| Component                   | File               | What it provides                                                                   |
|-----------------------------|--------------------|------------------------------------------------------------------------------------|
| Recharts (`recharts@3.8.0`) | `package.json`     | Only charting library — area charts used in `SentimentTimeline.tsx`                |
| `SentimentTimeline.tsx`     | `components/game/` | Recharts `AreaChart` for weekly sentiment — pattern to follow                      |
| `SearchClient.tsx`          | `app/search/`      | Filter UI with genre/tag/year/sentiment/price dropdowns — reusable filter patterns |
| `GameCard.tsx`              | `components/game/` | Reusable game tile for drill-down results                                          |
| Tailwind + shadcn/ui        | `components/ui/`   | Card, Badge, Button primitives                                                     |
| Motion (`motion@12.36.0`)   | `package.json`     | Animation library for transitions                                                  |

**Charting note:** Recharts is the only charting library. All new charts should
use Recharts. The custom HTML bar charts in `PlaytimeChart.tsx` and
`CompetitiveBenchmark.tsx` are acceptable for simple bars but Recharts should
be preferred for any time-series, multi-series, or interactive charts.

### Database fields available

On `games`: `release_date` (DATE), `coming_soon` (BOOLEAN), `type` (TEXT:
game|dlc|demo|music|tool), `price_usd` (NUMERIC), `is_free` (BOOLEAN),
`positive_pct` (INTEGER), `review_count` (INTEGER), `review_count_english`
(INTEGER), `metacritic_score` (INTEGER, nullable), `platforms` (JSONB:
{windows, mac, linux}), `deck_compatibility` (INTEGER: 0=unknown, 1=unsupported,
2=playable, 3=verified), `review_velocity_lifetime` (NUMERIC, nullable).

On `reviews`: `posted_at` (TIMESTAMPTZ), `written_during_early_access` (BOOLEAN),
`voted_up` (BOOLEAN), `playtime_hours` (INTEGER).

Join tables: `game_genres` (appid, genre_id), `game_tags` (appid, tag_id, votes),
`game_categories` (appid, category_id, category_name).

Existing indexes: `idx_reviews_appid_posted`, `idx_reviews_appid_ea`,
`idx_reviews_appid_playtime`.

Precomputed storage: `index_insights` table (type, slug, insight_json, computed_at)
— used for expensive aggregate computations that shouldn't run in real time.

---

## Architecture: mandatory layering

All new backend code follows the three-layer pattern in CLAUDE.md:

```
Handler (FastAPI route)
  └── AnalyticsService (business logic, derived fields, formatting)
        └── AnalyticsRepository (pure SQL, returns raw rows)
```

**Repository** — pure SQL only. Returns raw dicts from the DB cursor. No computed
fields, no formatting, no business logic. Accepts validated inputs only (granularity
has already been whitelisted by the caller).

**AnalyticsService** — receives a repository instance via constructor injection. Contains
all Python-side logic: computing `ea_pct`, `positive_pct`, `trend` direction, share
percentages, period label formatting. Builds and returns the final response dict.

**Handler** — validates and parses query params (granularity whitelist, limit cap),
constructs `AnalyticsService`, calls the appropriate method, returns the result. No SQL,
no business logic.

---

## What to build

### 1. New repository methods: `AnalyticsRepository`

Add to `src/library-layer/library_layer/repositories/analytics_repo.py`.

Repository methods are pure SQL. They accept a validated `granularity` string that
has already been whitelisted by the service before passing it in. Never pass raw
user input directly to `DATE_TRUNC` — validation happens in `AnalyticsService` before
any repo method is called.

All methods return `list[dict]` — raw rows from the cursor as dicts. No wrapping
envelope, no computed fields.

**Data quality filter on all queries:** Every query includes `AND g.type = 'game'`
by default. DLC, demos, and soundtracks inflate release counts and distort
sentiment/pricing data. When the `game_type` parameter is set to `"dlc"`, filter
on `g.type = 'dlc'` instead. When `"all"`, omit the type filter entirely. This
is a Pro-only parameter — free users always see `type = 'game'`.

#### `find_release_volume_rows(granularity: str, genre_slug: str | None, tag_slug: str | None, limit: int) -> list[dict]`

Release count per time bucket, optionally filtered by genre or tag.

```sql
SELECT
    DATE_TRUNC(%s, g.release_date) AS period,
    COUNT(*) AS releases,
    ROUND(AVG(g.positive_pct), 1) AS avg_sentiment,
    ROUND(AVG(g.review_count), 0) AS avg_reviews,
    COUNT(*) FILTER (WHERE g.is_free) AS free_count
FROM games g
-- optional JOIN game_genres gg ON gg.appid = g.appid JOIN genres gn ON gg.genre_id = gn.id
-- optional JOIN game_tags gt ON gt.appid = g.appid JOIN tags t ON gt.tag_id = t.id
WHERE g.release_date IS NOT NULL
  AND g.coming_soon = FALSE
  AND g.type = 'game'       -- default; 'dlc' or omit when game_type param is set
  AND g.review_count >= 10
  -- AND gn.slug = %s   (when genre_slug is set)
  -- AND t.slug = %s    (when tag_slug is set)
GROUP BY 1
ORDER BY 1
LIMIT %s
```

Returns `list[dict]` with keys: `period` (datetime), `releases`, `avg_sentiment`,
`avg_reviews`, `free_count`.

#### `find_sentiment_distribution_rows(granularity: str, genre_slug: str | None, limit: int) -> list[dict]`

Sentiment breakdown per time bucket.

```sql
SELECT
    DATE_TRUNC(%s, g.release_date) AS period,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE g.positive_pct >= 70) AS positive_count,
    COUNT(*) FILTER (WHERE g.positive_pct >= 40 AND g.positive_pct < 70) AS mixed_count,
    COUNT(*) FILTER (WHERE g.positive_pct < 40) AS negative_count,
    ROUND(AVG(g.positive_pct), 1) AS avg_sentiment,
    ROUND(AVG(g.metacritic_score) FILTER (WHERE g.metacritic_score IS NOT NULL), 1) AS avg_metacritic
FROM games g
-- optional JOIN game_genres / genres when genre_slug is set
WHERE g.release_date IS NOT NULL
  AND g.coming_soon = FALSE
  AND g.type = 'game'
  AND g.review_count >= 10
GROUP BY 1
ORDER BY 1
LIMIT %s
```

Returns `list[dict]` with keys: `period`, `total`, `positive_count`, `mixed_count`,
`negative_count`, `avg_sentiment`, `avg_metacritic`.

#### `find_genre_share_rows(granularity: str, limit: int) -> list[dict]`

Raw genre counts per time bucket — no share computation here.

```sql
SELECT
    DATE_TRUNC(%s, g.release_date) AS period,
    gn.name AS genre,
    gn.slug AS genre_slug,
    COUNT(*) AS releases
FROM games g
JOIN game_genres gg ON gg.appid = g.appid
JOIN genres gn ON gg.genre_id = gn.id
WHERE g.release_date IS NOT NULL
  AND g.coming_soon = FALSE
  AND g.type = 'game'
  AND g.review_count >= 10
GROUP BY 1, 2, 3
ORDER BY 1, 4 DESC
LIMIT %s
```

Returns `list[dict]` with keys: `period`, `genre`, `genre_slug`, `releases`.

#### `find_velocity_distribution_rows(granularity: str, genre_slug: str | None, limit: int) -> list[dict]`

Review velocity distribution by release cohort.

Uses `review_velocity_lifetime` (migration `0009_game_velocity_cache.sql`). Falls
back to `review_count_english / NULLIF(CURRENT_DATE - release_date, 0)` for rows
where the column is NULL.

```sql
SELECT
    DATE_TRUNC(%s, g.release_date) AS period,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE COALESCE(g.review_velocity_lifetime,
        g.review_count_english::numeric / NULLIF(CURRENT_DATE - g.release_date, 0))
        < 1) AS velocity_under_1,
    COUNT(*) FILTER (WHERE COALESCE(g.review_velocity_lifetime,
        g.review_count_english::numeric / NULLIF(CURRENT_DATE - g.release_date, 0))
        BETWEEN 1 AND 10) AS velocity_1_10,
    COUNT(*) FILTER (WHERE COALESCE(g.review_velocity_lifetime,
        g.review_count_english::numeric / NULLIF(CURRENT_DATE - g.release_date, 0))
        BETWEEN 10 AND 50) AS velocity_10_50,
    COUNT(*) FILTER (WHERE COALESCE(g.review_velocity_lifetime,
        g.review_count_english::numeric / NULLIF(CURRENT_DATE - g.release_date, 0))
        > 50) AS velocity_50_plus
FROM games g
-- optional JOIN game_genres / genres when genre_slug is set
WHERE g.release_date IS NOT NULL
  AND g.coming_soon = FALSE
  AND g.type = 'game'
  AND g.review_count >= 10
  AND CURRENT_DATE - g.release_date > 0
GROUP BY 1
ORDER BY 1
LIMIT %s
```

Returns `list[dict]` with keys: `period`, `total`, `velocity_under_1`, `velocity_1_10`,
`velocity_10_50`, `velocity_50_plus`.

#### `find_price_trend_rows(granularity: str, genre_slug: str | None, limit: int) -> list[dict]`

Average price per time bucket. `free_pct` is computed in `AnalyticsService`, not here.

```sql
SELECT
    DATE_TRUNC(%s, g.release_date) AS period,
    COUNT(*) AS total,
    ROUND(AVG(g.price_usd) FILTER (WHERE NOT g.is_free), 2) AS avg_paid_price,
    ROUND(AVG(g.price_usd), 2) AS avg_price_incl_free,
    COUNT(*) FILTER (WHERE g.is_free) AS free_count
FROM games g
-- optional JOIN game_genres / genres when genre_slug is set
WHERE g.release_date IS NOT NULL
  AND g.coming_soon = FALSE
  AND g.type = 'game'
  AND g.review_count >= 10
GROUP BY 1
ORDER BY 1
LIMIT %s
```

Returns `list[dict]` with keys: `period`, `total`, `avg_paid_price`,
`avg_price_incl_free`, `free_count`.

#### `find_ea_trend_rows(granularity: str, limit: int) -> list[dict]`

Early Access counts per time bucket. `ea_pct` is computed in `AnalyticsService`.

```sql
SELECT
    DATE_TRUNC(%s, g.release_date) AS period,
    COUNT(*) AS total_releases,
    COUNT(*) FILTER (WHERE EXISTS (
        SELECT 1 FROM reviews r
        WHERE r.appid = g.appid AND r.written_during_early_access LIMIT 1
    )) AS ea_count,
    ROUND(AVG(g.positive_pct) FILTER (WHERE EXISTS (
        SELECT 1 FROM reviews r
        WHERE r.appid = g.appid AND r.written_during_early_access LIMIT 1
    )), 1) AS ea_avg_sentiment,
    ROUND(AVG(g.positive_pct) FILTER (WHERE NOT EXISTS (
        SELECT 1 FROM reviews r
        WHERE r.appid = g.appid AND r.written_during_early_access LIMIT 1
    )), 1) AS non_ea_avg_sentiment
FROM games g
WHERE g.release_date IS NOT NULL
  AND g.coming_soon = FALSE
  AND g.type = 'game'
  AND g.review_count >= 10
GROUP BY 1
ORDER BY 1
LIMIT %s
```

Returns `list[dict]` with keys: `period`, `total_releases`, `ea_count`,
`ea_avg_sentiment`, `non_ea_avg_sentiment`.

#### `find_platform_trend_rows(granularity: str, genre_slug: str | None, limit: int) -> list[dict]`

Platform support and Steam Deck verification rates per release cohort. Query
pattern adapted from existing `find_platform_distribution` (`analytics_repo.py:246`).

```sql
SELECT
    DATE_TRUNC(%s, g.release_date) AS period,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE (g.platforms->>'windows')::boolean) AS windows_count,
    COUNT(*) FILTER (WHERE (g.platforms->>'mac')::boolean) AS mac_count,
    COUNT(*) FILTER (WHERE (g.platforms->>'linux')::boolean) AS linux_count,
    COUNT(*) FILTER (WHERE g.deck_compatibility = 3) AS deck_verified,
    COUNT(*) FILTER (WHERE g.deck_compatibility = 2) AS deck_playable,
    COUNT(*) FILTER (WHERE g.deck_compatibility = 1) AS deck_unsupported
FROM games g
-- optional JOIN game_genres / genres when genre_slug is set
WHERE g.release_date IS NOT NULL
  AND g.coming_soon = FALSE
  AND g.type = 'game'
  AND g.review_count >= 10
GROUP BY 1
ORDER BY 1
LIMIT %s
```

Returns `list[dict]` with keys: `period`, `total`, `windows_count`, `mac_count`,
`linux_count`, `deck_verified`, `deck_playable`, `deck_unsupported`.

#### `find_engagement_depth_rows(granularity: str, genre_slug: str | None, limit: int) -> list[dict]`

Playtime distribution by release cohort. **This reads from `index_insights`** (precomputed),
not from a live `reviews` table scan. The batch job that populates this data is
a separate implementation concern (see "Batch dependency" section below).

```sql
SELECT insight_json
FROM index_insights
WHERE type = 'engagement_depth'
  AND slug = %s   -- e.g. "month:all" or "quarter:action"
ORDER BY computed_at DESC
LIMIT 1
```

The `insight_json` JSONB contains precomputed periods:
```json
[
  {
    "period": "2024-01-01",
    "total_reviews": 12480,
    "playtime_under_2h": 1872,
    "playtime_2_10h": 4368,
    "playtime_10_50h": 3744,
    "playtime_50_200h": 1872,
    "playtime_200h_plus": 624
  }
]
```

Returns `list[dict]` parsed from the stored JSONB. If no precomputed data exists
for the requested granularity/genre combination, returns `[]`.

#### `find_category_trend_rows(granularity: str, limit: int) -> list[dict]`

Steam category adoption rates per release cohort. Categories include: Single-player,
Multi-player, Co-op, Steam Workshop, VR Supported, Full controller support,
Steam Cloud, Steam Achievements.

```sql
SELECT
    DATE_TRUNC(%s, g.release_date) AS period,
    gc.category_name,
    COUNT(*) AS games_with_category
FROM games g
JOIN game_categories gc ON gc.appid = g.appid
WHERE g.release_date IS NOT NULL
  AND g.coming_soon = FALSE
  AND g.type = 'game'
  AND g.review_count >= 10
  AND gc.category_name IN (
    'Single-player', 'Multi-player', 'Co-op', 'Steam Workshop',
    'VR Supported', 'Full controller support', 'Steam Cloud', 'Steam Achievements'
  )
GROUP BY 1, 2
ORDER BY 1, 3 DESC
LIMIT %s
```

Returns `list[dict]` with keys: `period`, `category_name`, `games_with_category`.

**Note:** The total game count per period (needed for computing adoption %) is
available from `find_release_volume_rows` — the service can reuse that data
or issue a simple `COUNT(*)` grouped by period. Avoid duplicating the base count
query in this method.

### 2. New service: `AnalyticsService`

Create `src/library-layer/library_layer/services/analytics_service.py`.

`AnalyticsService` owns all Python-side computation. It receives an `AnalyticsRepository`
instance via constructor injection — never instantiates the repo itself.

```python
from library_layer.repositories.analytics_repo import AnalyticsRepository

VALID_GRANULARITIES = {"week", "month", "quarter", "year"}

class AnalyticsService:
    def __init__(self, analytics_repo: AnalyticsRepository) -> None:
        self._repo = analytics_repo

    def _validate_granularity(self, granularity: str) -> str:
        if granularity not in VALID_GRANULARITIES:
            raise ValueError(f"Invalid granularity: {granularity!r}")
        return granularity

    def _format_period(self, period: datetime, granularity: str) -> str:
        # "2024-01" for month, "2024" for year, "2024-Q1" for quarter, "2024-W03" for week
        ...

    def get_release_volume(
        self,
        granularity: str = "month",
        genre_slug: str | None = None,
        tag_slug: str | None = None,
        limit: int = 100,
    ) -> dict: ...

    def get_sentiment_distribution(
        self,
        granularity: str = "month",
        genre_slug: str | None = None,
        limit: int = 100,
    ) -> dict: ...

    def get_genre_share(
        self,
        granularity: str = "year",
        top_n: int = 5,
        limit: int = 100,
    ) -> dict: ...

    def get_velocity_distribution(
        self,
        granularity: str = "month",
        genre_slug: str | None = None,
        limit: int = 100,
    ) -> dict: ...

    def get_price_trend(
        self,
        granularity: str = "year",
        genre_slug: str | None = None,
        limit: int = 100,
    ) -> dict: ...

    def get_ea_trend(
        self,
        granularity: str = "year",
        limit: int = 100,
    ) -> dict: ...

    def get_platform_trend(
        self,
        granularity: str = "year",
        genre_slug: str | None = None,
        limit: int = 100,
    ) -> dict: ...

    def get_engagement_depth(
        self,
        granularity: str = "year",
        genre_slug: str | None = None,
        limit: int = 100,
    ) -> dict: ...

    def get_category_trend(
        self,
        granularity: str = "year",
        top_n: int = 4,
        limit: int = 100,
    ) -> dict: ...
```

**Business logic owned by `AnalyticsService` (not the repository):**

- `_validate_granularity` — whitelist check before any repo call. Raises `ValueError`
  on invalid input; the handler converts this to a 400 response.
- `_format_period` — converts a `datetime` from the DB into a human-readable period
  label: `"2024-01"` (month), `"2024"` (year), `"2024-Q1"` (quarter), `"2024-W03"` (week).
- `get_release_volume`: calls `find_release_volume_rows`, formats periods, computes
  `summary` (total_releases, avg_per_period, trend). **Trend logic:** compare mean
  of last 3 period `releases` vs overall mean — `> 1.2×` = `"increasing"`,
  `< 0.8×` = `"decreasing"`, else `"stable"`.
- `get_sentiment_distribution`: calls `find_sentiment_distribution_rows`, formats
  periods, computes `positive_pct` per period as `positive_count / total * 100`.
- `get_genre_share`: calls `find_genre_share_rows`, aggregates raw rows by period,
  ranks genres by total volume across all periods, keeps top N and buckets the rest
  as `"Other"`, computes `shares` dict per period as `genre_count / period_total`.
- `get_price_trend`: calls `find_price_trend_rows`, formats periods, computes
  `free_pct` per period as `free_count / total * 100`.
- `get_ea_trend`: calls `find_ea_trend_rows`, formats periods, computes `ea_pct`
  per period as `ea_count / total_releases * 100`.
- `get_velocity_distribution`: calls `find_velocity_distribution_rows`, formats
  periods. No additional computation needed.
- `get_platform_trend`: calls `find_platform_trend_rows`, formats periods, computes
  `mac_pct`, `linux_pct`, `deck_verified_pct`, `deck_playable_pct` per period.
- `get_engagement_depth`: calls `find_engagement_depth_rows`, formats periods,
  computes band percentages from raw counts. Returns empty response with a
  `"data_available": false` flag if no precomputed data exists yet.
- `get_category_trend`: calls `find_category_trend_rows`, also calls
  `find_release_volume_rows` to get total games per period (reuses existing method).
  Computes adoption % per period per category. Free users see top 4, Pro see all 8.

**Response shapes** (built by the service, returned to the handler as plain `dict`):

`get_release_volume` returns:
```json
{
  "granularity": "month",
  "filter": {"genre": "action"},
  "periods": [
    {"period": "2024-01", "releases": 142, "avg_sentiment": 71.3, "avg_reviews": 485, "free_count": 23}
  ],
  "summary": {"total_releases": 4821, "avg_per_period": 201, "trend": "increasing"}
}
```

`get_sentiment_distribution` returns:
```json
{
  "granularity": "quarter",
  "periods": [
    {"period": "2024-Q1", "total": 387, "positive_count": 245, "mixed_count": 98,
     "negative_count": 44, "positive_pct": 63.3, "avg_sentiment": 68.1}
  ]
}
```

`get_genre_share` returns:
```json
{
  "granularity": "year",
  "genres": ["Action", "Indie", "RPG", "Strategy", "Adventure", "Other"],
  "periods": [
    {"period": "2023", "total": 1842, "shares": {"Action": 0.28, "Indie": 0.22, "Other": 0.14}}
  ]
}
```

`get_velocity_distribution` returns:
```json
{
  "granularity": "quarter",
  "periods": [
    {"period": "2024-Q1", "total": 387, "velocity_under_1": 201,
     "velocity_1_10": 132, "velocity_10_50": 41, "velocity_50_plus": 13}
  ]
}
```

`get_price_trend` returns:
```json
{
  "granularity": "year",
  "periods": [
    {"period": "2023", "total": 1842, "avg_paid_price": 18.50,
     "avg_price_incl_free": 14.20, "free_count": 312, "free_pct": 16.9}
  ]
}
```

`get_ea_trend` returns:
```json
{
  "granularity": "year",
  "periods": [
    {"period": "2023", "total_releases": 1842, "ea_count": 423,
     "ea_pct": 23.0, "ea_avg_sentiment": 74.2, "non_ea_avg_sentiment": 68.1}
  ]
}
```

`get_platform_trend` returns:
```json
{
  "granularity": "year",
  "periods": [
    {"period": "2023", "total": 1842, "mac_pct": 28.4, "linux_pct": 22.1,
     "deck_verified_pct": 31.2, "deck_playable_pct": 24.8}
  ]
}
```

`get_engagement_depth` returns:
```json
{
  "granularity": "year",
  "data_available": true,
  "periods": [
    {"period": "2023", "total_reviews": 48210,
     "playtime_under_2h_pct": 15.0, "playtime_2_10h_pct": 35.0,
     "playtime_10_50h_pct": 30.0, "playtime_50_200h_pct": 15.0,
     "playtime_200h_plus_pct": 5.0}
  ]
}
```

`get_category_trend` returns:
```json
{
  "granularity": "year",
  "categories": ["Single-player", "Multi-player", "Steam Cloud", "Full controller support"],
  "periods": [
    {"period": "2023", "total": 1842,
     "adoption": {"Single-player": 0.92, "Multi-player": 0.31, "Steam Cloud": 0.48,
                   "Full controller support": 0.44}}
  ]
}
```

`get_sentiment_distribution` response now also includes `avg_metacritic` per period
(may be `null` if no games in that period have a Metacritic score):
```json
{"period": "2024-Q1", "total": 387, "positive_count": 245, "mixed_count": 98,
 "negative_count": 44, "positive_pct": 63.3, "avg_sentiment": 68.1, "avg_metacritic": 72.4}
```

### 3. New API endpoints

Add to `src/lambda-functions/lambda_functions/api/handler.py`.

Instantiate `AnalyticsService` at module level alongside the other repos and services:

```python
_analytics_service = AnalyticsService(_analytics_repo)
```

The handler's only jobs are: parse query params, call the service, return the result.
`granularity` validation and `limit` capping happen in the service — the handler just
passes the raw string and lets `AnalyticsService._validate_granularity` raise `ValueError`,
which the handler converts to a 400 response.

All 9 endpoints share a common query parameter pattern:

| Param | Type | Default | Values |
|-------|------|---------|--------|
| `granularity` | str | `"month"` | `week`, `month`, `quarter`, `year` |
| `genre` | str? | None | Genre slug filter (where applicable) |
| `type` | str | `"game"` | `game`, `dlc`, `all` — Pro-only, free always `game` |
| `limit` | int | 100 | Max periods returned (cap at 200) |

All 9 endpoints follow this pattern:

```python
@app.get("/api/analytics/trends/release-volume")
async def get_trend_release_volume(
    granularity: str = "month",
    genre: str | None = None,
    tag: str | None = None,
    limit: int = 100,
) -> dict:
    try:
        return _analytics_service.get_release_volume(
            granularity=granularity, genre_slug=genre, tag_slug=tag,
            limit=min(limit, 200),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
```

All 9 endpoints apply the same `min(limit, 200)` cap and the same `ValueError → 400`
conversion. Endpoints with no genre filter (`genre-share`, `early-access`,
`categories`) simply omit those parameters.

| Endpoint                                   | Service method               | Notes                             |
|--------------------------------------------|------------------------------|-----------------------------------|
| `GET /api/analytics/trends/release-volume` | `get_release_volume`         | `genre`, `tag` filters            |
| `GET /api/analytics/trends/sentiment`      | `get_sentiment_distribution` | `genre` filter                    |
| `GET /api/analytics/trends/genre-share`    | `get_genre_share`            | `top_n` param (default 5, max 15) |
| `GET /api/analytics/trends/velocity`       | `get_velocity_distribution`  | `genre` filter                    |
| `GET /api/analytics/trends/pricing`        | `get_price_trend`            | `genre` filter                    |
| `GET /api/analytics/trends/early-access`   | `get_ea_trend`               | no filter params                  |
| `GET /api/analytics/trends/platforms`      | `get_platform_trend`         | `genre` filter                    |
| `GET /api/analytics/trends/engagement`     | `get_engagement_depth`       | `genre` filter; reads precomputed |
| `GET /api/analytics/trends/categories`     | `get_category_trend`         | `top_n` param (default 4, max 8)  |

### 3. Frontend types

Add to `frontend/lib/types.ts`:

```typescript
type Granularity = "week" | "month" | "quarter" | "year";

interface TrendPeriod {
  period: string;  // ISO date or "YYYY", "YYYY-QN", "YYYY-MM", "YYYY-WNN"
}

interface ReleaseVolumePeriod extends TrendPeriod {
  releases: number;
  avg_sentiment: number;
  avg_reviews: number;
  free_count: number;
}

interface SentimentDistPeriod extends TrendPeriod {
  total: number;
  positive_count: number;
  mixed_count: number;
  negative_count: number;
  positive_pct: number;
  avg_sentiment: number;
  avg_metacritic: number | null;
}

interface GenreSharePeriod extends TrendPeriod {
  total: number;
  shares: Record<string, number>;
}

interface VelocityDistPeriod extends TrendPeriod {
  total: number;
  velocity_under_1: number;
  velocity_1_10: number;
  velocity_10_50: number;
  velocity_50_plus: number;
}

interface PriceTrendPeriod extends TrendPeriod {
  total: number;
  avg_paid_price: number;
  avg_price_incl_free: number;
  free_count: number;
  free_pct: number;
}

interface EATrendPeriod extends TrendPeriod {
  total_releases: number;
  ea_count: number;
  ea_pct: number;
  ea_avg_sentiment: number;
  non_ea_avg_sentiment: number;
}

interface PlatformTrendPeriod extends TrendPeriod {
  total: number;
  mac_pct: number;
  linux_pct: number;
  deck_verified_pct: number;
  deck_playable_pct: number;
}

interface EngagementDepthPeriod extends TrendPeriod {
  total_reviews: number;
  playtime_under_2h_pct: number;
  playtime_2_10h_pct: number;
  playtime_10_50h_pct: number;
  playtime_50_200h_pct: number;
  playtime_200h_plus_pct: number;
}

interface CategoryTrendPeriod extends TrendPeriod {
  total: number;
  adoption: Record<string, number>;
}
```

### 4. Frontend API client functions

Add to `frontend/lib/api.ts`:

```typescript
function getAnalyticsTrendReleaseVolume(params: {
  granularity?: Granularity;
  genre?: string;
  tag?: string;
  limit?: number;
}): Promise<{ granularity: string; periods: ReleaseVolumePeriod[]; summary: object }>

function getAnalyticsTrendSentiment(params: {
  granularity?: Granularity;
  genre?: string;
  limit?: number;
}): Promise<{ granularity: string; periods: SentimentDistPeriod[] }>

function getAnalyticsTrendGenreShare(params: {
  granularity?: Granularity;
  limit?: number;
}): Promise<{ granularity: string; genres: string[]; periods: GenreSharePeriod[] }>

function getAnalyticsTrendVelocity(params: {
  granularity?: Granularity;
  genre?: string;
  limit?: number;
}): Promise<{ granularity: string; periods: VelocityDistPeriod[] }>

function getAnalyticsTrendPricing(params: {
  granularity?: Granularity;
  genre?: string;
  limit?: number;
}): Promise<{ granularity: string; periods: PriceTrendPeriod[] }>

function getAnalyticsTrendEarlyAccess(params: {
  granularity?: Granularity;
  limit?: number;
}): Promise<{ granularity: string; periods: EATrendPeriod[] }>

function getAnalyticsTrendPlatforms(params: {
  granularity?: Granularity;
  genre?: string;
  limit?: number;
}): Promise<{ granularity: string; periods: PlatformTrendPeriod[] }>

function getAnalyticsTrendEngagement(params: {
  granularity?: Granularity;
  genre?: string;
  limit?: number;
}): Promise<{ granularity: string; data_available: boolean; periods: EngagementDepthPeriod[] }>

function getAnalyticsTrendCategories(params: {
  granularity?: Granularity;
  top_n?: number;
  limit?: number;
}): Promise<{ granularity: string; categories: string[]; periods: CategoryTrendPeriod[] }>
```

### 5. Frontend page: `/analytics`

Create `frontend/app/analytics/page.tsx` (server component) and
`frontend/app/analytics/AnalyticsClient.tsx` (client component).

#### Page layout

The page has a **shared control bar** at the top and **9 chart sections** below.

**Control bar (Pro-gated):**
- Granularity toggle: Week | Month | Quarter | Year (default: Month)
- Genre filter: dropdown populated from `getGenres()` (optional, "All Genres" default)
- Controls apply to all charts simultaneously. Changing a control re-fetches all charts.
- Free users see the control bar blurred with a "Customize with Pro →" CTA overlay
  (see free/pro pattern above). Free users always see monthly granularity, all genres.
- **Only granularity + genre live in the shared bar.** Per-chart Pro controls
  (tag filter, type selector, top-N) render in the respective card headers.

**Chart sections** (each in a shadcn `Card`):

1. **Release Volume** — `TrendBarChart` (Recharts `BarChart` / `ComposedChart`)
   - X: time period, Y: release count
   - Summary stat line above: total releases, avg per period, trend direction
   - Free: bars + 3-period moving average trend line (grey)
   - **Pro extras:** avg sentiment overlay line (amber) on secondary Y axis;
     tag + type dropdowns in card header (scoped to this chart)

2. **Sentiment Distribution** — `TrendStackedArea` (Recharts `AreaChart`)
   - X: time period, Y: percentage (0–100%), pre-computed normalized values
   - Three stacked areas: Positive (green), Mixed (amber), Negative (red)
   - Tooltip shows counts + percentages
   - **Pro extra:** toggle between normalized % view and raw count view;
     Metacritic overlay line (indigo) on secondary Y axis

3. **Genre Share** — `TrendStackedArea` (Recharts `AreaChart`)
   - X: time period, Y: percentage share (0–100%)
   - One area per top genre, "Other" at bottom; legend with genre colors
   - Free: top 5 genres, yearly granularity (unaffected by control bar genre filter)
   - **Pro extra:** granularity toggle (week/month map to quarter);
     choose top N genres (5/10/15) via radio buttons in card header

4. **Review Velocity** — `TrendStackedBarChart` (Recharts `BarChart`)
   - X: time period, Y: game count per velocity band
   - Four stacked bars: <1/day (grey), 1–10/day (blue), 10–50/day (teal), 50+/day (green)
   - **Pro extra:** genre filter via shared control bar

5. **Pricing Trends** — `TrendComposed` (Recharts `ComposedChart`)
   - Bar: free-to-play % (left Y axis); Line: avg paid price (right Y axis)
   - Free: quarterly granularity, bar + line combo (both always visible)
   - **Pro extra:** granularity toggle, genre filter

6. **Early Access Trends** — `TrendComposed` (Recharts `ComposedChart`)
   - Free: quarterly granularity, EA % as bar only
   - **Pro extra:** granularity toggle; switches to EA count bar +
     EA % line + EA avg sentiment + non-EA avg sentiment lines

7. **Platform & Steam Deck** — `TrendComposed` (Recharts `ComposedChart`)
   - Lines: Mac support %, Linux support %, Deck Verified %
   - Tooltip shows raw counts + percentages
   - Free: quarterly granularity, Mac/Linux/Deck Verified % lines
   - **Pro extra:** granularity toggle, genre filter;
     full Deck breakdown adds Playable % + Unsupported % lines

8. **Engagement Depth** — `TrendStackedArea` (Recharts `AreaChart`)
   - X: time period, Y: percentage of reviews by playtime band
   - Five stacked areas: <2h (red), 2–10h (amber), 10–50h (blue), 50–200h (teal), 200h+ (green)
   - Tooltip shows "X% of reviews from players with Y hours"
   - Free: all genres, yearly
   - **Pro extra:** granularity toggle, genre filter
   - **Empty state:** if precomputed data is not yet available, show "Engagement data
     is being computed — check back soon" instead of the chart

9. **Feature Adoption** — `TrendComposed` (Recharts `ComposedChart`)
   - X: time period, Y: adoption % (0–100%)
   - One line per category (e.g., Multiplayer, Co-op, Workshop, VR, Controller, Cloud)
   - Free: top 4 categories, yearly
   - **Pro extra:** all 8 categories, granularity toggle

#### Data fetching pattern

Follow the existing pattern in `GameReportClient.tsx`: server component loads
the page shell, `AnalyticsClient` fetches data in `useEffect` with loading states.

Fetch all 9 endpoints in parallel on mount and when controls change. Use
`Promise.allSettled` (like `trending/page.tsx` does) so one slow/failing chart
doesn't block the others.

#### Responsive design

- Desktop: 2-column grid for charts (5 rows — last row has 1 chart centered or full-width)
- Mobile: single column stack
- Charts should have a minimum height (300px) and responsive width

#### Empty states

If a chart has no data (e.g. too few games in a niche genre), show a centered
message: "Not enough data for this view" rather than an empty chart.

### 6. New chart components

Create in `frontend/components/trends/`:

#### `TrendBarChart.tsx`
Generic time-series bar chart wrapping Recharts `BarChart`. Props:
- `data: TrendPeriod[]`
- `dataKey: string` (which field to chart)
- `xKey?: string` (default `"period"`)
- `color?: string`
- `granularity: Granularity` (for X-axis label formatting)
- `secondaryLine?: { dataKey: string; color: string }` (Pro-only overlay — only rendered when prop is present)

#### `TrendStackedArea.tsx`
Stacked area chart wrapping Recharts `AreaChart`. Props:
- `data: TrendPeriod[]`
- `series: { key: string; label: string; color: string }[]`
- `granularity: Granularity`
- `normalized?: boolean` (default `true` — show as %; when `false` show raw counts — Pro toggle)

#### `TrendComposed.tsx`
Composed chart (bars + lines) wrapping Recharts `ComposedChart`. Props:
- `data: TrendPeriod[]`
- `bars: { dataKey: string; label: string; color: string }[]`
- `lines: { dataKey: string; label: string; color: string }[]`
- `granularity: Granularity`

All chart components should:
- Accept a `height?: number` prop (default 300)
- Use `ResponsiveContainer` from Recharts for fluid width
- Format X axis labels based on `granularity` ("Jan 2024" for month, "2024" for year,
  "Q1 2024" for quarter, "W12 2024" for week)
- Include Recharts `Tooltip` with formatted values
- Return an empty-state div ("Not enough data for this view") if `data.length < 2`

#### `GranularityToggle.tsx`
Simple button group for selecting granularity. Props:
- `value: Granularity`
- `onChange: (g: Granularity) => void`
- `disabled?: boolean` (pass `!isPro` to visually disable without blur — the parent
  wrapper handles the blur/overlay)

### 7. Navigation

Add "Analytics" link to `frontend/components/layout/Navbar.tsx` alongside existing
nav items. Position after "Trending" and before "Search". Use `href="/analytics"`.

---

## Migration dependency

The velocity distribution chart depends on `review_velocity_lifetime` from
migration `0009_game_velocity_cache.sql` (defined in `game-temporal-intelligence.md`).
If that migration hasn't been applied yet, the fallback SQL
(`review_count_english / NULLIF(CURRENT_DATE - release_date, 0)`) handles it.

The category trends chart may benefit from a new index:
```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_game_categories_appid
  ON game_categories(appid);
```
Add this to the next migration if query performance warrants it. The
`game_categories` table is small enough per-game that it may not be critical.

All other charts use columns and tables that already exist. No new migration is
required for this feature.

## Batch dependency: engagement depth precomputation

The engagement depth chart reads precomputed data from `index_insights`, NOT
from a live `reviews` table scan. A batch job must populate this data.

**This batch job is NOT part of this prompt's implementation scope.** It should
be built separately. This prompt defines only the data shape, API contract, and
frontend chart.

**Batch job specification (for separate implementation):**

- **Trigger:** EventBridge schedule (e.g., daily) or post-crawl SNS event
- **What it computes:** For each combination of (granularity, genre_slug):
  aggregate `reviews.playtime_hours` into 5 bands (<2h, 2-10h, 10-50h, 50-200h, 200h+),
  grouped by `DATE_TRUNC(granularity, g.release_date)`
- **Where it writes:** `index_insights` table with `type = 'engagement_depth'`,
  `slug = '{granularity}:{genre_slug or "all"}'`, `insight_json = [...]`
- **Precompute for:** `month:all`, `quarter:all`, `year:all`, plus per-genre
  variants for top 10 genres by game count
- **If no precomputed data exists:** The API returns `{"data_available": false, "periods": []}`,
  and the frontend shows "Engagement data is being computed — check back soon"

---

## Constraints

- All SQL lives in `AnalyticsRepository` — no SQL in handlers or services
- All business logic (derived fields, validation, formatting) lives in `AnalyticsService`
  — no business logic in handlers or repositories
- Handlers call `AnalyticsService` methods only — never `_analytics_repo` directly
- `granularity` whitelisted in `AnalyticsService._validate_granularity` before any repo
  call — never interpolate user input directly into SQL identifiers
- Cap `limit` at 200 periods: `min(limit, 200)` in the handler before passing to service
- `AND g.type = 'game'` on all queries by default — exclude DLC, demos, soundtracks.
  `type` param (`game`|`dlc`|`all`) is Pro-only; free users always get `type = 'game'`
- Minimum `review_count >= 10` filter on all queries to exclude noise
- Exclude `coming_soon = TRUE` games from all trend queries
- Engagement depth chart reads from `index_insights` (precomputed) — never scan
  the `reviews` table in a real-time API call for catalog-wide playtime aggregation
- `AnalyticsService` constructor takes `AnalyticsRepository` as a required parameter —
  instantiated once at module level in `handler.py` alongside the other repos
- All new Recharts charts use `ResponsiveContainer` for fluid sizing
- Follow existing component patterns: Tailwind styling, shadcn Card wrappers
- Type hints on all Python parameters and return types (Python 3.12)
- TypeScript types for all API response shapes
- `poetry run pytest -v` and `npm run build` must pass

---

## Files to create / modify

| File                                                             | Action                                                                        |
|------------------------------------------------------------------|-------------------------------------------------------------------------------|
| `src/library-layer/library_layer/repositories/analytics_repo.py` | Add 9 `*_rows` methods (pure SQL) + `type` filter on all                      |
| `src/library-layer/library_layer/services/analytics_service.py`  | Create — `AnalyticsService` with business logic for 9 chart types             |
| `src/lambda-functions/lambda_functions/api/handler.py`           | Add `_analytics_service` instance + 9 `GET /api/analytics/trends/*` endpoints |
| `frontend/lib/types.ts`                                          | Add 12 trend types (Granularity + 9 period interfaces + TrendPeriod base + CategoryTrendPeriod) |
| `frontend/lib/api.ts`                                            | Add 9 API client functions                                                    |
| `frontend/app/analytics/page.tsx`                                | Create — server component shell                                               |
| `frontend/app/analytics/AnalyticsClient.tsx`                     | Create — client component with 9 charts + controls                            |
| `frontend/components/trends/TrendBarChart.tsx`                   | Create — generic time-series bar chart                                        |
| `frontend/components/trends/TrendStackedArea.tsx`                | Create — stacked area chart                                                   |
| `frontend/components/trends/TrendComposed.tsx`                   | Create — composed bar + line chart                                            |
| `frontend/components/trends/GranularityToggle.tsx`               | Create — granularity selector                                                 |
| `frontend/components/trends/ProControlsOverlay.tsx`              | Create — blur wrapper + "Customize with Pro" CTA                              |
| `frontend/components/layout/Navbar.tsx`                          | Add "Analytics" nav link                                                      |
| `tests/repositories/test_analytics_repo.py`                      | Add tests for the 9 new `*_rows` methods                                      |
| `tests/services/test_analytics_service.py`                       | Create — tests for `AnalyticsService` business logic                          |

---

## Testing

### Backend

**Repository tests** — add to `tests/repositories/test_analytics_repo.py`:
- Seed 10–20 games with varying `release_date`, `positive_pct`, `price_usd`,
  `is_free`, `review_count`, `type`, `platforms`, `deck_compatibility`,
  `metacritic_score` values across multiple genres
- Seed `game_categories` rows for the seeded games
- Seed reviews with `written_during_early_access` for EA trend tests
- Seed `index_insights` row with `type = 'engagement_depth'` for engagement tests
- Test each `*_rows` method: verify correct columns are returned, rows are ordered
  by period, genre/tag filters apply, empty result set returns `[]`
- Test `type = 'game'` filter excludes DLC/demo rows
- Test `LIMIT` parameter is respected (pass `limit=2`, verify at most 2 rows)
- Test `find_engagement_depth_rows` returns `[]` when no precomputed data exists
- Repository tests do NOT test business logic (that belongs in service tests)

**Service tests** — create `tests/services/test_analytics_service.py`:
- Unit tests with a mocked `AnalyticsRepository` — stub `find_*_rows` to return
  controlled data; assert the service computes the correct derived fields
- Test `_validate_granularity`: valid values pass, invalid raises `ValueError`
- Test `_format_period`: verify output format for each granularity value
- Test trend calculation logic (increasing/stable/decreasing) directly
- Test `get_genre_share` share computation and "Other" bucketing
- Test `ea_pct`, `free_pct`, `positive_pct` derivations
- Test `get_platform_trend` computes `mac_pct`, `linux_pct`, `deck_verified_pct` correctly
- Test `get_engagement_depth` returns `data_available: false` when rows are empty
- Test `get_category_trend` adoption % computation and top-N filtering
- Test empty input (`[]` rows) returns sensible empty response without division errors

### Frontend
Add to `frontend/tests/`:
- Update `fixtures/mock-data.ts` with mock trend API responses for all 9 endpoints
- Update `fixtures/api-mock.ts` with `/api/analytics/trends/*` route mocks
- E2E test: navigate to `/analytics`, verify all 9 charts render with mock data
- E2E test (`isPro = true`): change granularity toggle, verify all charts re-fetch
- E2E test (`isPro = true`): select genre filter, verify charts re-fetch with `genre` param
- E2E test (`isPro = false`): control bar has `blur-sm` class and "Customize with Pro" link is visible
- E2E test (`isPro = false`): all 9 charts still render (free view, default params)
- E2E test: engagement chart shows "being computed" message when `data_available` is false
