# Analytics Builder Lens — User-Composed Charts

## Background

Today the analytics surface is the `TrendsLens`: 9 pre-canned charts with hardcoded metrics, axes, and chart types. The only user controls are granularity, a couple of Pro toggles (game type, normalization, top-N), and the global genre/tag filter. There is no way for a user to pick *what* to plot, *how* to plot it, or to combine arbitrary metrics on a single chart.

This is a real ceiling on the analytics value prop. The bones for a true "toolkit" experience already exist:

- **Backend**: 9 modular `/api/analytics/trends/*` endpoints reading `mv_*` matviews via `analytics_repo.py`. Each endpoint returns a fixed shape, but the underlying matviews are flexible.
- **Frontend**: 4 generic Recharts primitives in `frontend/components/trends/` (`TrendBarChart`, `TrendStackedArea`, `TrendStackedBarChart`, `TrendComposed`) — already used by the pre-canned charts.
- **Lens architecture**: `frontend/lib/toolkit-state.ts` + `ToolkitShell` already supports adding new lenses with their own URL state. `CompareLens` is the precedent for user-driven selection (appids in URL, parallel fetch, frontend assembly).

What's missing is (a) a generic backend query that returns multiple metrics in one response, (b) a backend-owned metric registry, and (c) a frontend lens that exposes metric/chart-type/filter pickers and routes the result into the existing chart primitives.

---

## Goal

Add a new **Builder lens** to the toolkit that lets a user compose their own chart:

1. Pick 1–N metrics from a curated catalog of trend metrics.
2. Pick a chart type (bar / line / stacked area / composed).
3. Apply filters (genre, tag, etc.) via the existing global filter bar.
4. See it rendered using existing chart primitives — no new chart code.
5. Pro-gated beyond a small free baseline.

This is an **MVP**: single Builder lens, picker + 4 chart types, no drill-down, no saved charts, no multi-chart canvas. It *does* add three new pre-computed trend matviews (see Backend §0) so reads are fast regardless of metric combination. The next iteration can extend filters, add drill-down, and persist saved views.

---

## Confirmed Decisions

- **Scope**: MVP only — single Builder lens, picker + 4 chart types routed into existing Recharts primitives. Three new pre-computed trend matviews are added so Builder reads are fast (no live `DATE_TRUNC` aggregation per request). No drill-down, no saved charts, no multi-chart canvas.
- **Metric registry**: Backend-owned in `library_layer/analytics/metrics.py`, exposed via `GET /api/analytics/metrics`. Frontend fetches it; adding a metric is a backend-only change.
- **Pro gating**: Free = 1 metric, granularity restricted to month/quarter/year, no normalization toggle. Pro = full picker (multi-metric, week granularity, normalization, all chart types).
- **Filter extension on existing trend endpoints**: deferred. The new `/api/analytics/trend-query` endpoint is the only backend surface added in this prompt; richer filters on legacy endpoints can come in a follow-up.

---

## Codebase Orientation

### Existing pieces this lens builds on

- **Chart primitives** (`frontend/components/trends/`): `TrendBarChart.tsx`, `TrendStackedArea.tsx`, `TrendStackedBarChart.tsx`, `TrendComposed.tsx`. All accept `data: TrendPeriod[]`, a series definition, and a granularity. Reuse — do not rewrite.
- **Lens shell + URL state**: `frontend/lib/toolkit-state.ts`, `ToolkitShell`, `LENSES` registry.
- **Picker UX precedent**: `frontend/components/toolkit/compare/GamePicker.tsx` (chip-style picker pattern).
- **Pro gating UX**: blur + upgrade-link pattern in `frontend/components/toolkit/lenses/TrendsLens.tsx` (lines 131-178). Reuse the `useIsPro` hook.
- **Backend trend repo**: `src/library-layer/library_layer/repositories/analytics_repo.py` — wraps `mv_*` matviews. Reuse, don't replace.
- **Backend service**: `src/library-layer/library_layer/services/analytics_service.py` — orchestration layer.
- **API handler**: `src/lambda-functions/lambda_functions/api/handler.py` — where new routes live.

### Existing backend trend metrics

Already exposed by `/api/analytics/trends/*` endpoints as **live `DATE_TRUNC` aggregations over the `games` table** (not matview-backed today; engagement reads `index_insights`, EA joins `reviews`). Builder will serve these same metrics from new pre-computed matviews — see Backend §0. These are the seed catalog for the metric registry:

- Volume: `releases`, `free_count`
- Sentiment: `avg_steam_pct`, `positive_count`, `mixed_count`, `negative_count`, `avg_metacritic`
- Pricing: `free_pct`, `avg_paid_price`, `median_price`
- Velocity: `velocity_under_1`, `velocity_1_10`, `velocity_10_50`, `velocity_50_plus`
- Early access: `ea_count`, `ea_pct`, `ea_avg_steam_pct`, `non_ea_avg_steam_pct`
- Platform: `mac_pct`, `linux_pct`, `deck_verified_pct`, `deck_playable_pct`, `deck_unsupported_pct`

> **Note**: Engagement metrics (`playtime_*_pct` buckets) are sourced from
> `index_insights` rather than the trend matviews, and require the
> cross-source merge path in `query_metrics`. They are **deferred to a
> follow-up** — v1 of the registry exposes only `source="trend_matview"`
> metrics so the Builder lens ships with a single, uniform query path.

---

## UX Principles (non-negotiable)

These rules are informed by established self-serve BI patterns (Metabase, Looker, Hex) and chart-design literature. Treat them as hard requirements, not suggestions.

### 1. Smart defaults — never an empty canvas

The user must never see a blank chart area asking "now what?". On first load:

- If the URL has no `metrics` selected, pre-select **one sensible default metric** (e.g. `releases`) and render its chart immediately.
- When the user adds a metric, auto-pick the chart type from that metric's `default_chart_hint` in the registry — only override if the user has explicitly chosen a chart type.
- When the user picks a chart type that becomes incompatible (see rules below), keep the metric selection and *fall back* to a compatible chart type rather than blanking the canvas. Surface a small toast: "Switched to bar — stacked area needs metrics with the same unit."

### 2. Chart type compatibility rules (enforced in `ChartResolver`)

| Chart type    | Allowed when                                                                  | Disabled tooltip                                              |
|---------------|--------------------------------------------------------------------------------|---------------------------------------------------------------|
| Bar           | Always                                                                         | —                                                             |
| Line          | Always                                                                         | —                                                             |
| Stacked area  | ≥2 metrics AND all metrics share the same `unit` AND unit ∈ {`count`, `pct`}   | "Stacked area needs ≥2 metrics with the same unit."           |
| Composed      | ≥2 metrics                                                                     | "Composed view needs ≥2 metrics."                             |

A metric mix with **different units** (e.g. `releases` count + `avg_paid_price` currency) automatically routes to **dual-axis composed** — bar on the left axis (counts), line on the right axis (currency/pct/score). This is the *only* legitimate use of dual axis; never put two same-unit metrics on dual axes. Rationale: dual axes are dangerous when readers can't tell which series belongs to which axis — restrict them to the case where unit difference makes the mapping unambiguous.

Disabled chart-type buttons must be visually disabled (not hidden) and carry a `title=` tooltip with the reason — discoverability over surprise.

### 3. Progressive disclosure

- Free tier: metric picker, chart type picker, granularity (month/quarter/year). That's it. No normalization toggle, no advanced filters surfaced.
- Pro tier: normalization toggle appears **only when** all selected metrics are counts (normalization is meaningless for pct/currency). Week granularity unlocks. Multi-metric (up to 6) unlocks.
- Never show a control that does nothing for the current selection — hide it, don't disable it (exception: chart type buttons, which are disabled-with-reason for discoverability).

### 4. Performance budgets

- **Initial chart render**: < 2s from page load on a cold cache.
- **Interaction response** (changing a picker): < 100ms feedback (loading spinner if the fetch takes longer).
- **Series cap**: ≤ 1000 data points per chart. The `limit` query param defaults to 24 (months), max 200. If the user picks a granularity that would exceed 1000 points across all series, the frontend caps `limit` and surfaces a small note: "Showing the most recent 200 periods."
- Debounce filter/picker changes by 250ms before firing the fetch.
- Cache fetched results in-memory keyed by the full query so toggling chart types doesn't re-fetch.

### 5. Accessibility

- Use a **colorblind-safe categorical palette** (Okabe-Ito 8-color or Tableau 10 colorblind-safe). Recharts' default palette is *not* colorblind-safe — define a constant `BUILDER_PALETTE` in `frontend/components/toolkit/builder/palette.ts` and pass it explicitly to every chart primitive.
- Every series must be labeled in the chart itself (axis label, end-of-line label, or persistent legend) — never rely on color alone.
- All picker controls keyboard-navigable: arrow keys cycle metrics, space/enter toggles, escape closes any popover.
- All interactive elements have visible focus rings and `aria-label`s.

### 6. Empty, loading, and error states

- **Empty (no metrics selected)**: Friendly placeholder with a one-liner "Pick a metric to start plotting" and a CTA to the metric picker. Never show an empty Recharts container.
- **Loading**: Skeleton chart (gray bars) over the chart area — never a spinner-only state.
- **Zero rows returned**: "No data for this combination of filters. Try widening the date range or removing a filter."
- **Fetch error**: "Couldn't load chart data. Retry." with a retry button. Log the error to console with structured fields.

### 7. Inspect, don't navigate

Clicking a data point should **not** navigate or trigger a new fetch. Instead, surface the underlying period + value(s) in a small side panel or popover. Drill-down (year → quarter → month) is explicitly out of scope for the MVP, but the click handler scaffolding should be in place so a follow-up can wire it up.

### 8. URL state is the source of truth

All builder state (`metrics`, `chartType`, `normalize`, plus inherited filters) lives in the URL. Reload preserves the chart. Sharing a URL shares the exact view. No localStorage shadow state.

---

## Implementation

### Backend

0. **New trend matviews** — `src/lambda-functions/migrations/` (new migrations)
   - Three wide matviews, one per filter shape, each carrying every Builder metric as a column so `query_metrics` reads from a single relation with no joins and no live aggregation:
     - `mv_trend_catalog` — key `(granularity, period)`, catalog-wide
     - `mv_trend_by_genre` — key `(granularity, period, genre_slug)`
     - `mv_trend_by_tag` — key `(granularity, period, tag_slug)`
   - Each matview is built as a `UNION ALL` of four `DATE_TRUNC` SELECTs (week / month / quarter / year) over `games` filtered to `review_count >= 10` and `game_type='game'`. The `ea_flags` CTE from `find_ea_trend_rows` is folded in so EA metrics sit directly in the matview.
   - Columns: `granularity`, `period`, `[genre_slug | tag_slug]`, `releases`, `free_count`, `positive_count`, `mixed_count`, `negative_count`, `avg_steam_pct`, `avg_metacritic`, `avg_paid_price`, `free_pct`, `velocity_under_1`, `velocity_1_10`, `velocity_10_50`, `velocity_50_plus`, `mac_pct`, `linux_pct`, `deck_verified_pct`, `ea_count`, `ea_avg_steam_pct`, `non_ea_avg_steam_pct`.
   - **Two migration files**: one for `CREATE MATERIALIZED VIEW IF NOT EXISTS` (transactional), one marked `-- transactional: false` for the unique `CREATE INDEX CONCURRENTLY` statements. Unique indexes are required so future refreshes can use `REFRESH MATERIALIZED VIEW CONCURRENTLY`.
   - Add the three new view names to `analytics_repo.refresh_matviews()` so the existing post-ingest refresh path picks them up — no new cron, no new Lambda.
   - **Engagement (playtime) metrics are deferred out of v1.** The `index_insights` source + cross-source merge path will land in a follow-up; this PR ships the Builder lens with a single `trend_matview` source path to keep the implementation scoped.

1. **Metric registry** — `src/library-layer/library_layer/analytics/metrics.py` (new)
   - Pydantic `MetricDefinition` model: `id`, `label`, `description`, `category` (`volume` | `sentiment` | `pricing` | `velocity` | `early_access` | `platform`), `unit` (`count` | `pct` | `currency` | `score`), `source` (`trend_matview` — engagement/`index_insights` deferred), `column` (the column name in the source relation), `default_chart_hint` (`bar` | `line` | `stacked_area` | `composed`).
   - Module-level `METRIC_REGISTRY: dict[str, MetricDefinition]` with one entry per seed metric listed above.
   - Helper `get_metric(metric_id: str) -> MetricDefinition` that raises a clear error on unknown ids.

2. **Repository** — extend `analytics_repo.py`
   - New method `query_metrics(metric_ids: list[str], granularity: Granularity, filters: TrendFilters, limit: int) -> list[dict]`.
   - All v1 metrics share `source="trend_matview"`. Pick the right physical matview based on filters: no filter → `mv_trend_catalog`; `genre_slug` set → `mv_trend_by_genre WHERE genre_slug = %s`; `tag_slug` set → `mv_trend_by_tag WHERE tag_slug = %s`. Issue one SELECT with only the requested columns — no GROUP BY, no joins. (A future cross-source merge path will be added when engagement/`index_insights` metrics land.)
   - If both source groups are used, merge in Python (dict-of-period → row). If only one source is used (the common case), return directly without merging.
   - Filters honored: `genre`, `tag` (mutually exclusive in v1 — combined genre+tag returns 400). Advanced filters are a follow-up.
   - Return rows in `{"period": ..., "<metric_id>": value, ...}` shape.

3. **Service** — extend `analytics_service.py`
   - `trend_query(metrics: list[str], granularity: Granularity, filters: TrendFilters, limit: int) -> TrendQueryResult`.
   - Validates metric ids against the registry (raise on unknown — handler maps to HTTPException 400).
   - Validates Pro gating constraints if needed (or leaves it to the handler).
   - Calls `analytics_repo.query_metrics`, wraps the result with the metric metadata pulled from the registry.

4. **API handler** — `src/lambda-functions/lambda_functions/api/handler.py`
   - `GET /api/analytics/metrics` → returns `{ metrics: MetricDefinition[] }` from the registry. No params.
   - `GET /api/analytics/trend-query` → params: `metrics` (comma-separated), `granularity`, `limit`, `genre`, `tag`. Returns `{ periods: [...], metrics: [{id, label, unit, axis_hint}] }`.
   - Both routes are non-Pro at the API level — gating is enforced on the frontend (matches the rest of the analytics surface).

5. **Tests**
   - `tests/services/test_analytics_service.py`: trend-query with single metric, multi-metric, filter applied, invalid metric id (→ raises), unknown granularity (→ raises).
   - `tests/repositories/test_analytics_repo.py` (against `steampulse_test`): seed games + refresh matviews, assert `query_metrics` reads from the right `mv_trend_*` matview per filter shape and returns expected columns.
   - Handler test for both new routes: success path + 400 on unknown metric.

### Frontend

1. **API client** — `frontend/lib/api.ts`
   - `fetchMetricsCatalog(): Promise<MetricDefinition[]>` → `GET /api/analytics/metrics`.
   - `fetchTrendQuery(params): Promise<TrendQueryResult>` → `GET /api/analytics/trend-query`.

2. **Lens registration** — `frontend/lib/toolkit-state.ts`
   - Add a `builder` lens id to the `LENSES` list with label "Chart Builder".
   - Add lens-local URL state: `metrics` (string array), `chartType` (`bar` | `line` | `stacked_area` | `composed`), `normalize` (boolean).

3. **Builder lens** — `frontend/components/toolkit/lenses/BuilderLens.tsx` (new)
   - Layout: left rail with picker controls, right side with the chart and a small "selection summary" chip row.
   - Fetches the metric catalog once on mount; passes it into the picker components.
   - Reads selections from URL state, builds the trend-query request, fetches data, hands the result to the chart resolver.

4. **Picker components** — `frontend/components/toolkit/builder/` (new)
   - `MetricPicker.tsx` — multi-select chip list grouped by `category`. Free tier: 1 metric. Pro: multi-select up to 6. Keyboard-navigable. Each chip shows the metric label and a tiny unit badge (`#`, `%`, `$`).
   - `ChartTypePicker.tsx` — segmented control: bar / line / stacked area / composed. Disabled buttons stay visible with a `title=` tooltip explaining why (see chart compatibility rules in UX Principles).
   - `ChartResolver.tsx` — `(metrics, chartType, data, granularity) → JSX`. Implements the chart-type compatibility rules: validates the selection, falls back to a compatible type if needed (with a toast), routes to one of the four existing primitives in `frontend/components/trends/`, and passes the colorblind-safe `BUILDER_PALETTE`. Mixed-unit selections automatically route to dual-axis composed.
   - `palette.ts` — exports `BUILDER_PALETTE` (Okabe-Ito or Tableau 10 colorblind-safe). All chart primitives in the builder lens must use this palette explicitly.
   - `EmptyState.tsx`, `LoadingSkeleton.tsx`, `ErrorState.tsx` — the three non-happy-path states described in UX Principles §6.

5. **Pro gating**
   - Use the existing `useIsPro` hook.
   - Free: 1 metric, granularity restricted to month/quarter/year, no normalization toggle, all 4 chart types available (it's the metric count that's gated, not the chart shape).
   - Pro: full picker (multi-metric up to ~6, week granularity, normalization toggle).
   - Match the blur + upgrade-link pattern from `TrendsLens.tsx`.

6. **Tests** — `frontend/tests/builder-lens.spec.ts` (new)
   - Mock `/api/analytics/metrics` and `/api/analytics/trend-query` in `frontend/tests/fixtures/api-mock.ts`.
   - **Smart default**: load the lens with no URL params, assert a default metric is pre-selected and a chart renders (no empty state).
   - **Empty state**: load with explicitly empty `metrics`, assert the empty state renders.
   - **Pick a metric**: assert URL updates and chart renders.
   - **Switch chart type**: assert chart re-renders without re-fetching (cache hit).
   - **Compatibility rule**: select two metrics with different units, assert chart type auto-routes to dual-axis composed and the stacked-area button is disabled with a tooltip.
   - **Apply a filter** (genre): assert URL updates and a new fetch fires.
   - **Pro gating**: as a free user, assert metric picker is capped at 1 and week granularity is hidden.
   - **Accessibility**: assert all picker controls are keyboard-navigable (tab + arrows + space).
   - **Error state**: mock a 500, assert the error state with retry renders.

---

## Out of Scope (explicit non-goals)

- No new physical tables (the three new entries are matviews only; no schema changes to `games`, `reviews`, etc.).
- No multi-game cross-aggregation (the Compare lens handles that).
- No "save chart" / dashboards / persisted views beyond URL state.
- No drill-down (click year → quarter); list as follow-up.
- No NL→SQL chat — that's the `/api/chat` v2 work.
- No filter extension on existing trend endpoints — `/api/analytics/trend-query` is the only new backend surface.

---

## Verification

1. **Backend unit tests** (`poetry run pytest -v`)
   - Service-level: `tests/services/test_analytics_service.py::test_trend_query_*`
   - Repo-level (steampulse_test DB): `tests/repositories/test_analytics_repo.py::test_query_metrics_*`
   - Handler-level: success + 400 on unknown metric.

2. **Local API smoke**
   ```bash
   ./scripts/dev/start-local.sh
   ./scripts/dev/run-api.sh
   curl 'http://localhost:8000/api/analytics/metrics' | jq
   curl 'http://localhost:8000/api/analytics/trend-query?metrics=releases,avg_steam_pct&granularity=month&limit=24' | jq
   curl 'http://localhost:8000/api/analytics/trend-query?metrics=releases&granularity=month&limit=12&genre=Indie' | jq
   ```

3. **Frontend Playwright** (`cd frontend && npm run test:e2e -- builder-lens`)

4. **Manual UX check**
   ```bash
   cd frontend && npm run dev
   ```
   Navigate to the toolkit, switch to the Builder lens, exercise the pickers as a free user and as a Pro user (stub via dev flag), verify gating, verify URL state persists across reload.

---

## Critical Files

### New
- `src/lambda-functions/migrations/00NN_add_trend_matviews.sql`
- `src/lambda-functions/migrations/00NN+1_add_trend_matview_indexes.sql` (transactional: false)
- `src/library-layer/library_layer/analytics/metrics.py`
- `frontend/components/toolkit/lenses/BuilderLens.tsx`
- `frontend/components/toolkit/builder/MetricPicker.tsx`
- `frontend/components/toolkit/builder/ChartTypePicker.tsx`
- `frontend/components/toolkit/builder/ChartResolver.tsx`
- `frontend/tests/builder-lens.spec.ts`

### Modified
- `src/lambda-functions/lambda_functions/api/handler.py` — add 2 routes
- `src/library-layer/library_layer/services/analytics_service.py` — add `trend_query`
- `src/library-layer/library_layer/repositories/analytics_repo.py` — add `query_metrics`, register new matviews in `refresh_matviews()`
- `src/library-layer/library_layer/schema.py` — document new matviews
- `frontend/lib/api.ts` — add 2 fetchers
- `frontend/lib/toolkit-state.ts` — register lens, add URL params
- `frontend/tests/fixtures/api-mock.ts` — add 2 mock endpoints
