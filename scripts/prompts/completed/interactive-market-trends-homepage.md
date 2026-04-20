# Interactive Market Trends on Homepage — Design Spec

Make the Market Trends section on the landing page feel alive and interactive,
so first-time visitors immediately see that SteamPulse charts are tools, not
static images.

> **Status (2026-04-16):** shipped as the lightweight version described below.
> The "expand to modal" feature from the original spec was **dropped**
> — Recharts' hover-interaction perf on 100+-point datasets was unusably laggy
> (mouse-crosshair tracking drops frames), and the rest of the analytics
> roadmap calls for many interactive charts that Recharts can't support. See
> `scripts/prompts/charting-library-evaluation.md` for the migration plan
> (Apache ECharts). The expand-to-modal feature is deferred until that
> migration lands.

---

## The Problem

The previous Market Trends Preview (`MarketTrendsPreview.tsx`) showed two small
static charts — 12 months of sentiment and release volume — with a "See more"
link to `/explore`. This:

1. **Hid the data depth** — SteamPulse has trend data back to Steam's 2003 launch.
   Showing only 12 months made it look like a shallow snapshot.
2. **Felt static** — no indication the charts were interactive. A visitor
   could think they were screenshots.
3. **Missed the wow moment** — the first time a user toggles a granularity
   button, they understand this is a real analytics tool. That moment should
   happen on the landing page, not buried in `/explore`.

---

## What Changes (shipped)

### Inline, two-column cards

- **Default granularity**: `"year"` with `limit=200`. Results are filtered
  client-side to years ≥ 2003 (Steam's launch — earlier release dates come
  from classic games that got Steam ports and would mislead "Steam market
  trends" framing).
- **Granularity toggle**: `GranularityToggle` (Week / Month / Quarter / Year)
  in the section header, right-aligned. Clicking a button refetches both
  charts at the new granularity. Toggle is disabled while loading.
- **Charts stay at 180px height** — same compact preview as before.
- **"Explore trends →" link** moves below the charts, alongside a caption
  that explains the sentiment methodology honestly (see "Labels" below).
- **No expand-to-modal button.** Dropped — see status note above.

### Labels (honest framing)

The sentiment chart plots `positive_pct` (share of releases with Steam review
score ≥70%). The title and caption reflect that exactly:

- **Title**: "Positively rated releases" (not "Sentiment distribution" — the
  inline chart is a single line, not a stacked distribution).
- **Caption**: "Sentiment: share of games released in each period with Steam
  review score ≥70% (among games with ≥10 English reviews)."

The release volume chart's sub-header adapts to granularity ("Yearly releases
on Steam", "Monthly releases on Steam", etc.).

### Loading & Empty States

- **Skeleton** (`bg-secondary rounded animate-pulse` at chart height) during
  initial load and granularity changes.
- **Per-chart empty state** — if one fetch returns <2 data points after the
  Steam-era filter, that card shows "Not enough sentiment/release data for
  this view." at chart height. Not a permanent skeleton.
- **Full section hides** only if both fetches outright fail (graceful
  degradation — same pattern as the rest of the homepage).

---

## Architecture

The component converts from **server-rendered with props** to a **client
component that self-fetches**:

```
Before:  page.tsx fetches trends → passes as props → MarketTrendsPreview renders
After:   page.tsx renders <MarketTrendsPreview /> → component fetches its own data
```

Granularity changes trigger refetches — the component owns its data lifecycle.
An `AbortController` in the `useEffect` cleanup cancels stale requests when
the user rapidly switches granularities.

### API calls — go through the typed helpers

Client-side fetches use `getAnalyticsTrendSentiment` and
`getAnalyticsTrendReleaseVolume` from `frontend/lib/api.ts`, not raw `fetch()`.
These wrap `apiFetch`, which provides:

- Consistent error handling (`ApiError` class)
- Timeout (`8s` in the browser, `25s` server-side) via `AbortSignal.timeout`
- Merged abort signals when the caller passes one (cancels on granularity change)

Both helpers accept an optional `signal?: AbortSignal` as a second argument,
so the component can tie them to its own `AbortController`.

### Impact on `page.tsx`

- Removed `getAnalyticsTrendReleaseVolume` from `Promise.allSettled()`
- Removed `trendReleases` from the destructuring
- Removed `releaseTrend` variable
- Renders `<MarketTrendsPreview />` unconditionally (no props)
- **Kept** the server-side sentiment trend fetch (`limit=12`,
  `granularity=month`) — used by `IntelligenceCards.trendData` for the
  sparkline, which is a different component with different needs.

### Impact on `IntelligenceCards`

None. Still receives `trendData` from `page.tsx`'s server-side fetch.

---

## Components Reused

| Component | Path | Purpose |
|---|---|---|
| `GranularityToggle` | `components/trends/GranularityToggle.tsx` | Week/Month/Quarter/Year buttons |
| `formatPeriodLabel` | `components/trends/periodLabel.ts` | X-axis tick formatter per granularity |
| `getAnalyticsTrendSentiment` | `lib/api.ts` | Typed fetch helper (with AbortSignal support) |
| `getAnalyticsTrendReleaseVolume` | `lib/api.ts` | Typed fetch helper (with AbortSignal support) |

Inline preview charts keep raw Recharts (simpler, smaller footprint,
adequate for the ~17–200 point counts here). `TrendStackedArea` and
`TrendBarChart` are NOT used here — they were planned for the dropped
expand-to-modal feature.

---

## API

Both endpoints already supported the needed parameters — no backend changes:

```
GET /api/analytics/trends/sentiment?granularity=year&limit=200
GET /api/analytics/trends/release-volume?granularity=year&limit=200
```

Data volume at each granularity (after filtering to Steam era ≥ 2003):

- **Year**: ~23 points (2003–2026) — clean, fast
- **Quarter**: ~92 points — good detail, still snappy
- **Month**: ~200 points — API caps here; hover interaction gets heavy
- **Week**: ~200 points (API cap) — ~4 years of weeks; hover interaction is laggy

The perf ceiling on Month/Week in the inline chart is tolerable because the
chart is small (180px) and has a simple single series. It's the bigger modal
view that tips Recharts over — which is why that feature was dropped.

---

## Files Modified

| File | Change |
|---|---|
| `frontend/components/home/MarketTrendsPreview.tsx` | Rewrote as self-fetching client component: granularity state, AbortController, per-chart empty/skeleton/failed states, Steam-era filter, caption |
| `frontend/app/page.tsx` | Removed release-volume fetch and `releaseTrend` variable, render `<MarketTrendsPreview />` unconditionally |
| `frontend/lib/api.ts` | Added optional `signal?: AbortSignal` to `getAnalyticsTrendSentiment` and `getAnalyticsTrendReleaseVolume` |
| `frontend/tests/home.spec.ts` | Added 2 tests: section + toggle visibility, and "switching granularity refetches with new param" |

---

## What Stays the Same

- Two-column chart layout (sentiment left, releases right)
- Card styling (`var(--card)`, `var(--border)`, `rounded-xl`)
- Teal color for release volume, green gradient for positive sentiment line
- "Explore trends →" link (repositioned below charts, next to caption)
- Dark theme, design system, typography

---

## Success Criteria

1. **A visitor sees ~23 years of Steam data** on first load (year granularity, ≥2003)
2. **Clicking a granularity button** refetches both charts; stale requests abort cleanly on rapid clicks
3. **Honest labeling** — chart title and caption describe exactly what's plotted (`positive_pct`), not "distribution"
4. **Loading states** are smooth — skeleton pulse, no layout shift, per-chart empty states when data is thin
5. **The IntelligenceCards sparkline** still works (unaffected)
6. **Playwright coverage** — `home.spec.ts` asserts the toggle is present and that switching it triggers refetches with the new granularity
7. **No regressions** — build passes, existing tests pass

---

## Deferred (requires ECharts migration)

- **Expand-to-modal**: maximize button on each card, modal with full
  `TrendStackedArea` / `TrendBarChart` at 450px, independent granularity
  toggle, X/Escape/click-outside close, footer link.

Why deferred: Recharts hover interactivity on 100+ points is unusably slow
even with `isAnimationActive={false}` on chart elements and tooltip,
`throttleDelay={50}` on the chart container, and memoized normalization —
all applied during the attempt. The `animate` prop escape hatch we added to
`TrendStackedArea` / `TrendBarChart` remains in place (default `true`,
no-op for existing callers) so it's available when the next charting
library lands.

Pick-up plan: once Apache ECharts is in (see
`scripts/prompts/charting-library-evaluation.md`), revisit this feature.
ECharts has built-in `dataZoom` that arguably replaces the modal entirely.
