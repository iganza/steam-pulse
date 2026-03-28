# Catalog Trends Dashboard — Interactive Analytics

## Background

SteamPulse currently offers per-game analytics (sentiment, velocity, playtime,
EA impact) and genre-scoped summaries (price positioning, release timing,
platform gaps). What's missing is a **catalog-wide trends dashboard** — interactive
charts that let users explore patterns across the entire Steam catalog over time.

The goal: a dedicated `/trends` page where users can see how Steam's catalog is
evolving — release volume, genre shifts, sentiment patterns, review velocity
distributions — across configurable time windows with drill-down by genre, tag,
and price tier.

---

## Free vs Pro access model

All 6 charts are visible to every user. Free users see each chart rendered with
sensible defaults — they can hover and read tooltips. The **control bar**
(granularity toggle + genre filter) and certain per-chart extras are Pro-only.

### Tiering table

| Chart | Free defaults | Pro extras |
|-------|--------------|------------|
| Release Volume | Monthly, all genres, bar + trend line | Granularity toggle, genre/tag filter |
| Sentiment Distribution | Monthly, all genres, stacked % area | Granularity toggle, genre filter, toggle %/raw count |
| Genre Share | Yearly, top 5 genres | Granularity toggle (quarter/year), choose top N genres |
| Review Velocity | Monthly, all genres | Granularity toggle, genre filter |
| Pricing Trends | Yearly, avg paid price line only | Granularity toggle, genre filter, overlay free-to-play % |
| Early Access | Yearly, EA % bar only | Granularity toggle, add EA vs non-EA sentiment lines |

### Implementation pattern

**Prerequisite:** `pro-gating-context.md` must be implemented first. It creates
`frontend/lib/pro.tsx` with `usePro()` and mounts `ProProvider` at the app root.

In `TrendsClient.tsx`, consume pro status from context:

```typescript
import { usePro } from "@/lib/pro";

// Inside the component:
const isPro = usePro();
```

Pass `isPro` down as a prop to chart sections that have pro extras (same pattern
as `GameReportClient.tsx` passes it to `PlaytimeChart` and `CompetitiveBenchmark`).

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

---

## What already exists (reuse — do NOT rebuild)

### Backend

| Method / Endpoint | File | What it provides |
|---|---|---|
| `AnalyticsRepository.find_release_timing(genre_slug)` | `analytics_repo.py:173` | Monthly release density by month-of-year (Jan–Dec), last 5 years, single genre. Aggregates by calendar month, NOT by actual time period. |
| `AnalyticsRepository.find_tag_trend(tag_slug)` | `analytics_repo.py` | Yearly game count + avg sentiment for a single tag (2015+) |
| `AnalyticsRepository.find_price_positioning(genre_slug)` | `analytics_repo.py` | Price distribution + sentiment by price range, single genre snapshot |
| `GameRepository.list_games(...)` | `game_repo.py` | Full filtering: genre, tag, year_from/to, sentiment, price_tier, min_reviews, sort, pagination |
| `ReviewRepository.find_review_velocity(appid)` | `review_repo.py:325` | Per-game monthly velocity + trend (24 months) |
| `GET /api/analytics/release-timing?genre=` | `api/handler.py` | Exposes `find_release_timing` |
| `GET /api/tags/{slug}/trend` | `api/handler.py` | Exposes `find_tag_trend` |
| `GET /api/analytics/price-positioning?genre=` | `api/handler.py` | Exposes `find_price_positioning` |

**Key gap:** Existing analytics are either per-game or single-genre snapshots.
None provide catalog-wide time-series with configurable granularity and
cross-genre comparison.

### Frontend

| Component | File | What it provides |
|---|---|---|
| Recharts (`recharts@3.8.0`) | `package.json` | Only charting library — area charts used in `SentimentTimeline.tsx` |
| `SentimentTimeline.tsx` | `components/game/` | Recharts `AreaChart` for weekly sentiment — pattern to follow |
| `SearchClient.tsx` | `app/search/` | Filter UI with genre/tag/year/sentiment/price dropdowns — reusable filter patterns |
| `GameCard.tsx` | `components/game/` | Reusable game tile for drill-down results |
| Tailwind + shadcn/ui | `components/ui/` | Card, Badge, Button primitives |
| Motion (`motion@12.36.0`) | `package.json` | Animation library for transitions |

**Charting note:** Recharts is the only charting library. All new charts should
use Recharts. The custom HTML bar charts in `PlaytimeChart.tsx` and
`CompetitiveBenchmark.tsx` are acceptable for simple bars but Recharts should
be preferred for any time-series, multi-series, or interactive charts.

### Database fields available

On `games`: `release_date` (DATE), `coming_soon` (BOOLEAN), `price_usd`
(NUMERIC), `is_free` (BOOLEAN), `positive_pct` (INTEGER), `review_count`
(INTEGER), `review_count_english` (INTEGER).

On `reviews`: `posted_at` (TIMESTAMPTZ), `written_during_early_access` (BOOLEAN),
`voted_up` (BOOLEAN).

Join tables: `game_genres` (appid, genre_id), `game_tags` (appid, tag_id, votes).

Existing indexes: `idx_reviews_appid_posted`, `idx_reviews_appid_ea`.

---

## What to build

### 1. New repository methods: `AnalyticsRepository`

Add to `src/library-layer/library_layer/repositories/analytics_repo.py`.

All methods accept a `granularity` parameter (`"week"` | `"month"` | `"quarter"` | `"year"`)
that maps to `DATE_TRUNC(granularity, g.release_date)`. Validate the value in
Python before interpolating — use a whitelist, not user input directly.

#### `find_release_volume(granularity, genre_slug?, tag_slug?, limit?) -> dict`

Release count per time bucket, optionally filtered by genre or tag.

```sql
SELECT
    DATE_TRUNC(%s, g.release_date) AS period,
    COUNT(*) AS releases,
    ROUND(AVG(g.positive_pct), 1) AS avg_sentiment,
    ROUND(AVG(g.review_count), 0) AS avg_reviews,
    COUNT(*) FILTER (WHERE g.is_free) AS free_count
FROM games g
-- optional JOIN game_genres / game_tags if filtering
WHERE g.release_date IS NOT NULL
  AND g.coming_soon = FALSE
  AND g.review_count >= 10
GROUP BY 1
ORDER BY 1
LIMIT %s  -- default 200 to bound response size
```

Returns:
```json
{
  "granularity": "month",
  "filter": {"genre": "action"} | {},
  "periods": [
    {
      "period": "2024-01",
      "releases": 142,
      "avg_sentiment": 71.3,
      "avg_reviews": 485,
      "free_count": 23
    }
  ],
  "summary": {
    "total_releases": 4821,
    "avg_per_period": 201,
    "trend": "increasing" | "stable" | "decreasing"
  }
}
```

Trend: compare last 3 periods avg vs overall avg. > 1.2x = "increasing",
< 0.8x = "decreasing", else "stable".

#### `find_sentiment_distribution(granularity, genre_slug?, limit?) -> dict`

Sentiment breakdown per time bucket — how many games fall into each sentiment
band per period.

```sql
SELECT
    DATE_TRUNC(%s, g.release_date) AS period,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE g.positive_pct >= 70) AS positive_count,
    COUNT(*) FILTER (WHERE g.positive_pct >= 40 AND g.positive_pct < 70) AS mixed_count,
    COUNT(*) FILTER (WHERE g.positive_pct < 40) AS negative_count,
    ROUND(AVG(g.positive_pct), 1) AS avg_sentiment
FROM games g
WHERE g.release_date IS NOT NULL
  AND g.coming_soon = FALSE
  AND g.review_count >= 10
GROUP BY 1
ORDER BY 1
LIMIT %s
```

Returns:
```json
{
  "granularity": "quarter",
  "periods": [
    {
      "period": "2024-Q1",
      "total": 387,
      "positive_count": 245,
      "mixed_count": 98,
      "negative_count": 44,
      "positive_pct": 63.3,
      "avg_sentiment": 68.1
    }
  ]
}
```

#### `find_genre_share(granularity, limit?) -> dict`

Genre proportion over time — which genres are growing or shrinking as a share
of total releases.

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
  AND g.review_count >= 10
GROUP BY 1, 2, 3
ORDER BY 1, 4 DESC
```

Compute share percentages in Python (not SQL) — divide each genre's count by
the period total. Return top N genres by total volume; bucket the rest as "Other".

Returns:
```json
{
  "granularity": "year",
  "genres": ["Action", "Indie", "RPG", "Strategy", "Adventure", "Other"],
  "periods": [
    {
      "period": "2023",
      "total": 1842,
      "shares": {"Action": 0.28, "Indie": 0.22, "RPG": 0.12, "...": "..."}
    }
  ]
}
```

#### `find_velocity_distribution(granularity, genre_slug?, limit?) -> dict`

Review velocity distribution by release cohort — how many games in each period
fall into velocity bands.

This requires `review_velocity_lifetime` on the `games` table (added by migration
`0009_game_velocity_cache.sql` from the temporal intelligence spec). If that
column is NULL for a game, fall back to computing
`review_count_english / (CURRENT_DATE - release_date)` inline.

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
WHERE g.release_date IS NOT NULL
  AND g.coming_soon = FALSE
  AND g.review_count >= 10
  AND CURRENT_DATE - g.release_date > 0
GROUP BY 1
ORDER BY 1
LIMIT %s
```

Returns:
```json
{
  "granularity": "quarter",
  "periods": [
    {
      "period": "2024-Q1",
      "total": 387,
      "velocity_under_1": 201,
      "velocity_1_10": 132,
      "velocity_10_50": 41,
      "velocity_50_plus": 13
    }
  ]
}
```

#### `find_price_trend(granularity, genre_slug?, limit?) -> dict`

Average price and free-to-play share over time.

```sql
SELECT
    DATE_TRUNC(%s, g.release_date) AS period,
    COUNT(*) AS total,
    ROUND(AVG(g.price_usd) FILTER (WHERE NOT g.is_free), 2) AS avg_paid_price,
    ROUND(AVG(g.price_usd), 2) AS avg_price_incl_free,
    COUNT(*) FILTER (WHERE g.is_free) AS free_count,
    ROUND(100.0 * COUNT(*) FILTER (WHERE g.is_free) / COUNT(*), 1) AS free_pct
FROM games g
WHERE g.release_date IS NOT NULL
  AND g.coming_soon = FALSE
  AND g.review_count >= 10
GROUP BY 1
ORDER BY 1
LIMIT %s
```

Returns:
```json
{
  "granularity": "year",
  "periods": [
    {
      "period": "2023",
      "total": 1842,
      "avg_paid_price": 18.50,
      "avg_price_incl_free": 14.20,
      "free_count": 312,
      "free_pct": 16.9
    }
  ]
}
```

#### `find_ea_trend(granularity, limit?) -> dict`

Early Access adoption and impact over time.

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
  AND g.review_count >= 10
GROUP BY 1
ORDER BY 1
LIMIT %s
```

Returns:
```json
{
  "granularity": "year",
  "periods": [
    {
      "period": "2023",
      "total_releases": 1842,
      "ea_count": 423,
      "ea_pct": 23.0,
      "ea_avg_sentiment": 74.2,
      "non_ea_avg_sentiment": 68.1
    }
  ]
}
```

Compute `ea_pct` in Python: `ea_count / total_releases * 100`.

### 2. New API endpoints

Add to `src/lambda-functions/lambda_functions/api/handler.py`.

All endpoints share a common query parameter pattern:

| Param | Type | Default | Values |
|-------|------|---------|--------|
| `granularity` | str | `"month"` | `week`, `month`, `quarter`, `year` |
| `genre` | str? | None | Genre slug filter |
| `tag` | str? | None | Tag slug filter (where applicable) |
| `limit` | int | 100 | Max periods returned (cap at 200) |

| Endpoint | Repository method | Notes |
|----------|-------------------|-------|
| `GET /api/trends/release-volume` | `find_release_volume` | Genre or tag filter |
| `GET /api/trends/sentiment` | `find_sentiment_distribution` | Genre filter |
| `GET /api/trends/genre-share` | `find_genre_share` | No genre filter (compares genres) |
| `GET /api/trends/velocity` | `find_velocity_distribution` | Genre filter; depends on `0009` migration |
| `GET /api/trends/pricing` | `find_price_trend` | Genre filter |
| `GET /api/trends/early-access` | `find_ea_trend` | No genre filter |

All endpoints validate `granularity` against the whitelist `{"week", "month", "quarter", "year"}`
and return 400 if invalid.

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
```

### 4. Frontend API client functions

Add to `frontend/lib/api.ts`:

```typescript
function getTrendReleaseVolume(params: {
  granularity?: Granularity;
  genre?: string;
  tag?: string;
  limit?: number;
}): Promise<{ granularity: string; periods: ReleaseVolumePeriod[]; summary: object }>

function getTrendSentiment(params: {
  granularity?: Granularity;
  genre?: string;
  limit?: number;
}): Promise<{ granularity: string; periods: SentimentDistPeriod[] }>

function getTrendGenreShare(params: {
  granularity?: Granularity;
  limit?: number;
}): Promise<{ granularity: string; genres: string[]; periods: GenreSharePeriod[] }>

function getTrendVelocity(params: {
  granularity?: Granularity;
  genre?: string;
  limit?: number;
}): Promise<{ granularity: string; periods: VelocityDistPeriod[] }>

function getTrendPricing(params: {
  granularity?: Granularity;
  genre?: string;
  limit?: number;
}): Promise<{ granularity: string; periods: PriceTrendPeriod[] }>

function getTrendEarlyAccess(params: {
  granularity?: Granularity;
  limit?: number;
}): Promise<{ granularity: string; periods: EATrendPeriod[] }>
```

### 5. Frontend page: `/trends`

Create `frontend/app/trends/page.tsx` (server component) and
`frontend/app/trends/TrendsClient.tsx` (client component).

#### Page layout

The page has a **shared control bar** at the top and **6 chart sections** below.

**Control bar (Pro-gated):**
- Granularity toggle: Week | Month | Quarter | Year (default: Month)
- Genre filter: dropdown populated from `getGenres()` (optional, "All Genres" default)
- Controls apply to all charts simultaneously. Changing a control re-fetches all charts.
- Free users see the control bar blurred with a "Customize with Pro →" CTA overlay
  (see free/pro pattern above). Free users always see monthly granularity, all genres.

**Chart sections** (each in a shadcn `Card`):

1. **Release Volume** — `BarChart` (Recharts)
   - X: time period, Y: release count
   - Summary stat cards above: total releases, avg per period, trend arrow
   - **Pro extra:** overlay line for avg sentiment on secondary Y axis

2. **Sentiment Distribution** — `StackedAreaChart` (Recharts), normalized to 100%
   - X: time period, Y: percentage (0–100%)
   - Three stacked areas: Positive (green), Mixed (amber), Negative (red)
   - Tooltip shows counts + percentages
   - **Pro extra:** toggle between normalized % view and raw count view

3. **Genre Share** — `StackedAreaChart` (Recharts), normalized to 100%
   - X: time period, Y: percentage share (0–100%)
   - One area per top genre, "Other" at bottom; legend with genre colors
   - Free: top 5 genres, yearly granularity (unaffected by control bar genre filter)
   - **Pro extra:** granularity toggle; choose top N genres (5/10/15) via dropdown

4. **Review Velocity** — `StackedBarChart` (Recharts)
   - X: time period, Y: game count per velocity band
   - Four stacked bars: <1/day (grey), 1–10/day (blue), 10–50/day (teal), 50+/day (green)
   - **Pro extra:** genre filter via shared control bar

5. **Pricing Trends** — `ComposedChart` (Recharts)
   - Line: avg paid price over time (left Y axis)
   - Free: price line only
   - **Pro extra:** overlay bar or area for free-to-play % (right Y axis)

6. **Early Access Trends** — `ComposedChart` (Recharts)
   - Bar: EA game count per period; line: EA % of total releases
   - Free: EA count + EA % line only
   - **Pro extra:** two additional lines — EA avg sentiment vs non-EA avg sentiment

#### Data fetching pattern

Follow the existing pattern in `GameReportClient.tsx`: server component loads
the page shell, client component fetches data in `useEffect` with loading states.

Fetch all 6 endpoints in parallel on mount and when controls change. Use
`Promise.allSettled` (like `trending/page.tsx` does) so one slow/failing chart
doesn't block the others.

#### Responsive design

- Desktop: 2-column grid for charts (3 rows of 2)
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

Add "Trends" link to `frontend/components/layout/Navbar.tsx` alongside existing
nav items. Position after "Trending" and before "Search".

---

## Migration dependency

The velocity distribution chart depends on `review_velocity_lifetime` from
migration `0009_game_velocity_cache.sql` (defined in `game-temporal-intelligence.md`).
If that migration hasn't been applied yet, the fallback SQL
(`review_count_english / NULLIF(CURRENT_DATE - release_date, 0)`) handles it.

All other charts use columns that already exist on the `games` table. No new
migration is needed for this feature.

---

## Constraints

- All SQL lives in `AnalyticsRepository` — no SQL in handlers or services
- Validate `granularity` against a whitelist before passing to `DATE_TRUNC` —
  never interpolate user input directly into SQL identifiers
- Cap `limit` at 200 periods per response to bound payload size
- Minimum `review_count >= 10` filter on all queries to exclude noise
- Exclude `coming_soon = TRUE` games from all trend queries
- All new Recharts charts use `ResponsiveContainer` for fluid sizing
- Follow existing component patterns: Tailwind styling, shadcn Card wrappers
- Type hints on all Python parameters and return types (Python 3.12)
- TypeScript types for all API response shapes
- `poetry run pytest -v` and `npm run build` must pass

---

## Files to create / modify

| File | Action |
|------|--------|
| `src/library-layer/library_layer/repositories/analytics_repo.py` | Add 6 methods |
| `src/lambda-functions/lambda_functions/api/handler.py` | Add 6 `GET /api/trends/*` endpoints |
| `frontend/lib/types.ts` | Add trend types |
| `frontend/lib/api.ts` | Add 6 API client functions |
| `frontend/app/trends/page.tsx` | Create — server component shell |
| `frontend/app/trends/TrendsClient.tsx` | Create — client component with charts + controls |
| `frontend/components/trends/TrendBarChart.tsx` | Create — generic time-series bar chart |
| `frontend/components/trends/TrendStackedArea.tsx` | Create — stacked area chart |
| `frontend/components/trends/TrendComposed.tsx` | Create — composed bar + line chart |
| `frontend/components/trends/GranularityToggle.tsx` | Create — granularity selector |
| `frontend/components/trends/ProControlsOverlay.tsx` | Create — blur wrapper + "Customize with Pro" CTA |
| `frontend/components/layout/Navbar.tsx` | Add "Trends" nav link |
| `tests/repositories/test_analytics_repo.py` | Add tests for new methods |

---

## Testing

### Backend
Add to `tests/repositories/test_analytics_repo.py`:
- Seed 10–20 games with varying `release_date`, `positive_pct`, `price_usd`,
  `is_free`, `review_count` values across multiple genres
- Seed reviews with `written_during_early_access` for EA trend tests
- Test each method with each granularity value
- Test genre/tag filter applies correctly
- Test empty results (no games matching filter)
- Test trend calculation logic (increasing/stable/decreasing)
- Test limit cap behavior

### Frontend
Add to `frontend/tests/`:
- Update `fixtures/mock-data.ts` with mock trend API responses for all 6 endpoints
- Update `fixtures/api-mock.ts` with `/api/trends/*` route mocks
- E2E test: navigate to `/trends`, verify all 6 charts render with mock data
- E2E test (`isPro = true`): change granularity toggle, verify all charts re-fetch
- E2E test (`isPro = true`): select genre filter, verify charts re-fetch with `genre` param
- E2E test (`isPro = false`): control bar has `blur-sm` class and "Customize with Pro" link is visible
- E2E test (`isPro = false`): all 6 charts still render (free view, default params)
