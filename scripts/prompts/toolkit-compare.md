# Toolkit Compare Lens — Side-by-Side Game Intelligence

## Background

The Compare lens is **the Pro conversion trigger** in SteamPulse's funnel. A free user lands on their own game's page (SEO), browses a few competitor pages, then clicks the Compare tab to line them up side-by-side against their own title. That click hits the paywall and starts the 14-day Pro trial.

Compare is the lens where SteamPulse's unique intelligence compounds: every metric we already compute per-game (Steam sentiment, promise gap, hidden gem score, audience profile, churn triggers, content depth, refund risk, review velocity, genre benchmarks) becomes exponentially more valuable when two or more games are placed next to each other. A solo indie dev's question isn't "is my game good?" — it's "is my game better or worse than *Balatro* at the same stage, and where specifically am I losing?"

The Compare lens must deliver that answer in one screen.

### Why Compare before Explorer

Compare serves the single use case that justifies the Pro subscription for the indie dev persona: *"How does my game measure up against 2–3 specific competitors I've already picked?"* Explorer (sortable mega-table) is a more analyst-y tool and can come later. Compare is the decision-making surface.

---

## Goal

Replace the `CompareLens` placeholder stub with a production-ready side-by-side comparison surface that:

1. Accepts 2–4 games via the `appids` URL param (already wired in `toolkit-state.ts`).
2. Provides a **game picker** (search autocomplete) for adding games and an × button for removing them — fully URL-synced.
3. Renders a **metrics grid** where each row is one metric and each column is one game, with the leader highlighted per row.
4. Renders a **normalized radar chart** for quick visual shape comparison across 6 axes.
5. Renders a **Promise Gap diff** (per-game `store_page_alignment` aligned into a single view).
6. Renders a **narrative "who wins where"** summary block generated client-side from the raw metric deltas (no LLM — deterministic rules).
7. Applies the **Pro gating** contract from the toolkit shell: free users can compare exactly **2 games** with a limited metric set; Pro users unlock the full metric set, up to **4 games**, the radar chart, the Promise Gap diff, and CSV export.
8. Adds a new `/compare` page (preset route) that renders `ToolkitShell` with the Compare lens active.

No backend changes. No new API endpoints. All data is assembled client-side by fanning out existing per-game endpoints in parallel.

---

## Codebase Orientation

### Existing pieces this lens builds on

- **Toolkit shell**: `frontend/components/toolkit/ToolkitShell.tsx` — already wires lens switching, filter bar, pro lock.
- **URL state**: `frontend/lib/toolkit-state.ts` — `appids` is already defined as `parseAsArrayOf(parseAsInteger, ",")`. Use the existing setter to add/remove games.
- **Lens registry**: `frontend/lib/lens-registry.ts` — `compare` lens is defined as `pro: true`, icon `Swords`.
- **Compare stub to replace**: `frontend/components/toolkit/lenses/CompareLens.tsx`
- **Pro context**: `frontend/lib/pro.tsx` — `usePro()` hook, receives `isPro: boolean` via `LensProps`.
- **API client**: `frontend/lib/api.ts`
  - `getGameReport(appid)` — full `GameReport` + game metadata (Steam sentiment, positive_pct, review counts, price, etc.)
  - `getGames({ q, limit })` — used for picker autocomplete
  - `getReviewStats(appid)` — weekly sentiment timeline + velocity
  - `getBenchmarks(appid)` — genre/tag percentile ranks (already computed server-side)
  - `getPlaytimeSentiment(appid)` — churn wall data
- **Types**: `frontend/lib/types.ts` — `Game`, `GameReport`, `StorePageAlignment`, `Benchmarks`
- **Design tokens**: see `CLAUDE.md` and `globals.css` — `--teal #2db9d4`, `--gem #c9973c`, `--positive #22c55e`, `--negative #ef4444`, `--card #141418`, `--border rgba(255,255,255,0.08)`
- **Existing reference components** (styling patterns to follow, not import directly):
  - `frontend/components/game/PromiseGap.tsx` — verdict badges, card row style
  - `frontend/components/game/CompetitiveBenchmark.tsx` — pro blur pattern
  - `frontend/app/search/SearchClient.tsx` — chip styling for removable game pills
- **Existing chart library**: the analytics dashboard already uses **Recharts**. Use `<RadarChart>` from Recharts for the radar visualization — do not add a new charting library.

### What the `compare` stub currently looks like

`frontend/components/toolkit/lenses/CompareLens.tsx` today is a placeholder "under construction" block. Replace its body entirely.

### Contract with the shell

The shell already passes `LensProps` (`{ filters: ToolkitFilters; isPro: boolean }`). The lens component reads `filters.appids` and calls the nuqs setter directly (import `useToolkitState` inside the lens) to add/remove games. Do not lift state up to the shell — the lens owns its own read/write of `appids`.

---

## Step 1: Types

Create `frontend/lib/compare-types.ts`:

```typescript
import type { Game, GameReport, Benchmarks, StorePageAlignment } from "./types";

/** Everything the Compare lens needs for one game. Assembled from parallel API calls. */
export interface CompareGameData {
  game: Game;                         // from getGameReport (returns game + report)
  report: GameReport | null;          // null if unanalyzed
  benchmarks: Benchmarks | null;      // null if unavailable
  // Derived, normalized for the radar chart — all 0..1
  radarAxes: CompareRadarAxes;
}

export interface CompareRadarAxes {
  sentiment: number;        // positive_pct / 100
  reviewVolume: number;     // log-scaled review_count, capped at 1.0
  hiddenGem: number;        // hidden_gem_score (already 0..1)
  contentDepth: number;     // report.content_depth.confidence-weighted score
  communityHealth: number;  // mapped from community_health.overall
  promiseAlignment: number; // ratio of delivered / (delivered + broken), defaults to 0.5
}

/** A single row in the metrics grid. */
export interface MetricRow {
  id: string;
  label: string;
  group: "steam" | "intelligence" | "risk" | "audience";
  /** Higher-is-better for leader highlighting. "neutral" means no winner. */
  direction: "higher" | "lower" | "neutral";
  /** Free tier visibility. */
  free: boolean;
  /** Render the cell value for one game. Returns a ReactNode so metrics can render badges, bars, etc. */
  render: (data: CompareGameData) => React.ReactNode;
  /** Sortable numeric value for leader detection. Return null to skip this cell in leader calc. */
  numeric: (data: CompareGameData) => number | null;
}
```

Add a re-export of `CompareGameData` from `frontend/lib/types.ts` is **not** needed — keep compare-only types in `compare-types.ts`.

---

## Step 2: Data Loader Hook

Create `frontend/lib/use-compare-data.ts`:

```typescript
export function useCompareData(appids: number[]): {
  data: CompareGameData[];
  loading: boolean;
  error: string | null;
}
```

### Behavior

- When `appids` changes, fetch each appid's data in parallel via `Promise.all`:
  - `getGameReport(appid)` — always
  - `getBenchmarks(appid)` — swallow errors, return null on failure (some games won't have benchmarks)
- Preserve order: `data[i]` corresponds to `appids[i]`.
- While loading, return `{ data: [], loading: true, error: null }`.
- Compute `radarAxes` inside the hook after assembly. Normalization rules:
  - `sentiment = (game.positive_pct ?? 0) / 100`
  - `reviewVolume = Math.min(1, Math.log10(Math.max(1, game.review_count ?? 1)) / 6)` — log10(1M) = 6 caps at 1.0
  - `hiddenGem = report?.hidden_gem_score ?? 0`
  - `contentDepth`: map `report.content_depth.perceived_length` × `replayability` × `value_perception` using a `{"low":0.25,"medium":0.6,"high":0.9}` lookup, average the three, fall back to 0.5 if missing
  - `communityHealth`: map `report.community_health.overall` using `{"healthy":0.9,"active":0.75,"mixed":0.5,"declining":0.25,"toxic":0.1}` (add keys as you see them in the model — fall back to 0.5)
  - `promiseAlignment`: `delivered.length / (delivered.length + broken.length)`, default 0.5 if both empty or `store_page_alignment` is null
- Cache: no need for a persistent cache — React Strict Mode dedup plus browser HTTP cache is sufficient. Do NOT add SWR or React Query.
- Cancel in-flight fetches on appid list change using an `AbortController` threaded through `apiFetch` (if `apiFetch` does not accept a signal today, add the optional `signal` param — it's a one-line change to `frontend/lib/api.ts`).

### Error handling

- If **all** games fail to load → set `error` to a human-readable message and `data: []`.
- If **some** fail, include partial data and log the failures via `console.warn`. The grid renders "—" cells for missing values.

---

## Step 3: Metric Registry

Create `frontend/lib/compare-metrics.ts` exporting `COMPARE_METRICS: MetricRow[]`.

### Metric rows (in render order)

Group: **Steam** (free tier sees all of these)

| id | label | direction | free | source |
|---|---|---|---|---|
| `positive_pct` | Positive Reviews % | higher | ✅ | `game.positive_pct` + `review_score_desc` as subtext |
| `review_count` | Total Reviews | higher | ✅ | `game.review_count` — format with `.toLocaleString()` |
| `price_usd` | Price | lower | ✅ | `game.price_usd` — render "Free" if `is_free` |
| `release_date` | Released | neutral | ✅ | `game.release_date` — show relative age ("3y ago") |

Group: **Intelligence** (mostly Pro)

| id | label | direction | free | source |
|---|---|---|---|---|
| `hidden_gem_score` | Hidden Gem Score | higher | ❌ | `report.hidden_gem_score` — render as a horizontal bar 0..1, teal fill |
| `sentiment_trend` | Sentiment Trend | higher | ✅ | `report.sentiment_trend` — arrow + label (↗ improving / → stable / ↘ declining) |
| `promise_delivered_count` | Promises Delivered | higher | ❌ | `report.store_page_alignment.promises_delivered.length` |
| `promise_broken_count` | Promises Broken | lower | ❌ | `report.store_page_alignment.promises_broken.length` |
| `hidden_strengths_count` | Hidden Strengths | higher | ❌ | `report.store_page_alignment.hidden_strengths.length` |
| `content_depth` | Content Depth | higher | ❌ | Composite of perceived_length + replayability + value_perception — render three mini pills |
| `community_health` | Community Health | higher | ❌ | `report.community_health.overall` — render as colored badge |

Group: **Risk** (Pro)

| id | label | direction | free | source |
|---|---|---|---|---|
| `refund_risk` | Refund Risk | lower | ❌ | `report.refund_signals.risk_level` — "low"/"med"/"high" badge |
| `churn_triggers_count` | Churn Triggers | lower | ❌ | `report.churn_triggers.length` |
| `technical_issues_count` | Technical Issues | lower | ❌ | `report.technical_issues.length` |

Group: **Audience** (Pro)

| id | label | direction | free | source |
|---|---|---|---|---|
| `ideal_player` | Ideal Player | neutral | ❌ | `report.audience_profile.ideal_player` (short text) |
| `casual_friendliness` | Casual Friendliness | higher | ❌ | `report.audience_profile.casual_friendliness` — badge |
| `benchmark_percentile` | Genre Percentile | higher | ❌ | `benchmarks.sentiment_percentile` (if available) |

### Leader highlighting

For each row where `direction !== "neutral"`, compute `numeric(data)` for every column, then highlight the cell whose value is the max (for `higher`) or min (for `lower`). Ties: highlight all leaders. Null values never win.

Leader cell styling:

```tsx
<td className="relative">
  <div className="absolute inset-y-1 left-0 w-0.5 rounded-full" style={{ background: "var(--teal)" }} />
  <span className="font-medium text-foreground">{value}</span>
</td>
```

Non-leader: `text-foreground/70`, no left bar.

Missing value: render `—` in `text-muted-foreground`.

---

## Step 4: Game Picker Component

Create `frontend/components/toolkit/compare/GamePicker.tsx`.

### Props

```typescript
interface GamePickerProps {
  selectedAppids: number[];
  maxGames: number;           // 2 for free, 4 for pro
  onAdd: (appid: number) => void;
  onRemove: (appid: number) => void;
  onClear: () => void;
}
```

### Behavior

- A row of selected-game pills. Each pill shows the game's header image thumbnail (40×20), name, and an × button.
- An "+ Add game" button opens an inline search. Typing debounces 250 ms then calls `getGames({ q: query, limit: 8 })`. Render up to 8 results with header image + name + positive_pct badge.
- Clicking a result calls `onAdd(appid)` and closes the search.
- If `selectedAppids.length >= maxGames`, hide the "+ Add game" button and instead show a small locked hint: *"Compare up to {maxGames} games"* — and if the user is not Pro, the hint links to `/pro` with the text "Add up to 4 games with Pro →".
- If `selectedAppids.length >= 2`, show a "Clear all" text button on the right.

### Styling

- Pills: `rounded-full` with `bg-card`, `border-border`, height 36px. Image rounds with `rounded-l-full`. Match `SearchClient.tsx` chip styling but larger for the thumbnail.
- Search popover: `rounded-xl`, `bg-popover`, `border-border`, `shadow-xl`. Show the loading state as three shimmering skeleton rows.
- Empty search results: *"No games found for '{query}'"* muted text.

### Validation

- Never allow adding an appid already in `selectedAppids`. If the user clicks a duplicate, silently no-op.
- `onAdd` / `onRemove` / `onClear` are thin wrappers that call `setAppids` from `useToolkitState` — the lens owns that setter and passes these bound callbacks down.

---

## Step 5: Metrics Grid Component

Create `frontend/components/toolkit/compare/MetricsGrid.tsx`.

### Props

```typescript
interface MetricsGridProps {
  data: CompareGameData[];    // one per column
  isPro: boolean;
}
```

### Layout

A `<table>` with:
- **Header row**: first cell empty, then one cell per game showing header image (120×56) + name + small "Go to game →" link (small text, teal, links to `/games/{appid}/{slug}`).
- **Group header rows**: a single full-width cell spanning all game columns, rendering the group name (e.g., "STEAM", "INTELLIGENCE") in font-mono uppercase, teal color, small padding, no border.
- **Metric rows**: first cell is the metric label (with a subtle info icon and tooltip explaining it — use `title` attribute; no need for a full tooltip library), then one cell per game rendered via `metric.render(data[i])`. Apply leader highlighting based on `metric.numeric`.

### Free tier gating

- Rows where `metric.free === false` are wrapped in a shared relative container grouped by Pro block. Specifically:
  - Render the free rows normally.
  - After the last free row, render the pro rows inside a single `<div className="relative">` whose inner content is blurred when `!isPro`.
  - Show one centered overlay over the pro block with: **"Unlock 12+ Pro metrics"** + upgrade button. Use the same visual language as `PromiseGap.tsx`'s overlay block.

Do NOT blur individual rows — group them into one blur region so the CTA isn't repeated.

### Responsive

- Below `md`, switch to a card-per-game stacked layout: each game becomes a vertical card that lists `metric.label: metric.render(data)` rows. Leader highlighting still applies per metric across cards (the card with the leading value shows a small "LEADS" pill next to the value).
- Alternatively, keep the table but make it horizontally scrollable (`overflow-x-auto`) on mobile and lock the first column sticky with `position: sticky; left: 0`. Pick whichever is simpler; prefer sticky-column table for implementation brevity.

### Empty state

If `data.length < 2`, render a call-to-action card: *"Add at least 2 games to compare."* with an arrow pointing up to the picker.

---

## Step 6: Radar Chart Component (Pro)

Create `frontend/components/toolkit/compare/CompareRadar.tsx`.

### Props

```typescript
interface CompareRadarProps {
  data: CompareGameData[];
}
```

### Implementation

Use Recharts `<RadarChart>` with 6 axes matching `CompareRadarAxes`:

```
Sentiment
Review Volume
Hidden Gem
Content Depth
Community
Promise Match
```

- One `<Radar>` series per game. Assign colors from a fixed palette: `["#2db9d4", "#c9973c", "#22c55e", "#a855f7"]` — teal, gem, green, purple.
- Axis domain: `[0, 1]` (data is already normalized).
- `fillOpacity: 0.15`, `strokeWidth: 2`.
- Legend below the chart: color swatch + game name.
- Height: 360 px on desktop, 280 px on mobile.
- Wrap in a card: `rounded-xl bg-card border-border p-6`.
- Section label above: "Shape Comparison" (use the existing `SectionLabel` component).

Do NOT render the radar for free users — it is entirely behind the same blur block as the pro metric rows, or as a separate pro-only block below the grid.

### Why this placement

The radar is a visual shortcut for *"where is my game uniquely weak?"* — the single most useful question after the metric grid. Placing it directly after the metric grid lets the user read the numeric delta, then zoom out to the shape.

---

## Step 7: Promise Gap Diff (Pro)

Create `frontend/components/toolkit/compare/PromiseGapDiff.tsx`.

### Props

```typescript
interface PromiseGapDiffProps {
  data: CompareGameData[];
}
```

### Behavior

- Render three horizontal sub-sections: **Delivered**, **Broken**, **Hidden Strengths**.
- Within each sub-section, render a row per game: game name (left), comma-separated list of the bullets (right, wrapping). If a game has no `store_page_alignment`, show "—".
- Each section header uses the same badge colors as `PromiseGap.tsx` (green/red/amber).
- Audience match verdict row at the bottom: each game gets its `audience_match` pill (aligned / partial / mismatch).

This is a Pro-only block — gate it with the same pattern used for the metric grid.

---

## Step 8: Who-Wins-Where Narrative

Create `frontend/components/toolkit/compare/WinsSummary.tsx`. Pure client-side, deterministic (no LLM).

### Props

```typescript
interface WinsSummaryProps {
  data: CompareGameData[];
}
```

### Behavior

- For each game, count the number of metric rows where it is a leader (from Step 3's leader calculation, reusing `COMPARE_METRICS` and filtering `direction !== "neutral"`).
- Identify the overall "leader" (most wins). Ties broken by `positive_pct`, then `review_count`.
- Render a paragraph per game:
  - **Leader**: *"{name} leads on {N}/{total} metrics — strongest on {top 3 metric labels}."*
  - **Others**: *"{name} leads on {N}/{total} — wins on {top metric labels}. Losing ground on {top 3 metrics where it has the worst value}."*
- If exactly 2 games: simpler wording — *"{A} beats {B} on: {…}. {B} beats {A} on: {…}."*

Render as a card with a `Swords` icon header and `SectionLabel` "Who Wins Where".

### Why this is worth building

LLM would be overkill and expensive. The narrative is mechanically derivable from the numeric deltas and adds a huge amount of "oh, I see it now" value. It's the takeaway the user screenshots and pastes into their Discord.

---

## Step 9: CSV Export (Pro)

Add an "Export CSV" button to the top-right of the metrics grid card. Pro-only.

- Build a CSV in-memory: first row is metric labels, subsequent rows are `game_name, val1, val2, …`. Or transposed — one row per metric, one column per game (prefer this; matches the grid layout the user just saw).
- Use `metric.numeric(data[i])` for the numeric value; fall back to a stringified render for text metrics (`ideal_player`, `sentiment_trend`).
- Trigger download via `Blob` + `URL.createObjectURL` + hidden `<a>` click. Filename: `steampulse-compare-{appid1}-{appid2}[-{appid3}][-{appid4}].csv`.

No external library. ~25 lines of code.

---

## Step 10: CompareLens Assembly

Replace the body of `frontend/components/toolkit/lenses/CompareLens.tsx` with the full lens.

### Structure

```tsx
"use client";

export function CompareLens({ filters, isPro }: LensProps) {
  const [state, setState] = useToolkitState();
  const maxGames = isPro ? 4 : 2;
  const appids = (filters.appids ?? []).slice(0, maxGames);
  const { data, loading, error } = useCompareData(appids);

  const setAppids = (next: number[]) => setState({ appids: next });
  const onAdd = (appid: number) => {
    if (appids.length >= maxGames) return;
    if (appids.includes(appid)) return;
    setAppids([...appids, appid]);
  };
  const onRemove = (appid: number) => setAppids(appids.filter((a) => a !== appid));
  const onClear = () => setAppids([]);

  return (
    <div className="space-y-8">
      <GamePicker
        selectedAppids={appids}
        maxGames={maxGames}
        onAdd={onAdd}
        onRemove={onRemove}
        onClear={onClear}
      />

      {loading && <CompareSkeleton count={appids.length} />}
      {error && <div className="text-negative">…</div>}

      {!loading && !error && data.length >= 2 && (
        <>
          <MetricsGrid data={data} isPro={isPro} />
          {isPro && <CompareRadar data={data} />}
          {isPro && <PromiseGapDiff data={data} />}
          <WinsSummary data={data} />
        </>
      )}

      {!loading && appids.length < 2 && <ComparePromptEmpty />}
    </div>
  );
}
```

Do **not** render the ProLockOverlay at the lens level — the shell already handles that for users who click the Compare tab without a Pro subscription. However, the Compare lens IS visible to free users when they are already on it (the shell passes `isPro: false` and the lens gates individual blocks). The ProLockOverlay fires only on tab-click while on another lens. This is consistent with the shell's design.

### Skeleton / Loading

`CompareSkeleton` is a small helper component inside the same file: render `count` placeholder columns with pulsing gray blocks matching the metrics grid shape. Use `animate-pulse` + `bg-card`.

### Empty prompt

`ComparePromptEmpty`: a dashed-border card saying *"Pick at least 2 games to begin. Try {linked suggestion 1} vs {linked suggestion 2}."* Hardcode two well-known popular appids as the suggestion (e.g., 440 TF2 vs 1172470 Apex Legends) — link clicks call `onAdd` for each.

---

## Step 11: `/compare` Page Route

Create `frontend/app/compare/page.tsx`:

```tsx
import type { Metadata } from "next";
import { ToolkitShell } from "@/components/toolkit/ToolkitShell";

export const metadata: Metadata = {
  title: "Compare Games — SteamPulse",
  description: "Side-by-side comparison of Steam games across sentiment, hidden gem score, promise gap, and audience fit.",
};

export default function ComparePage() {
  return (
    <main className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-4 py-8">
        <h1 className="font-serif text-2xl font-bold mb-1">Compare Games</h1>
        <p className="text-muted-foreground text-sm mb-6">
          Pick up to 4 games and line them up across every metric SteamPulse computes.
        </p>
        <ToolkitShell
          defaultLens="compare"
          visibleLenses={["compare", "sentiment", "benchmark"]}
        />
      </div>
    </main>
  );
}
```

The shell reads `appids` from the URL so `/compare?appids=440,892970` works out of the box.

### Navbar link

Add a "Compare" link to `frontend/components/layout/Navbar.tsx` desktop nav (and mobile menu), between "Toolkit" and the search bar. Use the `Swords` icon from lucide-react. Match the existing nav link styling.

---

## Step 12: Deep-link from Game Report Page

This is the **actual Pro conversion trigger**. In `frontend/app/games/[appid]/[slug]/GameReportClient.tsx`, add a small "Compare with…" button in the game header area (near the existing metadata chips). Clicking it navigates to `/compare?appids={currentAppid}` — which pre-loads the current game and invites the user to pick a competitor.

Alternatively, if the shell is already wrapping the game page with `visibleLenses: ["sentiment", "compare", "benchmark"]`, the Compare tab is already clickable — and the tab click for free users fires the `ProLockOverlay` from the shell (correct behavior). In that case, the deep-link button is redundant. **Pick one path:**

- If the game page currently wraps `GameReportClient` in `ToolkitShell` (check the output of the toolkit-shell prompt): rely on the tab. Add a small teal hint chip near the tabs: *"↑ See how this game stacks up — click Compare"*.
- If not: add an explicit button.

Check the current state of `frontend/app/games/[appid]/[slug]/page.tsx` before implementing to decide.

---

## Step 13: Playwright Tests

Update `frontend/tests/fixtures/mock-data.ts`:
- Add a second `MOCK_REPORT_2` for a different appid (e.g., 892970), with different metric values so leader highlighting is visually distinguishable. Include both good and bad cases (higher sentiment, lower hidden gem, etc.).

Update `frontend/tests/fixtures/api-mock.ts`:
- Extend `mockToolkitRoutes` to route `/api/games/{appid}/report` and `/api/games/{appid}/benchmarks` to the appropriate mock based on appid.
- Mock `/api/games?q=…` for the picker autocomplete.

Create `frontend/tests/compare.spec.ts`:

1. **Empty state** — navigate to `/compare`, verify the "Pick at least 2 games" prompt is visible and Compare tab is active.
2. **Add games via URL** — navigate to `/compare?appids=440,892970`, verify both game names render as column headers, verify at least 5 metric rows are visible.
3. **Leader highlighting** — verify the cell with the higher `positive_pct` has the leader bar (check for the data-testid `metric-leader`).
4. **Picker add** — on `/compare?appids=440`, click "+ Add game", type a query, click a result, verify the URL updates to include the new appid and the column appears.
5. **Picker remove** — on `/compare?appids=440,892970`, click the × on one pill, verify URL drops that appid and the column disappears.
6. **Free tier — max 2 games** — with `isPro=false`, verify the picker hides "+ Add game" once 2 games are selected and shows the "Add up to 4 games with Pro →" hint.
7. **Free tier — pro metric blur** — verify the pro metric rows are inside an overlay with "Unlock 12+ Pro metrics" and a link to `/pro`.
8. **Pro tier — radar visible** — with `isPro=true` (set via the test pro flag), verify the radar chart renders (check for `.recharts-radar` selector or data-testid).
9. **CSV export** — with `isPro=true`, click Export, assert the download fires (Playwright `page.waitForEvent("download")`).
10. **Who-wins-where narrative** — verify the summary block renders game names and leader counts.

Use `data-testid` attributes liberally on the lens containers, each metric row (`data-testid="metric-row-{id}"`), leader cells, the picker, and the pro gate overlay. Prefer `data-testid` over text matching for stability.

---

## File Summary

### New files

| File | Purpose |
|---|---|
| `frontend/lib/compare-types.ts` | Compare-specific types |
| `frontend/lib/use-compare-data.ts` | Parallel data loader hook |
| `frontend/lib/compare-metrics.ts` | `COMPARE_METRICS` registry |
| `frontend/components/toolkit/compare/GamePicker.tsx` | Search + pills |
| `frontend/components/toolkit/compare/MetricsGrid.tsx` | Side-by-side table |
| `frontend/components/toolkit/compare/CompareRadar.tsx` | Recharts radar (Pro) |
| `frontend/components/toolkit/compare/PromiseGapDiff.tsx` | Promise gap cross-game (Pro) |
| `frontend/components/toolkit/compare/WinsSummary.tsx` | Deterministic narrative |
| `frontend/app/compare/page.tsx` | `/compare` preset route |
| `frontend/tests/compare.spec.ts` | Playwright coverage |

### Modified files

| File | Change |
|---|---|
| `frontend/components/toolkit/lenses/CompareLens.tsx` | Replace stub with full lens |
| `frontend/components/layout/Navbar.tsx` | Add Compare nav link (desktop + mobile) |
| `frontend/lib/api.ts` | Optional: add `signal?: AbortSignal` to `apiFetch` if not present |
| `frontend/tests/fixtures/mock-data.ts` | Add `MOCK_REPORT_2` |
| `frontend/tests/fixtures/api-mock.ts` | Route multiple appids, mock picker search |
| `frontend/app/games/[appid]/[slug]/page.tsx` or `GameReportClient.tsx` | Optional deep-link hint (Step 12) |

---

## Verification

1. **Build succeeds**: `cd frontend && npm run build` — no TypeScript errors.

2. **Dev server manual check**:
   - `/compare` — empty prompt visible.
   - `/compare?appids=440,892970` — two columns render, metrics grid populated, leader bars visible on ≥ 3 rows, Who-Wins-Where block shows below the grid.
   - Set Pro flag → radar and PromiseGapDiff appear, CSV export works, picker allows up to 4 games.
   - Unset Pro flag → picker capped at 2, pro metric block blurred with single overlay CTA, radar/diff hidden.
   - Pick a third game via picker, verify URL updates to `?appids=A,B,C`.
   - Navigate from a game page via the Compare tab / deep link → current appid pre-loaded.
   - `/compare?lens=sentiment&appids=440` — the shell correctly switches to the Sentiment lens and Compare is just another tab.

3. **Playwright tests**: `cd frontend && npm run test:e2e` — all existing + new compare tests pass.

4. **Responsive check**: resize to mobile width; verify the metrics grid either scrolls with sticky first column OR reflows to stacked cards per game, and the picker pills wrap cleanly.

5. **Accessibility spot-check**: tab through the picker, tab order follows visual order; the picker popover is keyboard-dismissible (Escape); metric leader cells use semantic highlighting (not color-only — the small teal bar IS the non-color cue, which is acceptable).

---

## Non-goals

- No LLM-generated comparison prose. The deterministic WinsSummary is the narrative; adding an LLM call per compare would be slow and expensive.
- No saving compare sets. Boards/watchlists are a Pro+ feature (roadmap #19).
- No cross-compare of arbitrary catalog aggregates (tag vs tag). That's Market Map (roadmap #14).
- No re-implementing filter bar behaviors — the shell's filter bar is still visible above the lens, but it does NOT affect the Compare lens. The lens ignores `filters.genre`, `filters.tag`, etc. Only `filters.appids` is read. Leave the filter bar visible for consistency; consider hiding it entirely if it creates user confusion (optional UX judgment call — default to showing it).
