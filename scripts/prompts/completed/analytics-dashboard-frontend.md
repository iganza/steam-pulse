# Analytics Dashboard Frontend — Trends Lens

## Background

The `/analytics` page already exists and renders `AnalyticsClient.tsx` — a 9-chart
catalog-wide dashboard backed by `getAnalyticsTrend*()` API helpers. It has its own
ad-hoc control bar (granularity toggle + genre/tag dropdowns + game-type selector).

The Toolkit Shell (prompt #5, completed) has since landed. It introduced:

- A shared `ToolkitShell` with a global `FilterBar` (genre, tag, price tier, year,
  developer, sentiment, min reviews, deck, has_analysis, sort, appids) backed by
  `useToolkitState()` (URL-encoded via `nuqs`).
- A `LensTabSwitcher` and a registry of six lenses. The Trends lens is currently a
  placeholder stub (`frontend/components/toolkit/lenses/TrendsLens.tsx`).
- An integration on `/analytics` that wraps `AnalyticsClient` as the `trends` lens
  via the `lensContent` override. This was a temporary scaffold — `AnalyticsClient`
  still owns its own filter state and ignores the shell's filter bar.

This prompt finishes the job: turn the Trends lens into a **first-class lens** that
reads filters from the shared toolkit state, drop the duplicate ad-hoc controls,
and remove the override on the `/analytics` page so it becomes a true lens preset.

### Why this matters

Per the architecture (`20260331091542-projects_steam_pulse_game_analysis_talks.org`),
*filters persist across lens switches*. A user defines a segment once (e.g.
"Roguelike + Co-op + Under $20 + 500+ reviews") and rotates lenses to interrogate
it from different angles. Today the analytics page breaks that contract: changing
the genre in the filter bar does nothing to the charts, because `AnalyticsClient`
reads its own local `genre` state. We must close this gap before any other lens
ships, or the toolkit's central promise is broken on its highest-traffic page.

### What "Trends" means in the lens taxonomy

From the org doc (line 1048):
> Trends — Time-series view. Pick a metric, see it over time for filtered games or
> aggregated across the segment.

Translation for this prompt: **the 9 existing charts ARE the Trends lens**. They
already answer "how is this segment evolving over time?" The work is to make them
respect the segment defined by the toolkit filter bar instead of duplicating
controls inline. The lens itself adds *only* time-axis controls (granularity,
chart-specific toggles) — every "what" filter (genre/tag/price/year/etc.) lives
in the shared filter bar.

---

## Goal

1. Rewrite `frontend/components/toolkit/lenses/TrendsLens.tsx` so it renders the
   9-chart dashboard, sourcing every filter from `useToolkitState()`.
2. Move time-axis-only controls (granularity, sentiment normalized toggle, genre
   share top-N, release-volume game type) into a **lens-local control strip** that
   sits inside the lens content area, above the charts. These are *display
   parameters*, not segment filters, and stay local to the Trends lens.
3. Delete `frontend/app/analytics/AnalyticsClient.tsx` (or reduce it to a thin
   re-export of `TrendsLens` if any test imports it directly — check first).
4. Update `frontend/app/analytics/page.tsx` to render `ToolkitShell` *without* a
   `lensContent` override for trends — the shell will pick up the real lens from
   the registry / `LensRenderer`.
5. Ensure the genre page and tag page presets (which lock genre/tag and may show
   the Trends tab) get a working time-series view filtered to that genre/tag with
   no extra wiring.

No backend changes. No new API endpoints. No new charts (those are scoped for the
post-launch `toolkit-trends.md` Phase 2B prompt).

---

## Codebase Orientation

### Key existing files

- `frontend/app/analytics/page.tsx` — server component, currently wraps `AnalyticsClient` as `trends` lens override inside `ToolkitShell`
- `frontend/app/analytics/AnalyticsClient.tsx` — 458 lines, owns local filter state, renders 9 charts. **Source material for the new lens.**
- `frontend/components/toolkit/lenses/TrendsLens.tsx` — current placeholder stub
- `frontend/components/toolkit/ToolkitShell.tsx` — shell, accepts `lensContent` overrides
- `frontend/lib/toolkit-state.ts` — `useToolkitState()`, `ToolkitFilters` type, `LensProps` interface (`{ filters, isPro }`)
- `frontend/lib/lens-registry.ts` — `LENS_REGISTRY`, `LensRenderer` switch
- `frontend/lib/api.ts` — `getAnalyticsTrend*()` helpers (already accept `genre`, `tag`, `granularity`, `type`, `top_n` params)
- `frontend/components/trends/` — `GranularityToggle`, `TrendBarChart`, `TrendStackedArea`, `TrendStackedBarChart`, `TrendComposed`. **Reuse as-is.**
- `frontend/lib/types.ts` — `Granularity`, `ReleaseVolumePeriod`, `SentimentDistPeriod`, etc.
- `frontend/lib/pro.tsx` — `usePro()` hook
- `frontend/tests/fixtures/api-mock.ts` — `mockToolkitRoutes()`, plus existing analytics mocks

### Existing API param surface (do NOT change)

```ts
getAnalyticsTrendReleaseVolume({ granularity, genre?, tag?, type? })
getAnalyticsTrendSentiment       ({ granularity, genre? })
getAnalyticsTrendGenreShare      ({ granularity, top_n })
getAnalyticsTrendVelocity        ({ granularity, genre? })
getAnalyticsTrendPricing         ({ granularity, genre? })
getAnalyticsTrendEarlyAccess     ({ granularity })
getAnalyticsTrendPlatforms       ({ granularity, genre? })
getAnalyticsTrendEngagement      ({ granularity, genre? })
getAnalyticsTrendCategories      ({ granularity, top_n })
```

These are catalog-wide trend endpoints. They accept genre/tag passthrough but
**not** the full filter set (price, year, sentiment, min_reviews, etc.). For now
the Trends lens passes only the params each endpoint understands; unsupported
filters are silently ignored at this layer (the FilterBar still shows them, and
the Explorer / Market Map lenses will honor them when those land). Add a small
"Filtered to:" caption above the chart grid that lists the *active* filters and
notes which are applied vs. which are ignored by Trends, so the user is not
misled.

---

## Step 1: TrendsLens — Lens-Local Display Controls

Create a small `TrendsLensControls` sub-component (inline or in
`frontend/components/toolkit/lenses/TrendsLensControls.tsx`) that owns *only*
display state — never segment state. State lives in `useState`, **not** in URL
params (these are lens-internal display preferences and would pollute the URL):

| Control | Type | Default | Free | Pro | Notes |
|---|---|---|---|---|---|
| Granularity | `GranularityToggle` (week/month/quarter/year) | `month` | locked to `month` | unlocked | Reuse existing component |
| Sentiment normalized | toggle (`% Share` / `Raw`) | `% Share` | locked | unlocked | Per-chart, lives on Sentiment card |
| Genre Share top-N | `5 / 10 / 15` | `5` | locked to 5 | unlocked | Per-chart, lives on Genre Share card |
| Release Volume game type | `game / dlc / all` | `game` | locked to `game` | unlocked | Per-chart, lives on Release Volume card |

**Removed from the lens:** the inline genre and tag dropdowns from
`AnalyticsClient.tsx`. These now come from the global filter bar (genre and tag
are already filter-bar fields). Do NOT keep a duplicate.

Free users see the same Pro lock pattern that exists today: the control strip is
blurred with a "Customize with Pro →" CTA overlay. Lift the existing pattern
verbatim from `AnalyticsClient.tsx` lines 152–180.

---

## Step 2: TrendsLens — Wire to Toolkit Filters

Rewrite `frontend/components/toolkit/lenses/TrendsLens.tsx`:

```tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import type { LensProps } from "@/lib/toolkit-state";
import type { Granularity } from "@/lib/types";
// ... chart + API imports lifted from AnalyticsClient

export function TrendsLens({ filters, isPro }: LensProps) {
  // Lens-local display state
  const [granularity, setGranularity] = useState<Granularity>("month");
  const [sentimentNormalized, setSentimentNormalized] = useState(true);
  const [genreShareTopN, setGenreShareTopN] = useState(5);
  const [gameType, setGameType] = useState<"game" | "dlc" | "all">("game");

  // Segment filters come from props
  const genreSlug = filters.genre || undefined;
  const tagSlug   = filters.tag   || undefined;

  // ...rest of fetchAll() lifted from AnalyticsClient, replacing local genre/tag
  // state with genreSlug/tagSlug
}
```

`fetchAll` re-runs whenever any of:
- `filters.genre`, `filters.tag`
- `granularity`, `gameType`, `genreShareTopN`
- `isPro`

change. Use `useCallback` + `useEffect` exactly as `AnalyticsClient` does today —
no behavior change, just the source of `genre`/`tag` swapped.

### Filter awareness banner

At the top of the lens content (above the control strip), render a one-line
caption summarizing the active segment and which filters are honored:

```tsx
<p className="text-xs font-mono text-muted-foreground mb-3">
  Trends for: {summarizeSegment(filters)}
  {hasIgnoredFilters(filters) && (
    <span className="ml-2 text-foreground/40">
      ({ignoredFilterNames(filters).join(", ")} not yet supported in Trends — try Explorer)
    </span>
  )}
</p>
```

Helper functions live inside the lens file. The "ignored" set is everything
except `genre` and `tag` (today). When the post-launch trends prompt expands the
backend, this caption shrinks automatically.

If `filters.appids` has length > 0 the caption should say
"Trends are catalog-wide — game selection ignored. Use Sentiment Drill for a
single-game timeline." (Trends does not currently scope to specific appids.)

### Charts — lift verbatim

Copy the entire chart grid from `AnalyticsClient.tsx` lines 187–453 into the new
lens body unchanged. The only diffs are:

- Replace local `genre` / `tag` references with `genreSlug` / `tagSlug` from
  toolkit filters.
- Move the granularity toggle / genre dropdown row out (it's gone — replaced by
  the lens control strip + global filter bar).
- Per-chart Pro controls (sentiment normalized, top-N, gameType) move into the
  control strip section and remain wired the same way.

Result: identical visuals, but the lens is now a pure function of
`(filters, granularity, isPro, lens-local display state)`.

### Loading + empty states

Preserve the existing `loading` boolean and the engagement-data empty-state card.
Do not regress any existing behavior.

---

## Step 3: Slim Down `/analytics/page.tsx`

Open `frontend/app/analytics/page.tsx`. Today it passes `lensContent={{ trends: <AnalyticsClient /> }}`
to `ToolkitShell`. Remove that override. The shell will then render the real
`TrendsLens` from the lens registry / `LensRenderer`.

Resulting shape:

```tsx
<main className="max-w-6xl mx-auto px-4 py-8">
  <h1 className="text-2xl font-bold mb-1">Analytics</h1>
  <p className="text-muted-foreground text-sm mb-6">
    Catalog-wide trends across the Steam ecosystem. Add filters above to scope.
  </p>
  <ToolkitShell
    defaultLens="trends"
    visibleLenses={["trends", "market-map", "explorer"]}
  />
</main>
```

Keep the existing `metadata` export, JSON-LD if any, and any SSR data fetches
unchanged.

---

## Step 4: Delete (or Reduce) `AnalyticsClient.tsx`

Search for imports of `AnalyticsClient` across the repo:

```bash
grep -rn "AnalyticsClient" frontend/
```

- If the only consumer is `app/analytics/page.tsx` (which we just updated): delete the file.
- If a Playwright test or another page imports it: leave the file as a 1-line re-export `export { TrendsLens as AnalyticsClient } from "@/components/toolkit/lenses/TrendsLens";` — but prefer updating the consumer to use the lens directly.

---

## Step 5: Genre & Tag Page Presets

`/genre/[slug]` and `/tag/[slug]` already render `ToolkitShell` with locked filters
(`{ genre: slug }` / `{ tag: slug }`) and `visibleLenses` that include `trends`.
After this change, clicking the **Trends** tab on those pages will Just Work —
the lens reads `filters.genre` / `filters.tag` and the API helpers already accept
those params. No code changes needed beyond verifying it on the dev server.

---

## Step 6: LensRenderer Wiring

`frontend/components/toolkit/LensRenderer.tsx` already maps `"trends"` → `<TrendsLens />`
from the stub import. Confirm the import path still resolves; the file path is
unchanged (`frontend/components/toolkit/lenses/TrendsLens.tsx`). No edit expected.

---

## Step 7: Tests

### Update existing analytics tests

Run `npm run test:e2e -- analytics` (or whatever suite covers `/analytics`) and
fix any selectors that broke when `AnalyticsClient.tsx`'s control bar was removed.
Tests that asserted on the inline genre dropdown should now drive selection via
the global filter bar's "Add Filter → Genre" popover instead.

### New tests in `frontend/tests/toolkit.spec.ts` (or a new `trends-lens.spec.ts`)

1. **Trends lens renders 9 charts** — navigate to `/analytics`, verify 9 chart
   cards are visible by their titles.
2. **Genre filter propagation** — on `/analytics`, add a "Genre: Action" filter via
   the FilterBar popover. Verify the Trends API helpers were called with
   `genre=action` (intercept network requests via Playwright `page.route`).
3. **Granularity toggle (Pro only)** — with `NEXT_PUBLIC_PRO_ENABLED=true`,
   click `quarter` on the granularity toggle. Verify API calls use `granularity=quarter`.
4. **Free user lock** — without Pro, the granularity toggle and per-chart Pro
   controls are blurred and a CTA overlay is visible.
5. **Genre page integration** — navigate to `/genre/action`, click the Trends tab,
   verify the Trends lens renders and the locked genre chip is in the filter bar.
6. **Ignored filter caption** — add a price tier filter on `/analytics`. Verify
   the "not yet supported in Trends — try Explorer" caption appears.

### Mocks

Existing analytics endpoint mocks in `tests/fixtures/api-mock.ts` should be
sufficient. If tests need to assert on query string params, add a route handler
that captures requests and verifies the URL.

---

## File Summary

### New files

| File | Purpose |
|------|---------|
| (none required — `TrendsLensControls` may live inline in `TrendsLens.tsx`) | |

### Modified files

| File | Change |
|------|--------|
| `frontend/components/toolkit/lenses/TrendsLens.tsx` | Replace stub with real 9-chart implementation reading from `LensProps.filters` |
| `frontend/app/analytics/page.tsx` | Drop the `lensContent` override; let the shell render `TrendsLens` from the registry |
| `frontend/tests/toolkit.spec.ts` *(or new `trends-lens.spec.ts`)* | New tests for the lens |
| `frontend/tests/fixtures/api-mock.ts` | Add mocks for analytics trend endpoints if not already present |

### Deleted files

| File | Reason |
|------|--------|
| `frontend/app/analytics/AnalyticsClient.tsx` | Functionality folded into `TrendsLens` |

---

## Verification

1. **Build**: `cd frontend && npm run build` — no TypeScript errors.

2. **Dev server walk-through**:
   - `/analytics` — 9 charts visible. Granularity toggle and other Pro controls
     appear (locked for free users).
   - Add a Genre filter via the FilterBar → all charts re-fetch with the genre.
   - Add a Tag filter → release volume chart re-fetches with the tag.
   - Add a Price Tier filter → "not yet supported" caption appears; charts
     remain showing genre/tag scope.
   - `/genre/action` → click Trends tab → see catalog charts scoped to Action
     with the locked genre chip.
   - `/tag/roguelike` → click Trends tab → same, scoped to roguelike.
   - Switch from Trends to another lens and back — the granularity / display
     state may reset (it's `useState`, that's fine), but the segment filters
     persist via URL.
   - URL refresh round-trip: `/analytics?genre=action&lens=trends` restores both
     the active lens and the genre filter.

3. **Pro gating**:
   - Free user: granularity locked to `month`, per-chart Pro controls hidden or
     blurred behind CTA, charts still render at the free defaults that were used
     before this prompt.
   - Pro user: full control of granularity + per-chart toggles.

4. **Playwright**: `cd frontend && npm run test:e2e` — all existing tests pass,
   new Trends lens tests pass.

5. **No regressions** in `/games/[appid]/[slug]`, `/genre/[slug]`, `/tag/[slug]`,
   `/toolkit`, or `/search`.
