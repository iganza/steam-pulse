# /explore — Market Map lens

**Status:** not started. Stub was deleted after UI consolidation (see `scripts/prompts/ui-consolidation.md`) so users aren't confused by an empty tab. This prompt captures the design so we can rebuild it when the segment-shape view becomes a priority.

## What it is (in one sentence)

A grid of small, linked aggregate distribution charts that describe the **shape of the segment** defined by the current filter bar — not the individual games, but what the catalog slice looks like in aggregate.

## The question it answers

> "What does the 2023+ roguelike corner of Steam actually look like? How is it priced? How are these games rated? What platforms do they target? How many are early access? What's the size of the segment?"

Today there's no single page that answers "what is this segment shaped like?" in one glance. Per-entity pages (`/genre/[slug]`, `/tag/[slug]`, `/developer`) answer it *for that specific entity*, but only if you land on one of them, and only using the fixed layout those SSR pages happen to have. Market Map is the lens that does this **for any filter combination the toolkit supports** — "roguelikes + 2023+ + under $20 + >1000 reviews" produces a full segment portrait on demand.

## Where it lives

- Route: `/explore`
- Lens id: `market-map`
- Label in tab bar: **Market Map**
- Filter bar above: the shared `FilterBar` — same filters as every other `/explore` lens.
- URL state: existing filter parsers. Market-map-specific state (normalize %/absolute toggle, which panels are collapsed) gets `m_`-prefixed params.

## The small-multiples model

**This is the single most important design decision: it's small multiples, not one big chart.** Tufte's "small multiples" principle: many small charts, each the same shape, each answering the same question against a different dimension, arranged in a grid the eye can scan in a few seconds. Tableau, Power BI, Amplitude, Mixpanel, and Sensor Tower all use this pattern for segment explorers. A single giant dashboard chart forces the user to read labels and drill in; a grid of small charts lets them scan and spot anomalies at a glance.

Panels (v1, 8 total, 2 rows × 4 columns on desktop, responsive):

1. **Segment size** — a single big number + subtitle. "2,341 games · 12% of catalog · 4.1M reviews". Not a chart. Anchors the page.
2. **Genre mix** — horizontal bar chart, top 8 genres by game count in the segment. Rest collapsed into "Other". Click a bar → adds that genre as a filter (crossfilter, see below).
3. **Price distribution** — histogram across price tiers (free, <$10, $10–$20, $20–$40, >$40). Bar heights = count. Click a tier → adds `price_tier` filter.
4. **Sentiment distribution** — stacked horizontal bar: positive / mixed / negative as %. One row. Click a band → adds `sentiment` filter.
5. **Review count distribution** — histogram on a log scale (brackets: 0–100, 100–1k, 1k–10k, 10k–100k, 100k+). Shows the long tail clearly. Click a bucket → sets `min_reviews`.
6. **Release year histogram** — bar per year covering the segment's range. Click a bar → sets `year_from`/`year_to`.
7. **Platform coverage** — four horizontal bars (Windows, Mac, Linux, Steam Deck Verified) showing % of segment. Not clickable (no filter yet).
8. **Early access share** — donut: EA vs Released vs Ever-was-EA. Click a slice → adds an `ea` filter (new filter; small backend add).

All eight panels live in a responsive CSS grid. Each panel has:
- A short title (2–3 words)
- A single subtitle with the metric (`by game count` / `by review volume` toggle — see below)
- The chart body (80–120px tall — small is the point)
- A "sample: N" hint on low-count segments (<100 games)

## Interaction model — crossfilter

**Clicking any bar/slice in any panel adds that dimension as a filter and re-queries the entire page.** This is the dcjs / Tableau "brushing and linking" pattern, and it's the single reason Market Map is more than a static dashboard. Flow:

1. User opens `/explore?lens=market-map` with no filters → all 8 panels show catalog-wide distributions.
2. Click the "Action" bar in Genre mix → `genre=action` is appended to the URL. All 8 panels re-query and repaint.
3. Click the "$10–$20" bar in Price distribution → `price_tier=10_to_20` added. All 8 panels re-query.
4. User now sees the 2023+ action $10–$20 segment. Size panel shows new count. Every other panel shows the distribution *within that segment*.
5. Active filters are visible in the shared FilterBar chips above the lens, so the user can remove any of them with one click.

This is the core value proposition. Without crossfilter, small-multiples is just a dashboard. With it, it's an exploration tool.

## Global toggles (top right of lens)

- **Normalize: Count / %** — switch all panels between absolute counts and % of segment. Default: Count. Stored in `m_norm` URL param.
- **Weight by: Games / Reviews** — the big decision. "By games" counts each game as 1. "By reviews" weights by review_count so popular games dominate. "By reviews" is the more honest "where is the audience" view; "By games" is the "what are devs making" view. Both are meaningful, and users should be able to toggle. Default: Games. Stored in `m_weight`.
- **Export PNG** — Pro-only button that downloads a composite PNG of the current grid at 2x resolution. One-shot, no config.

## Empty, low-sample, and loading states

- **Loading**: skeleton panels with a pulsing bar — keep the grid shape so the page doesn't reflow.
- **Empty** (filters match 0 games): replace the grid with a single centered card: "No games match these filters" + "Clear filters" button. Same treatment as Table lens.
- **Low sample** (segment has <100 games): every panel renders but shows a yellow "Small sample (N games)" warning strip at the top of the lens. Individual panels that are meaningless below 100 games (sentiment distribution especially) gray out with "needs ≥100 games" text.
- **Error**: show a single "Couldn't load segment data" + retry in place of the grid. Don't blank the page.

## Backing data — mostly exists, small additions

Market Map needs one endpoint that returns all eight distributions in a single payload, scoped to the current filters:

`GET /api/explore/market-map?<filters>` →

```json
{
  "segment_size": { "games": 2341, "reviews": 4_100_000, "pct_of_catalog": 0.12 },
  "genre_mix": [{ "name": "Action", "games": 892, "reviews": 1_200_000 }, ...],
  "price_distribution": [{ "tier": "free", "games": 120, "reviews": 200_000 }, ...],
  "sentiment_distribution": { "positive": 1400, "mixed": 700, "negative": 241 },
  "review_count_buckets": [{ "bucket": "1k_to_10k", "games": 812 }, ...],
  "release_year_histogram": [{ "year": 2023, "games": 450 }, ...],
  "platform_coverage": { "windows": 2341, "mac": 812, "linux": 520, "deck_verified": 310 },
  "early_access": { "in_ea": 120, "released": 2100, "ever_ea": 380 },
  "sample_ok": true
}
```

Each field is a single `GROUP BY` on `games` with the same `WHERE` clause the existing filter parser produces. Build it in a new `MarketMapRepository` method that runs the eight aggregations in parallel (or one CTE if the query planner handles it better). This is classic "cheap to compute, expensive to think through" backend work — a day or two.

Several existing endpoints (`/api/analytics/price-positioning`, `/api/analytics/platform-gaps`, `/api/analytics/release-timing`, some of `/api/analytics/trends/*`) already compute subsets of this, but each returns a different shape and is scoped to a specific entity page rather than arbitrary filter combinations. Do **not** try to compose Market Map from those — write one purpose-built endpoint that owns the filter-to-distribution contract.

## UI/UX research — patterns this should follow

- **Tufte's small multiples**: the principle this entire lens is built on. Many small charts in a grid > one giant chart with controls. Read *The Visual Display of Quantitative Information* ch. 4 if in doubt.
- **dcjs / crossfilter**: the canonical "click anywhere to filter everywhere" pattern. Tableau calls it "brushing and linking." Our version just mutates URL state via the existing toolkit FilterBar, so it integrates for free with the rest of `/explore`.
- **Amplitude / Mixpanel "Insights" grids**: small-multiples with click-to-filter, segment-size number in the top-left. We're explicitly taking the visual structure from these.
- **Sensor Tower "Market Explorer"**: the game-industry analogue. Distributions of category, price, rating in a grid with filter chips above. We're doing the same but for Steam.
- **Recharts**: the charting library already used elsewhere in the app. Use it. Don't introduce D3 directly — too heavy for v1.
- **Count / % toggle**: Every good segment explorer has it. Different questions need different normalizations.
- **Games / Reviews weight toggle**: Less common but hugely valuable. Steam's catalog is dominated by shovelware by game count and by big titles by review count — same filter, same data, two totally different pictures. Showing only one is misleading. App Annie/data.ai's "by downloads vs by app count" toggle is the reference.

Anti-patterns to avoid:

- **One giant chart with a dropdown to pick the dimension.** That's the opposite of small multiples. Users have to click, read, click, read — the whole point is scan-and-compare.
- **Tooltips as the only way to see numbers.** Always show counts on the chart (on bars, above pie slices, etc.) so users don't need to hover. Tooltips supplement, they don't replace.
- **Pie charts for more than ~5 slices.** The Genre mix panel is a horizontal bar for this reason. Only Early Access (3 slices) gets a donut.
- **Colored categorical palettes with 12+ colors.** Eyes can't distinguish. Top 7 + "Other" is the hard ceiling for categorical axes.
- **Animations on every re-render.** Crossfilter means frequent re-renders; a 400ms animation on each one is nauseating. Use 150ms ease-out and only on bar height transitions, not color or position.
- **Burying the segment-size number.** It's the anchor. Top-left, large, never collapsed.

## Implementation plan

### Phase 1 — backend

1. Add `MarketMapRepository` with a single method `get_segment_portrait(filters)` returning the 8-field shape above. Run the aggregations in parallel where it helps; otherwise one CTE.
2. Add `GET /api/explore/market-map` in the FastAPI app. Reuse the existing filter parsing from `/api/games` so the filter surface is identical.
3. Unit test the repository against the `steampulse_test` DB with a few seeded segments.

### Phase 2 — frontend lens

4. Add `m_norm`, `m_weight` parsers to `lib/toolkit-state.ts`.
5. Rebuild `components/toolkit/lenses/MarketMapLens.tsx`:
   - Fetch the segment portrait via a `useMarketMap(filters, weight)` hook.
   - Render an 8-panel responsive grid (2×4 desktop, 1×8 mobile, 2×2 per row tablet).
   - Each panel is its own small component (`<SegmentSizePanel>`, `<GenreMixPanel>`, etc.) so they can evolve independently.
   - Normalize/weight toggles in the lens toolbar.
6. Crossfilter wiring: each clickable bar/slice calls `setState({ [filter]: value })` via the existing toolkit state hook. Filter bar above updates automatically.
7. Empty / low-sample / error / loading states.

### Phase 3 — polish + Pro export

8. PNG export: use `html-to-image` (or similar) to capture the grid at 2x DPR. Gate behind `usePro()`. Free users see the button disabled with a tooltip.
9. Keyboard: Tab cycles panels, Enter on a focused bar applies its filter. Accessibility pass.
10. Mobile: stack to 1 column; panels keep their full information but resize. Don't hide any of them on mobile — this is a scan-first lens and scrolling is fine.

## Tests (mandatory per CLAUDE.md)

- `frontend/tests/explore-market-map-lens.spec.ts` — new file
  - renders all 8 panels on `/explore?lens=market-map`
  - segment size shows catalog-wide numbers with no filters
  - clicking a Genre bar applies the genre filter and re-queries (crossfilter)
  - clicking a Price bar applies the price_tier filter
  - normalize Count ↔ % toggle changes bar values (not counts)
  - weight Games ↔ Reviews toggle re-queries with different weights
  - low-sample warning appears on narrow filter combinations
  - empty state renders when filters match nothing
  - Pro user can trigger PNG export; free user sees disabled button

## Non-goals for v1

- Drilldown into a panel ("show me the top 10 games in the Action bar") — that's what the Table lens is for. Clicking a bar *filters*, it doesn't drill. Resist the urge.
- Custom panel configuration (pick which 8 panels to show) — the 8 are opinionated and fixed in v1. Customization is a later prompt.
- Side-by-side segment comparison ("roguelikes vs platformers") — a great future feature but a whole second design. Defer.
- Time-windowed distributions ("show me how sentiment distribution changed 2020 → 2024") — that's what the Trends lens is for. Market Map is a snapshot.
- Saved segments with names — same answer as Table: defer until `/pro` has auth.

## How to know it's working

1. Visit `/explore?lens=market-map` — all 8 panels render with catalog-wide numbers.
2. Click the "Action" bar in Genre mix — URL gains `genre=action`, all 8 panels re-query and show the action segment's shape. Size panel drops from catalog total to action-only.
3. Click the `$10–$20` bar in Price distribution — filter stacks. Panels re-query to show the action / $10–$20 intersection.
4. Flip Normalize to % — bars rescale to 0–100%, counts labels update.
5. Flip Weight to Reviews — bars re-query with review-weighted counts. The Genre mix typically looks dramatically different because Steam's long tail has lots of small games and a few enormous ones.
6. Narrow filters until <100 games match — low-sample warning appears; sentiment panel grays out.
7. Clear all filters (from the FilterBar) — returns to catalog-wide view.
8. Pro user clicks PNG export — downloads a composite image of the current grid.
9. URL of the current view is shareable — pasting it into a new tab renders the same segment.
