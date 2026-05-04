# /explore — Table lens

**Status:** not started. Stub was deleted after UI consolidation (see `scripts/prompts/ui-consolidation.md`) so users aren't confused by an empty tab. This prompt captures the design so we can rebuild it when the analyst workflow becomes a priority.

## What it is (in one sentence)

A filterable, sortable, multi-column data grid of every game matching the current filter bar — the "give me the rows with all the metrics" view that analysts actually use to answer specific catalog questions.

## The question it answers

> "Show me all 2024 action roguelikes under $20 with >1000 reviews, sorted by hidden gem score descending."

Today that question has **no home**. `/search` is title-autocomplete driven. Genre/tag pages are SSR'd with a fixed layout. The Explore lens family has Trends (time series) and Chart Builder (custom chart) but nothing that says "just give me the rows." This lens fills that gap.

## Where it lives

- Route: `/explore`
- Lens id: `explorer` (unchanged from the stub — URL param compatibility)
- Label in tab bar: **Table**
- Default lens on `/explore`: still `trends` (unchanged). Table is one of the four catalog lenses.
- Filter bar above: the existing `FilterBar` — genre, tag, search, developer, sentiment, price_tier, min_reviews, year_from/to, deck, has_analysis. No new filters.
- URL state: driven by the existing `toolkitParsers` in `lib/toolkit-state.ts`. Table-specific state (column visibility, sort, density) gets new `t_`-prefixed params so it can't collide with other lenses, same convention Builder uses with `b_`.

## Backing data — already exists

`/api/games` already supports every filter the toolkit bar produces and returns the full row shape via `GameRepository`. The only backend work is:

- Confirm the endpoint accepts multi-column sort (`sort=hidden_gem_score,desc;review_count,desc`) or adapt to whatever it supports today.
- Add pagination params if not present (`limit`, `offset` or cursor).
- Make sure every column we want to render is in the response — see Columns below. Anything missing is a one-liner in `GameRepository.list_games()`.

No new Lambda, no new migration, no new analyzer pass.

## Columns

Default visible (in order):

1. **Game** — header image thumbnail (32px) + name. Click → game page. Sticky left.
2. **Genres** — comma-joined, up to 2 shown, "+N" for overflow
3. **Release date** — short format, sortable
4. **Price** — `$X.XX` or "Free", sortable
5. **Reviews** — total review count, right-aligned, sortable
6. **Positive %** — Steam positive_pct, right-aligned, colored (red/amber/green thresholds)
7. **Review score** — Steam review_score_desc ("Very Positive" etc.)
8. **Hidden gem** — hidden_gem_score as 0–100, right-aligned, sortable
9. **Est. revenue** — `revenue_estimate_usd` Boxleiter v1, right-aligned, sortable
10. **Est. owners** — `estimated_owners`, right-aligned, sortable
11. **Analyzed** — checkmark if `has_analysis`, click → game page's Analysis section

Available but hidden by default (toggle via column picker):
- Developer, Publisher, Tags (comma list), Deck compatibility, Platforms (W/M/L icons), EA flag, Last analyzed timestamp, Total reviews analyzed, Sentiment trend (arrow), Primary tag, Year, Review velocity (30d)

**Column visibility** persists in URL (`t_cols=game,genres,reviews,...`) so a saved URL restores the exact view.

## Interaction model

- **Sort**: click header to sort asc/desc/off. Shift-click adds secondary sort. Active sort state in URL (`t_sort=hidden_gem_score,desc`). Multi-sort badges in header show priority (1, 2, 3).
- **Filter**: driven by the global FilterBar above the lens. Table re-queries when filters change. No per-column filter UI (keeps the model clean — the FilterBar is the single source of filter truth).
- **Row click**: navigates to the game page (`/games/{appid}/{slug}`). Cmd/Ctrl-click opens in new tab. Do not use a button inside the row; the whole row is the click target with proper `role="link"` or wrapping Link.
- **Density toggle**: compact / comfortable / spacious. URL (`t_density=compact`). Default comfortable.
- **Column picker**: popover with checkboxes + drag-to-reorder. Commits to URL.
- **Pagination**: virtualized infinite scroll (TanStack Virtual) — load 50 rows at a time as the user scrolls. Show loading skeleton rows at the bottom. Show total count ("Showing 1–50 of 2,341") in a sticky footer.
- **Empty state**: if filters match zero games, show "No games match these filters" with a "Clear filters" button.
- **Error state**: if the API errors, show "Couldn't load games" with retry button. Don't blank the page.

## UI/UX research — patterns this should follow

This is the most-studied UI pattern in analytics software. The good patterns:

- **TanStack Table v8** (headless): the obvious library choice. Already works with React 18+, supports column visibility / ordering / sorting / row models, plays cleanly with URL state, pairs well with TanStack Virtual for large datasets. Use it — don't roll your own.
- **Sticky header + sticky first column**: non-negotiable on a wide table. The game name must always be visible when scrolling horizontally.
- **Right-align numeric columns, left-align text**: universal convention (Excel, Google Sheets, Linear, Airtable, Metabase). Tabular-nums font feature (`font-variant-numeric: tabular-nums`) on numeric cells so digits line up.
- **Sort indicators in the header, always visible when active**: small up/down chevron, plus a number badge (1, 2, 3) when multi-sort is active. Linear and Notion both do this well.
- **Virtualize past ~100 rows**: anything longer and non-virtualized grids become unusable. TanStack Virtual + TanStack Table is the standard combo.
- **Column picker in a popover, not a modal**: modal is overkill for "hide a column." Linear, GitHub Projects, Notion all use popovers.
- **No per-cell editing**: this is a read-only analyst view, not a CMS. Don't add inline editing — it ruins the click-row-to-open pattern.
- **Row density, not row height config**: give three presets (compact/comfortable/spacious), not a free pixel slider. Airtable and Notion converged on this.
- **URL-driven state**: all of sort, column visibility, density, pagination cursor in the URL so the view is shareable and back-button works. This matches the rest of the toolkit.
- **Keyboard**: arrow keys move the selected row, Enter opens it. Table views without keyboard nav feel broken to power users. Reference: Linear and Notion.

Anti-patterns to avoid (seen in many SaaS tables, don't copy them):

- Per-column filter dropdowns. The FilterBar is the filter surface; duplicating it in each column is clutter and splits the mental model.
- Modal-based "configure view." Popovers are faster and keep context.
- Hardcoded column widths. Let content + minmax do the work; users who need more can drag to resize (Pro enhancement, not v1).
- Sticky toolbar that eats half the vertical space. One slim row is enough.
- Checkbox selection without a bulk action. If you show checkboxes, there must be a bulk action (export selected, etc.). Otherwise they're noise. v1 has no bulk actions → no checkboxes.

## Implementation plan

### Phase 1 — core grid

1. Add `t_sort`, `t_cols`, `t_density` parsers to `lib/toolkit-state.ts`. `t_sort` uses a compact `col,dir;col,dir` format to support multi-sort in a URL.
2. Extend `getGames()` in `lib/api.ts` (and the `/api/games` handler if needed) to accept `sort` as a repeatable param and `limit`/`offset` for pagination. Verify `GameRepository.list_games()` returns every column in the Columns list above. Add missing columns (this is the one place backend work may be needed).
3. Install TanStack Table v8 and TanStack Virtual if not already present.
4. Rebuild `components/toolkit/lenses/ExplorerLens.tsx`:
   - Read filters from the effective filters prop the shell passes.
   - Query games via a custom hook `useTableData(filters, sort, offset)` that paginates and assembles rows.
   - Render via `useReactTable` + `useVirtualizer`.
   - Sticky header + sticky first column (Game).
   - Sort indicators + shift-click multi-sort.
   - Row click → Link to game page.
   - Skeleton rows during load.
   - Empty/error states.
5. Toolbar above the grid: density toggle, column picker popover, result count, CSV export button.
6. Persist `t_sort`, `t_cols`, `t_density` in URL via `nuqs`.

### Phase 2 — export

7. CSV export endpoint: add `GET /api/games/export` that streams a CSV of all rows matching the filters. Default columns = currently visible (pass via query param `cols=...`).
8. Wire the CSV button to fetch the endpoint and trigger a browser download. Show a progress toast for large exports.

### Phase 3 — polish

10. Keyboard nav: arrow up/down moves row focus, Enter opens the selected game. Escape clears selection.
11. Sticky footer with "Showing X–Y of N · Z filters active · Clear all" breadcrumb.
12. Mobile: at narrow viewports, collapse to a single-column card list with the 4 most important fields (Game, Reviews, Positive %, Hidden Gem). The full table is desktop-only — don't try to horizontally scroll 15 columns on a phone.

## Tests (mandatory per CLAUDE.md)

- `frontend/tests/explore-table-lens.spec.ts` — new file
  - renders the table on `/explore?lens=explorer`
  - column headers present; sort click flips direction and reflects in URL
  - shift-click adds secondary sort
  - row click navigates to game page
  - filter bar changes re-query the table
  - empty state when filters match zero rows
  - column picker shows and hides columns, URL updates
  - density toggle changes row height
  - CSV export button works

## Non-goals for v1

- Inline editing / any mutation — read-only view.
- Saved views (name a filter+sort+columns combo, load it later) — cut. Defer to a "Saved Views" prompt if/when auth lands.
- Per-cell charts or sparklines — defer.
- Bulk row selection and bulk actions — defer.
- Column resize handles — defer. `minmax()` + sensible defaults is enough for v1.
- Freeze-additional-columns beyond the single sticky Game column — defer.
- Per-column filter dropdowns — explicitly rejected, see anti-patterns.

## How to know it's working

1. Visit `/explore?lens=explorer` — full table renders with defaults.
2. Click the Reviews header — sorted descending. URL shows `t_sort=review_count,desc`.
3. Shift-click Hidden Gem header — secondary sort added. URL shows both.
4. Add a genre filter in the FilterBar — table re-queries, row count updates.
5. Open the column picker, hide Price — column disappears, URL reflects it.
6. Copy the URL, open in a new tab — identical view renders.
7. Click a row — lands on the game page.
8. Free user: Revenue column shows blur + lock; CSV button disabled.
9. Pro user: Revenue column visible; CSV button downloads all rows for current filters.
10. Scroll to the bottom — virtualizer loads next page of rows seamlessly.
