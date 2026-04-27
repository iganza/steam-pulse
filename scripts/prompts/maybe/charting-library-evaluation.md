# Charting Library Evaluation — Future Migration

Notes captured on 2026-04-16 while building the interactive Market Trends
preview on the homepage. The immediate scope was small (an expand-to-modal
chart with ~17–200 points) but the roadmap calls for many interactive
analytics charts across `/explore`, `/pro`, genre pages, developer pages,
and the chat answer view. This doc captures why Recharts — our current
charting library — is unlikely to scale to that roadmap, and what the
replacement options look like.

---

## What prompted this

While implementing the expand-to-modal feature for `MarketTrendsPreview`,
the modal chart (using `TrendStackedArea` + `TrendBarChart` with
~100–200 points at 450px height) was visibly laggy on mouse hover. We
applied the standard Recharts perf escape hatches:

- `isAnimationActive={false}` on `<Area>` / `<Bar>` / `<Line>` (entrance animation)
- `isAnimationActive={false}` on `<Tooltip>` (slide-between-positions animation)
- `throttleDelay={50}` on the chart container (cap mouse-move event rate)
- Memoized the normalization computation inside `TrendStackedArea`

See git log for commits touching `frontend/components/trends/TrendStackedArea.tsx`
and `frontend/components/trends/TrendBarChart.tsx` — these perf props were
added as optional `animate` arguments so other callers are unaffected.

Result: still laggy. The root cause is Recharts' SVG-based architecture —
every hover triggers React reconciliation across the chart tree, and the
cursor crosshair element is a DOM element that repositions on every move.

**Decision:** removed the expand-to-modal feature entirely from
`MarketTrendsPreview` for now. Inline 180px preview charts keep working
fine (small point counts, no heavy interactivity). Revisit when we pick
a new charting library.

---

## Where Recharts is fine vs. where it breaks

| Use case | Recharts verdict |
|---|---|
| Homepage inline preview (180px, ≤50 points) | Fine — keep using |
| IntelligenceCards mini sparklines | Fine — keep using |
| Game page mini charts | Fine for current point counts |
| `/explore` TrendsLens (100+ points, filters, crossfilter) | Already feels heavy; will get worse |
| `/pro` dense dashboards (planned) | Will not scale |
| Large release-volume or sentiment-over-time with 500+ points | Unusable |

The rule of thumb: **Recharts is fine up to ~50–100 data points with
interactive tooltips. Past that, it degrades fast.**

---

## Options evaluated

| Library | Renderer | Interactive ceiling | Bundle | React ergonomics | Cost |
|---|---|---|---|---|---|
| **Recharts** (current) | SVG + React | ~100 pts | ~100KB gz | Excellent | Free |
| **Apache ECharts** | Canvas | 10k+ pts | ~500KB gz (tree-shakeable) | Good via `echarts-for-react` | Free (Apache 2.0) |
| **uPlot** | Canvas | 100k+ pts | ~40KB gz | Manual — no official React wrapper | Free (MIT) |
| **Plotly.js** | WebGL/Canvas | 100k+ pts | ~3MB gz | Good via `react-plotly.js` | Free (MIT); bundle is a problem |
| **Highcharts** | SVG/Canvas | 10k+ pts | ~200KB gz | Good | **Commercial license required** |
| **Visx + custom canvas** | Canvas | 100k+ pts | Depends on usage | Excellent (D3 primitives) | Free |
| **Observable Plot** | SVG | ~100 pts | ~100KB gz | OK | Free — but same SVG ceiling as Recharts |

### Recommendation

**Primary: Apache ECharts.**

- Right perf shape — canvas renderer comfortably handles the data density we'll actually ship.
- Mature interaction primitives out of the box: zoom, brush, crossfilter, legend toggle, dataZoom slider.
- Broad chart vocabulary: stacked area, bar, line, scatter, heatmap, treemap, sankey, sunburst, geo, boxplot, candlestick. This matches our roadmap (revenue estimator scatters, genre share treemap, platform heatmap, etc.).
- Used at analytics-dashboard scale by Alibaba, Airbnb, and many others — well understood operationally.
- Bundle is tree-shakeable; we can start with just the chart types we use.

**Keep Recharts for:** homepage inline previews, sparklines, small
≤50-point widgets. Already loaded, looks great at small sizes, no reason
to migrate these.

**Do not pursue:** Plotly (bundle too heavy — this alone would tank our
landing-page LCP), Highcharts (license cost without matching revenue).

### Why not uPlot?

uPlot is the performance champion — 100k points in 3ms, 40KB bundle. But:

- No official React wrapper; we'd maintain our own integration.
- API is lower-level than ECharts — more work per chart type.
- Limited to time-series-ish charts. Doesn't cover heatmaps, sankeys, treemaps, geo.

Good fallback if ECharts proves too heavy for a specific view, but not
the primary choice for our catalog breadth.

---

## Migration strategy (when we pick this up)

1. **Pick a single pilot view.** Good candidate: `/explore` TrendsLens
   or the planned Pro dashboard. Port one complete view to ECharts to
   validate ergonomics, bundle impact, and perf.
2. **Establish chart primitives.** Wrap ECharts in a thin set of
   SteamPulse-styled components that match the current `TrendStackedArea`
   / `TrendBarChart` / `TrendBarChart` APIs. Keep call sites stable.
3. **Design-system alignment.** Port our color tokens (`--teal`, `--positive`,
   etc.), font-mono tick labels, dashed grid, and card-style tooltips
   into an ECharts theme object. Apply it globally so charts feel
   consistent with the rest of the site.
4. **Migrate view-by-view.** Homepage inline previews stay on Recharts
   until the very end (or indefinitely). Convert the data-dense views
   first where the pain is.
5. **Revisit the expand-to-modal feature.** Once ECharts is in, the
   homepage modal chart becomes trivial (ECharts has a built-in
   `dataZoom` slider that arguably replaces the modal entirely). See
   commit history for the code we removed — the state management
   (granularity state, AbortController fetch pattern, seeded modal data)
   is worth reusing.

---

## What was removed

Git history has the full implementation but for reference:
`frontend/components/home/MarketTrendsPreview.tsx` previously had:

- `expandedChart` / `modalGranularity` / `modalSentimentData` /
  `modalReleaseData` / `modalLoading` state
- A Dialog-based modal rendering `TrendStackedArea` / `TrendBarChart`
  at 450px height
- A second `useEffect` fetching modal data on granularity change with
  seeding-from-inline when granularities matched
- `Maximize2` expand buttons on each chart card

The granularity toggle on the inline view is kept — that works fine
on ~17-point year data and provides some interactivity without the
hover-perf cliff.

---

## Related context

- `scripts/prompts/interactive-market-trends-homepage.md` — original spec
  for the feature. The "expand modal" section is now deferred to the
  post-migration world.
- `frontend/components/trends/TrendStackedArea.tsx`,
  `frontend/components/trends/TrendBarChart.tsx` — perf escape hatches
  (`animate` prop, memoized normalization) stay in place; they help
  somewhat and don't cost anything at small point counts.
