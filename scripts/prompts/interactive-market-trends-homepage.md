# Interactive Market Trends on Homepage — Design Spec

Make the Market Trends section on the landing page feel alive and interactive,
so first-time visitors immediately see that SteamPulse charts are tools, not
static images.

---

## The Problem

The current Market Trends Preview (`MarketTrendsPreview.tsx`) shows two small
static charts — 12 months of sentiment distribution and release volume — with
a "See more" link to `/explore`. This:

1. **Hides the data depth** — SteamPulse has trend data back to ~2008. Showing
   only 12 months makes it look like a shallow snapshot.
2. **Feels static** — there's no indication the charts are interactive. A
   visitor could think these are screenshots.
3. **Misses the wow moment** — the first time a user toggles a granularity
   button or expands a chart, they understand this is a real analytics tool.
   That moment should happen on the landing page, not buried in `/explore`.

---

## What Changes

### Default View (inline, two-column cards)

- **Granularity**: Default to `"year"` with `limit=200` — shows the full Steam
  catalog history (~2008–present) in ~17 clean data points.
- **Granularity toggle**: Add the existing `GranularityToggle` component
  (Week / Month / Quarter / Year buttons) in the section header, right-aligned.
  Clicking a button refetches both charts at the new granularity.
- **Expand button**: Each chart card gets a small maximize icon (top-right
  corner, `Maximize2` from lucide-react). Clicking it opens the chart in an
  expanded modal.
- **"Explore trends →" link**: Moves below the charts (currently in the
  section header).
- **Charts stay at 180px height** — same compact preview as today.

### Expanded Modal

When a user clicks the expand icon on either chart:

- **Dark overlay** + centered modal (`max-w-4xl`, `rounded-xl`, card background)
- **Modal header**: Chart title + `GranularityToggle` (independent of inline)
- **Chart**: 450px height, using the full `TrendStackedArea` (sentiment) or
  `TrendBarChart` (release volume) components — with proper tooltips, legends,
  and period formatting.
- **Close**: X button top-right + click-outside + Escape key
- **Footer**: "Explore all trends →" link to `/explore`

### Loading & Empty States

- **Skeleton**: `bg-secondary rounded animate-pulse` at chart height during
  initial load and granularity changes.
- **Empty**: If both trend fetches fail, the entire section hides (graceful
  degradation — same pattern as the rest of the homepage).

---

## Architecture

The component converts from **server-rendered with props** to a **client
component that self-fetches**:

```
Before:  page.tsx fetches trends → passes as props → MarketTrendsPreview renders
After:   page.tsx renders <MarketTrendsPreview /> → component fetches its own data
```

This is necessary because granularity changes trigger refetches — the component
needs to own its data lifecycle.

### Impact on `page.tsx`

- Remove `trendSentiment` and `trendReleases` from `Promise.allSettled()`
- Remove `sentimentTrend` / `releaseTrend` variables
- Render `<MarketTrendsPreview />` unconditionally (no props, no conditional)
- **Keep** the server-side sentiment trend fetch (`limit=12`, `granularity=month`)
  for the `IntelligenceCards` sparkline — that's a different component with
  different needs.

### Impact on `IntelligenceCards`

None. The "Market Intelligence" card's mini sparkline still receives `trendData`
from `page.tsx`'s server-side fetch. Only `MarketTrendsPreview` changes.

---

## Components to Reuse

| Component | Path | Purpose |
|---|---|---|
| `GranularityToggle` | `components/trends/GranularityToggle.tsx` | Week/Month/Quarter/Year buttons |
| `formatPeriodLabel` | `components/trends/periodLabel.ts` | X-axis tick formatter per granularity |
| `TrendStackedArea` | `components/trends/TrendStackedArea.tsx` | Sentiment chart in expanded modal |
| `TrendBarChart` | `components/trends/TrendBarChart.tsx` | Release volume chart in expanded modal |

Inline preview charts keep raw Recharts (simpler, smaller footprint). Expanded
modal uses the full trend components (richer tooltips, legends, formatting).

---

## API

Both endpoints already support the needed parameters — no backend changes:

```
GET /api/analytics/trends/sentiment?granularity=year&limit=200
GET /api/analytics/trends/release-volume?granularity=year&limit=200
```

Data volume at each granularity:
- **Year**: ~17 points (2008–2025) — clean, fast
- **Quarter**: ~68 points — good detail
- **Month**: ~200 points — maximum detail, still performant in Recharts
- **Week**: ~900 points — API caps at 200, so effectively ~4 years of weeks

---

## Files to Modify

| File | Change |
|---|---|
| `frontend/components/home/MarketTrendsPreview.tsx` | Rewrite: self-fetching, granularity state, expand modal |
| `frontend/app/page.tsx` | Remove trend fetches from `Promise.allSettled()`, render component unconditionally |

---

## What Stays the Same

- Two-column chart layout (sentiment left, releases right)
- Card styling (`var(--card)`, `var(--border)`, `rounded-xl`)
- Teal color for positive data, green for positive sentiment
- "Explore trends →" link (repositioned below charts)
- Dark theme, design system, typography

---

## Success Criteria

1. **A visitor sees ~17 years of Steam data** on first load (year granularity)
2. **Clicking a granularity button** updates both charts within ~1s
3. **Clicking the expand icon** opens a large, detailed chart in a modal
4. **The modal has its own granularity toggle** — users can drill into monthly
   data from the expanded view
5. **Loading states** are smooth — skeleton pulse, no layout shift
6. **The IntelligenceCards sparkline** still works (unaffected)
7. **No regressions** — build passes, existing tests pass
