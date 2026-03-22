# Data-Driven Game Insights Prompt

## Goal

Enrich game report pages with computed statistics and visualizations derived
purely from the existing Steam data — **no LLM required**. These are
high-signal metrics for the primary audience: indie developers doing
competitive pre-launch research.

Every feature in this prompt must be computable from data already in the DB:
`review_count`, `positive_pct`, `total_positive`, `total_negative`,
`price_usd`, `is_free`, `release_date`, `achievements_total`,
`metacritic_score`, `genres`, `tags`, and the `reviews` table
(`voted_up`, `playtime_hours`, `posted_at`).

---

## Free vs Pro Philosophy

- **Free** — stats that contextualize *this* game in isolation. Quantitative,
  factual, no synthesis required.
- **Pro (blurred/gated)** — stats that require *comparison* to other games
  (benchmarks, percentiles, cohort positioning). These are what a developer
  pays for: competitive intelligence.

Never hard-remove Pro content. Blur it with a `backdrop-blur-sm` + overlay
CTA, exactly like the existing blur pattern in `GameReportClient.tsx`.

---

## Features to Build

---

### 1. Sentiment Timeline Chart (FREE)

A sparkline/area chart showing `positive_pct` by week over the game's
review history.

**New API endpoint:** `GET /api/games/{appid}/review-stats`

Returns:
```json
{
  "timeline": [
    { "week": "2024-01-01", "total": 120, "positive": 96, "pct_positive": 80 }
  ],
  "playtime_buckets": [
    { "bucket": "<2h", "reviews": 22, "pct_positive": 59 },
    { "bucket": "2-10h", "reviews": 121, "pct_positive": 68 },
    { "bucket": "10-50h", "reviews": 205, "pct_positive": 77 },
    { "bucket": "50-200h", "reviews": 212, "pct_positive": 83 },
    { "bucket": "200h+", "reviews": 1405, "pct_positive": 71 }
  ],
  "review_velocity": {
    "reviews_per_day": 12.3,
    "days_since_release": 312
  }
}
```

SQL for timeline (already verified working):
```sql
SELECT DATE_TRUNC('week', posted_at) AS week,
       COUNT(*) AS total,
       COUNT(CASE WHEN voted_up THEN 1 END) AS positive,
       ROUND(COUNT(CASE WHEN voted_up THEN 1 END)::numeric / COUNT(*) * 100) AS pct_positive
FROM reviews WHERE appid = %s
GROUP BY 1 ORDER BY 1
```

SQL for playtime buckets:
```sql
SELECT
  CASE
    WHEN playtime_hours = 0     THEN '0h'
    WHEN playtime_hours < 2     THEN '<2h'
    WHEN playtime_hours < 10    THEN '2-10h'
    WHEN playtime_hours < 50    THEN '10-50h'
    WHEN playtime_hours < 200   THEN '50-200h'
    ELSE '200h+'
  END AS bucket,
  COUNT(*) AS reviews,
  ROUND(COUNT(CASE WHEN voted_up THEN 1 END)::numeric / COUNT(*) * 100) AS pct_positive
FROM reviews WHERE appid = %s
GROUP BY 1 ORDER BY MIN(playtime_hours)
```

**Cache:** `revalidate: 3600` (same as other endpoints).

**Frontend — Sentiment Timeline:**

- Use **Recharts** (`npm install recharts`) — lightweight, React-native, no
  D3 required. Import only `AreaChart`, `Area`, `XAxis`, `YAxis`, `Tooltip`,
  `ResponsiveContainer`.
- Area chart, filled with teal at 30% opacity, line at full teal.
- X-axis: abbreviated month labels (`Jan`, `Feb`…).
- Y-axis: 0–100, show only 50 and 100 as tick marks.
- Tooltip: `"Week of Jan 15: 78% positive (120 reviews)"`.
- Height: 140px. No legend needed.
- Only render if `timeline.length >= 3`.
- "mark as client component" — add `"use client"` since Recharts uses browser
  APIs.

**Frontend — Playtime Sentiment Bar Chart:**

- Simple horizontal bars (can be pure CSS/Tailwind, no Recharts needed).
- Each bucket is a row: `[bucket label] [bar] [pct%] [(N reviews)]`.
- Bar color: green if ≥80%, amber if 60–79%, red if <60%.
- Highest-sentiment bucket gets a subtle glow/ring to draw the eye.
- Label above chart: "Sentiment by time invested" + a tooltip explaining:
  "Players who've spent more time generally rate the game differently."
- This is one of the most insightful charts — it shows whether a game is a
  "first impression" hit (high early sentiment, drops with hours) vs. a
  "slow burn" (low early, improves with hours). Show it prominently.

---

### 2. Review Velocity Card (FREE)

A small stat card showing:
- **Reviews/day** (lifetime average) — e.g. "12.3 reviews/day"
- **Days since release** — e.g. "312 days on Steam"
- **Momentum label** — computed as `reviews_last_30_days / (reviews_per_day * 30)`:
  - ≥1.2 → 🟢 "Gaining momentum"
  - 0.8–1.2 → ⚪ "Steady"
  - <0.8 → 🟡 "Slowing"

For momentum, compute from timeline data already fetched:
- `reviews_last_30_days` = sum of timeline entries in last 30 days
- `expected_30_days` = `reviews_per_day * 30`
- Ratio = `reviews_last_30_days / expected_30_days`

Display inline in the existing **Quick Stats** grid — add a 6th card
(or replace the existing grid's 5th item if space is a concern on mobile).

---

### 3. Competitive Benchmark (PRO — blurred for free users)

**What it shows:**
```
This game's sentiment ranks in the top 23% of Action games
released in 2023 with a similar price ($10–$20).
```

Three benchmark lines:
1. **Sentiment percentile** — vs. same genre + same release year + same price tier
2. **Review count percentile** — vs. same cohort ("top 18% by player count")  
3. **Cohort size** — "Compared to 847 similar games"

**Backend:**

New endpoint `GET /api/games/{appid}/benchmarks`

```python
@app.get("/api/games/{appid}/benchmarks")
async def get_benchmarks(appid: int) -> dict:
    """Compute percentile rankings vs. genre+year+price cohort."""
    game = _game_repo.find_by_appid(appid)
    if not game:
        raise HTTPException(404)
    
    # Build cohort: same primary genre + same release year + similar price
    # (±50% price, or both free, or both in $0-10/$10-25/$25+ tier)
    # Return percentiles and cohort size
```

SQL (compute cohort and percentile):
```sql
WITH cohort AS (
    SELECT g.appid, g.positive_pct, g.review_count
    FROM games g
    JOIN game_genres gg ON gg.appid = g.appid
    JOIN genres gn ON gg.genre_id = gn.id
    WHERE gn.name = %s  -- primary genre
      AND EXTRACT(YEAR FROM g.release_date) = %s  -- same year
      AND (
          (g.is_free = TRUE AND %s = TRUE)  -- both free
          OR (g.price_usd BETWEEN %s * 0.5 AND %s * 2.0)  -- ±50% price
      )
      AND g.review_count > 50  -- exclude noise
),
ranked AS (
    SELECT appid,
           PERCENT_RANK() OVER (ORDER BY positive_pct) AS sentiment_rank,
           PERCENT_RANK() OVER (ORDER BY review_count)  AS popularity_rank
    FROM cohort
)
SELECT r.sentiment_rank, r.popularity_rank, (SELECT COUNT(*) FROM cohort) AS cohort_size
FROM ranked r WHERE r.appid = %s
```

**Frontend:**

Blurred section using the same blur pattern from `GameReportClient.tsx`:
```tsx
<div className="relative">
  <div className={isPro ? "" : "blur-sm pointer-events-none select-none"}>
    {/* Benchmark content */}
  </div>
  {!isPro && <ProCTAOverlay />}
</div>
```

Display as three horizontal "benchmark bars" (like a progress bar):
- Label: "Sentiment vs. similar games"
- Bar: filled to the percentile position, with a dot showing `this game`
- Value: "Top 23%" or "Bottom 40%"

Use `var(--teal)` for fill, `var(--border)` for track. No external library —
pure CSS/Tailwind.

---

### 4. Playtime Distribution Insight (FREE with PRO teaser)

Already computed in the `review-stats` endpoint above.

**Free:** Show the full playtime sentiment chart (Section 1).

**Pro teaser:** Below the chart, add a single blurred sentence:
> "Players who played 10–50 hours rate this game 15 points higher than
> those who played under 2 hours. [What does this mean for your game?→]"

This sentence is computed (not LLM), but the *interpretation* (what the
pattern implies for the developer) is Pro. The sentence itself can be
generated with a simple rule engine:

```python
def playtime_insight(buckets: list[dict]) -> str:
    early = next((b for b in buckets if b["bucket"] in ["<2h", "2-10h"]), None)
    deep  = next((b for b in buckets if b["bucket"] in ["50-200h", "200h+"]), None)
    if not early or not deep:
        return ""
    delta = deep["pct_positive"] - early["pct_positive"]
    if delta >= 15:
        return f"Players who invest more time rate this game significantly higher (+{delta}pts) — a strong signal of a slow-burn experience that rewards patience."
    elif delta <= -15:
        return f"Early players rate this game higher than veterans (-{abs(delta)}pts) — suggesting the game has strong first impressions but may not hold up over time."
    else:
        return f"Sentiment is consistent across all playtime ranges — players feel the same way whether they've played 2 hours or 200."
```

Show this insight (blurred for free) below the playtime chart.

---

### 5. Score Context Card (FREE)

A single sentence below the `positive_pct` number giving raw context:

- `positive_pct >= 95` → "Overwhelmingly Positive — fewer than 5% of Steam
  games with 1,000+ reviews achieve this."
- `positive_pct >= 80` → "Very Positive — this puts the game in the top 30%
  of all reviewed games on Steam."
- `positive_pct >= 70` → "Mostly Positive — above the median for reviewed
  Steam games."
- `positive_pct >= 50` → "Mixed — roughly half of players recommend it."
- `positive_pct < 50` → "Mostly Negative — significant player dissatisfaction."

These percentages are approximate but directionally correct based on Steam's
distribution. Hardcode them as constants — no DB query needed.

Display in muted text (`text-xs text-muted-foreground`) directly below the
`positive_pct` display in the Quick Stats section.

---

## Where to Place These on the Page

**For unanalyzed games** (no LLM report yet):

```
[Header / Hero image]
[Quick Stats] ← add velocity card here
[Score Context Card]  ← new, after quick stats
[About / short_desc]
[Tags]
[Sentiment Timeline]  ← new section
[Playtime Chart]      ← new section
[Analysis status / CTA]
```

**For analyzed games** (full report):

```
[Header / Hero image]
[The Verdict]
[Quick Stats] ← add velocity card
[Score Context Card]  ← new
[Design Strengths]
[Gameplay Friction]
[Audience Profile]
[...]
[Sentiment Timeline]  ← new section (add after existing LLM sections)
[Playtime Chart + insight]  ← new section
[Competitive Benchmark]  ← new PRO section (blurred for free)
[Tags]
[Footer CTA]
```

---

## Implementation Notes

### Recharts

```bash
cd frontend && npm install recharts
```

Keep the import minimal — only use `AreaChart`, `Area`, `XAxis`, `YAxis`,
`Tooltip`, `ResponsiveContainer` to keep bundle size down.

Make any chart component a `"use client"` component in a separate file,
e.g. `frontend/components/game/SentimentTimeline.tsx`. The parent page
(`GameReportClient.tsx`) is already a client component so this is fine.

### New API repo method

Add `find_review_stats(appid: int) -> dict` to a new
`src/library-layer/library_layer/repositories/review_repo.py` method
(or add to existing `ReviewRepository` if it exists).

Add `find_benchmarks(appid: int, genre: str, year: int, price: float,
is_free: bool) -> dict` to `GameRepository`.

### Loading states

Both charts should render a skeleton placeholder while loading (a grey
shimmer div at the same height). Use `useState` + `useEffect` to fetch
`/api/games/{appid}/review-stats` client-side after initial page load —
this keeps SSR fast and loads charts progressively.

### Only show charts when data exists

- `SentimentTimeline` → only render if `timeline.length >= 3`
- `PlaytimeChart` → only render if total reviews in buckets >= 50
- `CompetitiveBenchmark` → only render if `cohort_size >= 10`

---

## Do NOT

- Do not install D3, Victory, Chart.js, or any other charting library —
  Recharts only.
- Do not make these charts SSR — they are client-side components.
- Do not add charts to the game *catalog/search* page — only game report page.
- Do not add a Pro paywall to the timeline or playtime chart — these are free
  insights that build trust and return visits.
- Do not show "loading" spinners — use skeleton shimmer placeholders.

---

## Playwright Tests

**Update `frontend/tests/game-report.spec.ts`** to cover the new features.
Add the following test cases (use the existing mock fixture pattern from
`frontend/tests/fixtures/`):

### Mock data additions needed

Add to `frontend/tests/fixtures/mock-data.ts`:
- `mockReviewStats` — a fixture for `GET /api/games/:appid/review-stats`
  with at least 5 weekly timeline entries and all 6 playtime buckets
- `mockBenchmarks` — a fixture for `GET /api/games/:appid/benchmarks`
  with `sentiment_rank: 0.77`, `popularity_rank: 0.45`, `cohort_size: 312`

Add to `frontend/tests/fixtures/api-mock.ts`:
- Mock handler for `GET /api/games/:appid/review-stats`
- Mock handler for `GET /api/games/:appid/benchmarks`

### New test cases for `game-report.spec.ts`

```
describe('Data-driven insights (analyzed game)')
  ✓ sentiment timeline chart renders when 3+ weeks of data present
  ✓ timeline chart does NOT render when fewer than 3 data points
  ✓ playtime chart renders all 6 buckets
  ✓ playtime chart colors: green for ≥80%, amber for 60-79%, red for <60%
  ✓ highest-sentiment playtime bucket has visual highlight
  ✓ playtime insight sentence is visible (free tier)
  ✓ competitive benchmark section is present in DOM but blurred for free users
  ✓ competitive benchmark blur is removed when isPro=true
  ✓ score context sentence appears below positive_pct in quick stats
  ✓ review velocity card shows reviews/day and momentum label

describe('Data-driven insights (unanalyzed game)')
  ✓ sentiment timeline renders for unanalyzed game if review data exists
  ✓ playtime chart renders for unanalyzed game if review data exists
  ✓ competitive benchmark section is NOT shown for unanalyzed games
    (no cohort comparison without primary genre + price data)

describe('Skeleton loading states')
  ✓ timeline skeleton placeholder visible before data loads
  ✓ playtime skeleton placeholder visible before data loads
  ✓ no layout shift when charts load in
```

### Keep existing tests passing

Do not modify or remove any existing test cases in `game-report.spec.ts`.
Run the full suite after changes: `npx playwright test` and fix any
breakage caused by new DOM structure (e.g. if a new section shifts
element selectors).

---

## Acceptance Criteria

1. `GET /api/games/{appid}/review-stats` returns timeline + playtime buckets
2. Sentiment timeline chart renders for a game with 3+ weeks of reviews
3. Playtime chart renders with correct color coding (green ≥80%, amber
   60–79%, red <60%)
4. Competitive benchmark section is visible but blurred for non-Pro users,
   with a CTA linking to `/pro`
5. All charts show skeleton placeholders while loading
6. Build passes with no TypeScript errors
7. All new Playwright tests pass against mock fixtures
8. No existing Playwright tests broken

