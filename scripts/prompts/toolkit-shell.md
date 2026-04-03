# SteamPulse Toolkit Shell — Shared Layout, Filter Bar, Lens Tabs, URL State

## Background

SteamPulse's core UI philosophy is **every page is a pre-configured toolkit state.** The same shell layout renders everywhere — a persistent filter bar at the top, a row of lens tabs below it, and a content area that renders the active lens. Existing pages (`/games/[appid]/[slug]`, `/genre/[slug]`, `/tag/[slug]`, `/analytics`) become presets — they set initial filters and a default lens, but the shell infrastructure is identical.

```
/genre/action                →  filter(genre=action)  + Market Map lens
/games/440/team-fortress-2   →  filter(appid=440)     + Sentiment Drill lens
/tag/roguelike               →  filter(tag=roguelike) + Explorer lens
/analytics                   →  no filter             + Trends lens
/compare?games=440,892970    →  filter(appids=[...])  + Compare lens
/toolkit                     →  no filter             + Sentiment Drill lens (blank canvas)
```

URL encodes all state: `?genre=action&lens=compare&appids=440,892970&price_tier=under_10`

Free users get the default lens pre-selected. Pro users can switch lenses, add filters, export.

```
[Sentiment Drill ✓] [Compare 🔒 Pro] [Explorer 🔒 Pro] [Market Map 🔒 Pro]
```

This prompt builds the **shell only** — the container, filter bar, lens tab switcher, URL state management, and pro-lock pattern. Individual lens implementations are separate prompts (items 6–10 on the roadmap). This prompt creates placeholder stubs for every lens so the shell is fully navigable on completion.

### Why this must come first

Every subsequent frontend prompt (Store Page Alignment, Analytics Dashboard Frontend, Compare Lens, etc.) plugs into this shell as a lens. Without the shell, each prompt would reinvent filter state, tab switching, and pro gating. Building the shell first gives all future prompts a stable contract to implement against.

---

## Goal

Build a `ToolkitShell` client component that provides:

1. A composable **FilterBar** with add/remove filter chips, a live matching-game count badge, and a "Clear all" action.
2. A **LensTabSwitcher** with free and pro lens tabs, lock icons on pro lenses, and active-tab styling.
3. **URL state** for all filters and the active lens, using the `nuqs` library for type-safe URL search param management.
4. A **Pro lock pattern** that shows a blur overlay with an upgrade CTA when a free user clicks a pro lens.
5. **Lens placeholder stubs** for all six lenses (Sentiment Drill, Compare, Explorer, Benchmark, Market Map, Trends).
6. A new `/toolkit` page — the blank-canvas entry point.
7. Integration into existing pages as presets, without breaking any current page or test.

No backend changes. No new API endpoints. The shell orchestrates existing client-side state and existing API functions.

---

## Codebase Orientation

### File Layout

- **Root layout**: `frontend/app/layout.tsx` — mounts `ProProvider`, `Navbar`, fonts. **NuqsAdapter must be added here.**
- **Pro context**: `frontend/lib/pro.tsx` — `ProProvider` wrapping the app, `usePro()` hook returns boolean.
- **API client**: `frontend/lib/api.ts` — `apiFetch<T>()`, plus `getGames()` (already supports all filter params: `q`, `genre`, `tag`, `developer`, `year_from`, `year_to`, `min_reviews`, `has_analysis`, `sentiment`, `price_tier`, `deck`, `sort`, `limit`, `offset`), `getGenres()`, `getTopTags()`.
- **Types**: `frontend/lib/types.ts` — `Game`, `Genre`, `Tag`, `GameReport`, `Granularity`, etc.
- **Search/filter page**: `frontend/app/search/SearchClient.tsx` — existing filter sidebar with URL state via `useSearchParams()` + `router.push()`. **Primary reference for filter UX patterns and chip styling.**
- **Game report page**: `frontend/app/games/[appid]/[slug]/page.tsx` (server, SSR + JSON-LD) + `GameReportClient.tsx` (client, receives report + game data as props)
- **Genre page**: `frontend/app/genre/[slug]/page.tsx` — server component with SSR data, renders top picks + market intelligence + SearchClient
- **Tag page**: `frontend/app/tag/[slug]/page.tsx` — same pattern as genre
- **Analytics page**: `frontend/app/analytics/page.tsx` (server) + `AnalyticsClient.tsx` (client)
- **Navbar**: `frontend/components/layout/Navbar.tsx` — sticky top-0 z-50, desktop links: Browse, Hidden Gems, New Releases, Trending, Analytics, For Developers
- **UI primitives**: `frontend/components/ui/` — `card.tsx`, `badge.tsx`, `button.tsx`, `dialog.tsx`
- **Playwright tests**: `frontend/tests/` — mocks in `tests/fixtures/api-mock.ts` and `tests/fixtures/mock-data.ts`

### Design Tokens (from `globals.css`)

```css
--background: #0c0c0f;
--foreground: #ededea;
--card: #141418;
--popover: #1a1a1f;
--border: rgba(255,255,255,0.08);
--teal: #2db9d4;
--gem: #c9973c;
--positive: #22c55e;
--negative: #ef4444;
--radius: 0.5rem;
--font-playfair: /* serif headings */
--font-syne: /* sans-serif body */
--font-jetbrains: /* mono labels/numbers */
```

### Existing URL State Pattern (to be replaced by nuqs)

```typescript
// SearchClient.tsx reads from URL
const searchParams = useSearchParams();
const genre = searchParams.get("genre") ?? "";
// Updates via router.push
function updateParams(updates: Record<string, string>) {
  const params = new URLSearchParams(searchParams.toString());
  for (const [k, v] of Object.entries(updates)) {
    if (v) params.set(k, v); else params.delete(k);
  }
  router.push(`?${params.toString()}`, { scroll: false });
}
```

### Existing Pro Gating Pattern

```typescript
// lib/pro.tsx
const isPro = usePro(); // returns boolean from ProContext

// Leaf components receive isPro as prop and conditionally blur/lock:
<div className={isPro ? "" : "blur-sm pointer-events-none select-none"}>
  {content}
</div>
{!isPro && (
  <div className="absolute inset-0 flex items-center justify-center">
    <Link href="/pro">Customize with Pro →</Link>
  </div>
)}
```

### Existing Navbar Link Pattern

```tsx
<Link
  href="/analytics"
  className="flex items-center gap-1 px-3 py-1.5 rounded text-sm font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
>
  <BarChart3 className="w-3 h-3" /> Analytics
</Link>
```

### Existing Card/Section Styling

```tsx
<div className="p-6 rounded-xl" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
```

### Existing Filter Chip Styling (from SearchClient.tsx)

```tsx
<button className="flex items-center gap-1 px-2.5 py-1 rounded-full text-sm font-mono border border-border text-foreground/70 hover:text-foreground transition-colors">
  {label} <X className="w-3 h-3" />
</button>
```

---

## Step 1: Install nuqs

```bash
cd frontend && npm install nuqs
```

`nuqs` provides `useQueryState()` and `useQueryStates()` hooks that sync React state with URL search params. It works natively with Next.js App Router and handles serialization, parsing, shallow routing, and history management.

---

## Step 2: Add NuqsAdapter to Root Layout

In `frontend/app/layout.tsx`, import and mount the `NuqsAdapter` from `nuqs/adapters/next/app`. Wrap `{children}` with it, inside the existing `ProProvider`:

```tsx
import { NuqsAdapter } from "nuqs/adapters/next/app";

// In the return:
<ProProvider isPro={isPro}>
  <Navbar />
  <NuqsAdapter>{children}</NuqsAdapter>
</ProProvider>
```

This enables `nuqs` hooks in all client components throughout the app.

---

## Step 3: URL State Schema — `frontend/lib/toolkit-state.ts`

Create a single file that defines the URL param schema for the entire toolkit. Every filter and the lens selection is defined here.

### Lens IDs

```typescript
export const LENS_IDS = ["sentiment", "compare", "explorer", "benchmark", "market-map", "trends"] as const;
export type LensId = (typeof LENS_IDS)[number];
```

### URL Parameters

Use `nuqs` parsers to define each param:

| Param | nuqs Parser | Default | Notes |
|---|---|---|---|
| `lens` | `parseAsStringLiteral(LENS_IDS)` | `"sentiment"` | Active lens tab |
| `genre` | `parseAsString` | `""` | Genre slug |
| `tag` | `parseAsString` | `""` | Tag slug |
| `q` | `parseAsString` | `""` | Search query |
| `developer` | `parseAsString` | `""` | Developer slug |
| `sentiment` | `parseAsStringLiteral(["positive","mixed","negative"])` | `null` | Sentiment bucket |
| `price_tier` | `parseAsStringLiteral(["free","under_10","10_to_20","over_20"])` | `null` | Price bucket |
| `min_reviews` | `parseAsInteger` | `null` | Minimum review count |
| `year_from` | `parseAsInteger` | `null` | Release year start |
| `year_to` | `parseAsInteger` | `null` | Release year end |
| `deck` | `parseAsString` | `""` | Deck compat filter |
| `has_analysis` | `parseAsBoolean` | `null` | Only analyzed games |
| `sort` | `parseAsString` | `"review_count"` | Sort field |
| `appids` | `parseAsArrayOf(parseAsInteger, ",")` | `[]` | Selected game IDs (compare, single-game preset) |

### Exports

- `toolkitParsers` — the parsers object for use with `useQueryStates()`
- `useToolkitState()` — a convenience hook wrapping `useQueryStates(toolkitParsers)` that returns the typed state and setters
- `ToolkitFilters` — TypeScript type derived from the parser output (the filter values only, excluding `lens`)

Configure nuqs with `history: "push"` so back/forward navigation works naturally between filter states.

---

## Step 4: Lens Registry — `frontend/lib/lens-registry.ts`

Define a registry mapping each `LensId` to its metadata:

```typescript
export interface LensDefinition {
  id: LensId;
  label: string;        // Display name for tab
  icon: string;         // Lucide icon component name
  pro: boolean;         // Requires pro subscription
  description: string;  // Tooltip / CTA text
}

export const LENS_REGISTRY: LensDefinition[] = [
  { id: "sentiment",  label: "Sentiment Drill", icon: "BarChart3",   pro: false, description: "Deep sentiment analysis for a single game" },
  { id: "compare",    label: "Compare",         icon: "Swords",      pro: true,  description: "Side-by-side comparison of multiple games" },
  { id: "explorer",   label: "Explorer",        icon: "Table",       pro: true,  description: "Sortable table with every computed metric as a column" },
  { id: "benchmark",  label: "Benchmark",       icon: "Target",      pro: true,  description: "Percentile rankings within genre or tag" },
  { id: "market-map", label: "Market Map",      icon: "PieChart",    pro: true,  description: "Aggregate distributions across the filtered catalog" },
  { id: "trends",     label: "Trends",          icon: "TrendingUp",  pro: true,  description: "Time-series trends for any metric" },
];
```

Also export a helper `getLens(id: LensId): LensDefinition` and a `LensIcon` component that maps the icon string to the actual Lucide component.

---

## Step 5: ToolkitShell Component — `frontend/components/toolkit/ToolkitShell.tsx`

This is the main shell component. It is a `"use client"` component.

### Props

```typescript
interface ToolkitShellProps {
  /** Pre-applied filters the user cannot remove (e.g., appid on a game page). Rendered as non-removable chips. */
  lockedFilters?: Partial<Record<string, string | number | boolean | number[]>>;
  /** Default lens if none is in the URL. Falls back to "sentiment". */
  defaultLens?: LensId;
  /** Content to render above the filter bar (e.g., game header, genre intro). */
  header?: React.ReactNode;
  /** Which lens tabs to show. Defaults to all 6. */
  visibleLenses?: LensId[];
  /**
   * Override content for specific lenses. Allows existing pages to pass their
   * current client component as the body of a specific lens tab without rewriting.
   * Example: game page passes GameReportClient as the "sentiment" lens content.
   */
  lensContent?: Partial<Record<LensId, React.ReactNode>>;
}
```

### Behavior

1. Reads `lens` from `useToolkitState()`. If absent, uses `defaultLens` prop (or `"sentiment"` if neither).
2. Renders `header` prop above the shell (outside the filter/lens area).
3. Renders `FilterBar` with current filter state + `lockedFilters`.
4. Renders `LensTabSwitcher` with `visibleLenses` (or all lenses if not specified).
5. Renders lens content: checks `lensContent[activeLens]` first (for page overrides), then falls back to `LensRenderer` (placeholder stubs).
6. Maintains a `proCtaLens: LensId | null` local state — when set, the content area shows a `ProLockOverlay` instead of the lens content.

Layout: use `max-w-6xl mx-auto px-4` to match the rest of the site. But note that the shell itself should NOT add max-width if it is already inside a container that has it (the host page controls the outer container). The shell only manages its inner layout — filter bar, tabs, and content area.

---

## Step 6: FilterBar Component — `frontend/components/toolkit/FilterBar.tsx`

A horizontal strip of active filter chips with an "Add filter" button and game count.

### Layout

```
[ Genre: Action × ] [ Price: Under $10 × ] [ 200+ reviews × ]  [+ Add Filter]  [Clear all]    1,247 games
```

### Active Filter Chips

Each active filter renders as a chip showing the filter label and value. Chips have an × button to remove the filter (which clears the corresponding URL param via `useToolkitState` setter).

Locked filters (from `lockedFilters` prop) render as chips without the × button and with a subtle pin/lock visual (different border style or small lock icon). They cannot be removed.

Use the existing chip styling from SearchClient.tsx (rounded-full, font-mono, text-sm, border-border).

### "Add Filter" Popover

Clicking "+ Add Filter" opens a dropdown/popover listing available filter categories. Each category shows its name and the type of input:

| Category | Input Type | Options |
|---|---|---|
| Genre | Dropdown | Fetched from `getGenres()` on first open |
| Tag | Dropdown | Fetched from `getTopTags(20)` on first open |
| Price Range | Preset buttons | Free, Under $10, $10–$20, $20+ |
| Min Reviews | Preset buttons | 50+, 200+, 1,000+, 10,000+ |
| Sentiment | Preset buttons | Positive, Mixed, Negative |
| Deck Compatible | Toggle | Yes/No |
| Release Year | Two number inputs | From / To |
| Developer | Text input | Free text |
| Analyzed Only | Toggle | Yes/No |

Categories that already have an active filter show a checkmark or highlight. Selecting a value:
1. Sets the URL param via the nuqs setter
2. Closes the popover
3. A new chip appears in the filter bar

Style the popover like the existing Navbar browse dropdown: `background: var(--popover)`, `border: 1px solid var(--border)`, `rounded-xl`, `shadow-xl`.

Fetch genres and tags lazily (only on first popover open), same pattern as `Navbar.tsx` lines 29–39.

### Game Count Badge

Show a count badge on the right: "N games". Fetch the count by calling `getGames()` with the current filter params and `limit=1` (to minimize payload — only read the `total` field from the response).

Debounce the count fetch by 300ms after any filter change. Show a subtle loading indicator (opacity transition or ellipsis) while fetching.

If `appids` is set and contains exactly one value, the count badge can show "1 game" statically without an API call.

### "Clear All" Button

Visible when any non-locked filter is active. Clicking it resets all filter URL params to their defaults (via nuqs setters), but preserves `lens` and any locked filters.

### Responsive Behavior

On screens below `md` breakpoint, collapse the filter bar into a compact "Filters (N)" button that opens a slide-up panel or bottom sheet. Same concept as SearchClient.tsx's mobile filter approach.

---

## Step 7: LensTabSwitcher Component — `frontend/components/toolkit/LensTabSwitcher.tsx`

A horizontal tab bar showing the available lenses.

### Tab Styling

- **Active tab**: `text-foreground` with `border-b-2` in teal (`border-[color:var(--teal)]`), subtle `bg-card/50` background
- **Inactive tab**: `text-muted-foreground hover:text-foreground transition-colors`
- **Locked pro tab** (when `!isPro`): small `Lock` icon (lucide-react, `w-3 h-3`) next to the label, `opacity-60`

### Click Behavior

- **Free lens, or user is Pro**: update the `lens` URL param to the clicked lens ID.
- **Pro lens and user is NOT Pro**: do NOT change the `lens` URL param. Instead, call `onProLensClick(lens)` which sets the `proCtaLens` state in `ToolkitShell`, causing the content area to show the `ProLockOverlay`.

### Props

```typescript
interface LensTabSwitcherProps {
  activeLens: LensId;
  visibleLenses: LensId[];
  onLensChange: (lens: LensId) => void;
  onProLensClick: (lens: LensId) => void;
}
```

### Overflow / Scroll

On mobile, if tabs overflow horizontally, allow horizontal scroll with `overflow-x-auto` and hide the scrollbar. Tabs should not wrap to multiple lines.

---

## Step 8: ProLockOverlay Component — `frontend/components/toolkit/ProLockOverlay.tsx`

Displayed over the content area when a free user clicks a pro lens tab.

### Design

```tsx
<div className="absolute inset-0 z-10 flex items-center justify-center bg-background/80 backdrop-blur-sm rounded-xl">
  <div className="text-center max-w-sm px-6">
    <Lock className="w-8 h-8 mx-auto mb-3" style={{ color: "var(--teal)" }} />
    <h3 className="font-serif text-lg font-semibold mb-1">{lens.label}</h3>
    <p className="text-muted-foreground text-sm mb-4">{lens.description}</p>
    <Link
      href="/pro"
      className="inline-flex items-center gap-2 px-4 py-2 rounded-lg font-mono text-sm font-semibold transition-colors"
      style={{ background: "var(--teal)", color: "var(--background)" }}
    >
      Unlock with Pro →
    </Link>
    <button
      onClick={onDismiss}
      className="block mx-auto mt-3 text-sm text-muted-foreground hover:text-foreground transition-colors"
    >
      Dismiss
    </button>
  </div>
</div>
```

The content area (`LensContentArea`) must have `position: relative` for this overlay to position correctly.

---

## Step 9: Lens Placeholder Stubs — `frontend/components/toolkit/lenses/`

Create one stub component per lens. Each is a `"use client"` component that renders a simple placeholder showing the lens name and a brief message. Each stub receives the current filter state as props so that future implementations can use the same interface.

### Shared Lens Props Interface

```typescript
// frontend/lib/toolkit-state.ts (add to the existing file)
export interface LensProps {
  filters: ToolkitFilters;
  isPro: boolean;
}
```

### Stub Files

- `frontend/components/toolkit/lenses/SentimentDrillLens.tsx`
- `frontend/components/toolkit/lenses/CompareLens.tsx`
- `frontend/components/toolkit/lenses/ExplorerLens.tsx`
- `frontend/components/toolkit/lenses/BenchmarkLens.tsx`
- `frontend/components/toolkit/lenses/MarketMapLens.tsx`
- `frontend/components/toolkit/lenses/TrendsLens.tsx`

Each renders:

```tsx
<div className="py-20 text-center">
  <LensIcon name={definition.icon} className="w-10 h-10 mx-auto mb-4 text-muted-foreground" />
  <h2 className="font-serif text-xl font-semibold mb-2">{definition.label}</h2>
  <p className="text-muted-foreground text-sm">This lens is under construction.</p>
</div>
```

### LensRenderer Component — `frontend/components/toolkit/LensRenderer.tsx`

Maps a `LensId` to the appropriate lens component. Accepts an optional `override` (React.ReactNode) — if provided, renders the override instead of the stub. This is how existing pages inject their content into a lens tab.

```typescript
interface LensRendererProps {
  lens: LensId;
  filters: ToolkitFilters;
  isPro: boolean;
  override?: React.ReactNode;
}
```

Use a `switch` statement on `lens` to render the correct stub component, or `override` if provided.

---

## Step 10: New `/toolkit` Page — `frontend/app/toolkit/page.tsx`

The blank-canvas entry point. Server component with metadata, renders `ToolkitShell` with no presets.

```tsx
import type { Metadata } from "next";
import { ToolkitShell } from "@/components/toolkit/ToolkitShell";

export const metadata: Metadata = {
  title: "Toolkit — SteamPulse",
  description: "Explore Steam game intelligence with filters, comparisons, and market analysis.",
};

export default function ToolkitPage() {
  return (
    <main className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-4 py-8">
        <h1 className="font-serif text-2xl font-bold mb-1">Toolkit</h1>
        <p className="text-muted-foreground text-sm mb-6">
          Add filters to explore the Steam catalog. Switch lenses to see different perspectives.
        </p>
        <ToolkitShell />
      </div>
    </main>
  );
}
```

No `lockedFilters`, no `defaultLens` override, no `lensContent` overrides — everything comes from URL state.

---

## Step 11: Add Toolkit Link to Navbar

In `frontend/components/layout/Navbar.tsx`, add a "Toolkit" link in the desktop nav links, between "Analytics" and the search bar. Also add it to the mobile menu.

Use the `SlidersHorizontal` icon from lucide-react (already imported in `SearchClient.tsx` — import it in Navbar too).

Desktop link (same styling as existing nav links):

```tsx
<Link
  href="/toolkit"
  className="flex items-center gap-1 px-3 py-1.5 rounded text-sm font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
>
  <SlidersHorizontal className="w-3 h-3" /> Toolkit
</Link>
```

Mobile link:

```tsx
<Link href="/toolkit" onClick={() => setMobileMenuOpen(false)} className="block py-2 text-base text-foreground/70 hover:text-foreground">Toolkit</Link>
```

---

## Step 12: Integrate Existing Pages as Presets

This step is **incremental** — wrap existing content with the shell where it fits. If integration for a specific page is complex, skip it with a TODO comment and move on. The shell is a progressive enhancement.

### Game Report Page (`/games/[appid]/[slug]`)

This is the most important integration. The game page currently renders `GameReportClient` directly inside `<main>`.

In `page.tsx`, wrap the existing content with `ToolkitShell`:

```tsx
<main>
  <ToolkitShell
    lockedFilters={{ appids: [numericAppid] }}
    defaultLens="sentiment"
    visibleLenses={["sentiment", "compare", "benchmark"]}
    header={/* move breadcrumbs + game header area here if GameReportClient has them, or leave header empty */}
    lensContent={{
      sentiment: (
        <GameReportClient
          report={report}
          appid={numericAppid}
          /* ... all existing props unchanged ... */
        />
      ),
    }}
  />
</main>
```

`GameReportClient` becomes the content of the "Sentiment Drill" lens tab. Compare and Benchmark show placeholders (stubs) until their prompts are implemented.

**Important notes:**
- `page.tsx` is a server component. `ToolkitShell` is a `"use client"` component. `GameReportClient` is also `"use client"`. Server components can render client components as children/props — this is standard Next.js.
- All existing SSR data fetching, `generateMetadata`, JSON-LD, and ISR `revalidate` remain exactly as they are.
- The game page header content (game image, title, breadcrumbs, metadata chips) should still be visible regardless of which lens tab is selected. Either pass it as the `header` prop, or keep it as part of `GameReportClient` — whichever requires fewer changes.

### Genre Page (`/genre/[slug]`)

The genre page currently renders: top picks section → market intelligence charts → full SearchClient.

Add `ToolkitShell` below the existing top picks section. Lock the genre filter:

```tsx
<ToolkitShell
  lockedFilters={{ genre: slug }}
  defaultLens="explorer"
  visibleLenses={["explorer", "market-map", "trends"]}
  lensContent={{
    explorer: <SearchClient initialParams={{}} initialFilters={{ genre: slug }} hideGenreFilter />,
  }}
/>
```

The existing SearchClient content becomes the Explorer lens body. Market Map and Trends show placeholders.

### Tag Page (`/tag/[slug]`)

Same pattern as genre:

```tsx
<ToolkitShell
  lockedFilters={{ tag: slug }}
  defaultLens="explorer"
  visibleLenses={["explorer", "market-map", "trends"]}
  lensContent={{
    explorer: <SearchClient initialParams={{}} initialFilters={{ tag: slug }} hideTagFilter />,
  }}
/>
```

### Analytics Page (`/analytics`)

The analytics page currently renders `AnalyticsClient` directly. Wrap it:

```tsx
<main className="max-w-6xl mx-auto px-4 py-8">
  <h1 className="text-2xl font-bold mb-1">Analytics</h1>
  <p className="text-muted-foreground text-sm mb-6">
    Catalog-wide trends across the Steam ecosystem.
  </p>
  <ToolkitShell
    defaultLens="trends"
    visibleLenses={["trends", "market-map", "explorer"]}
    lensContent={{
      trends: <AnalyticsClient />,
    }}
  />
</main>
```

### Backwards Compatibility (Critical)

- Existing pages must continue to work identically if `ToolkitShell` has a rendering error. The shell is additive, not destructive.
- All existing Playwright tests must pass. The shell adds new DOM elements around existing content but does not remove or rename anything that tests assert on.
- Existing URL params (`?q=`, `?genre=`, `?sort=` on search pages) continue to work. The nuqs params use the same names, ensuring URL continuity.
- The standalone `/search` page is NOT modified in this prompt. It keeps its existing `SearchClient` approach. (A future prompt may integrate it with the toolkit shell.)

---

## Step 13: Playwright Test Updates

### Existing tests

Run all existing tests after implementation. The shell wraps existing content, so tests should pass. Fix any failures caused by structural changes (e.g., an extra wrapper div).

### New test file: `frontend/tests/toolkit.spec.ts`

Add a new test file covering the shell:

1. **Toolkit page loads** — navigate to `/toolkit`, verify filter bar visible, lens tabs visible, "Sentiment Drill" tab is active by default.

2. **Lens switching** — click each free lens tab, verify the active tab changes. Verify URL updates to include `?lens=<id>`.

3. **Pro lens lock** — with `NEXT_PUBLIC_PRO_ENABLED` not set (or false), click a pro lens tab (e.g., Compare). Verify the CTA overlay appears with "Unlock with Pro" text and a link to `/pro`. Verify the URL does NOT change to `?lens=compare`.

4. **Filter add/remove** — open the Add Filter popover, select a genre. Verify a filter chip appears. Verify URL contains `genre=<slug>`. Click the × on the chip. Verify URL no longer has the genre param.

5. **Clear all filters** — add multiple filters, click "Clear all", verify all chips are removed and URL is clean (only `lens` param may remain).

6. **Game page integration** — navigate to a game page (e.g., `/games/440/team-fortress-2`), verify the lens tab bar appears, verify "Sentiment Drill" tab is active, verify the game report content is visible.

7. **URL shareability** — navigate directly to `/toolkit?lens=explorer&genre=action&min_reviews=200`. Verify the Explorer tab is active, the genre chip shows "Action", and the min_reviews chip shows "200+".

### Mock fixtures

Add to `frontend/tests/fixtures/api-mock.ts` a `mockToolkitRoutes()` function that mocks `getGames` for count badge requests (returns `{ total: 1247, games: [] }` for `limit=1` requests).

---

## File Summary

### New files

| File | Purpose |
|------|---------|
| `frontend/lib/toolkit-state.ts` | URL state schema, `useToolkitState()` hook, `ToolkitFilters` type, `LensId` type, `LensProps` interface |
| `frontend/lib/lens-registry.ts` | `LENS_REGISTRY` array, `LensDefinition` interface, `getLens()` helper, `LensIcon` component |
| `frontend/components/toolkit/ToolkitShell.tsx` | Main shell: filter bar + lens tabs + content area |
| `frontend/components/toolkit/FilterBar.tsx` | Composable filter chips, add filter popover, game count badge |
| `frontend/components/toolkit/LensTabSwitcher.tsx` | Tab bar with pro lock icons |
| `frontend/components/toolkit/ProLockOverlay.tsx` | Blur overlay with upgrade CTA |
| `frontend/components/toolkit/LensRenderer.tsx` | Maps `LensId` to lens component or override |
| `frontend/components/toolkit/lenses/SentimentDrillLens.tsx` | Placeholder stub |
| `frontend/components/toolkit/lenses/CompareLens.tsx` | Placeholder stub |
| `frontend/components/toolkit/lenses/ExplorerLens.tsx` | Placeholder stub |
| `frontend/components/toolkit/lenses/BenchmarkLens.tsx` | Placeholder stub |
| `frontend/components/toolkit/lenses/MarketMapLens.tsx` | Placeholder stub |
| `frontend/components/toolkit/lenses/TrendsLens.tsx` | Placeholder stub |
| `frontend/app/toolkit/page.tsx` | Clean toolkit page (blank canvas) |
| `frontend/tests/toolkit.spec.ts` | Playwright tests for the shell |

### Modified files

| File | Change |
|------|--------|
| `frontend/package.json` | Add `nuqs` dependency |
| `frontend/app/layout.tsx` | Add `NuqsAdapter` wrapper |
| `frontend/components/layout/Navbar.tsx` | Add "Toolkit" nav link (desktop + mobile) |
| `frontend/app/games/[appid]/[slug]/page.tsx` | Wrap `GameReportClient` in `ToolkitShell` |
| `frontend/app/genre/[slug]/page.tsx` | Add `ToolkitShell` wrapping SearchClient section |
| `frontend/app/tag/[slug]/page.tsx` | Add `ToolkitShell` wrapping SearchClient section |
| `frontend/app/analytics/page.tsx` | Wrap `AnalyticsClient` in `ToolkitShell` |
| `frontend/tests/fixtures/api-mock.ts` | Add `mockToolkitRoutes()` |

---

## Verification

1. **Build succeeds**: `cd frontend && npm run build` — no TypeScript errors.

2. **Dev server check** — visit each page and verify:
   - `/toolkit` — filter bar visible, all 6 lens tabs visible, Sentiment Drill active, placeholder content shown
   - `/toolkit?lens=compare` — Compare tab active, pro CTA overlay displayed (if not pro)
   - `/toolkit?genre=action&lens=explorer` — genre chip shown as "Action", Explorer tab active
   - `/games/440/team-fortress-2` — game report content visible inside shell, Sentiment Drill tab active, Compare and Benchmark tabs shown (locked if not pro)
   - `/genre/action` — genre locked as non-removable chip, SearchClient visible as explorer content
   - `/analytics` — AnalyticsClient visible as trends content
   - All other existing pages render correctly and are not broken

3. **URL state round-trip**:
   - Adding a filter updates the URL immediately
   - Refreshing the page restores all filters and active lens from URL
   - Browser back/forward navigates between filter states
   - Copying the URL and opening in a new tab shows the same state

4. **Playwright tests**: `cd frontend && npm run test:e2e` — all existing tests pass, new toolkit tests pass.
