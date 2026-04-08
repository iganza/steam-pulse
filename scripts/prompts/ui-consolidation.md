# UI Consolidation — Analytics, Toolkit, Compare, Game Page

**Status:** implemented. This document reflects the final design and the facts that drove it. Keep it accurate — it's the reference for anyone revisiting this area.

## Background

Originally: `/analytics`, `/toolkit`, and `/compare` coexisted as three top-level analysis surfaces, plus the game detail page had its own sentiment/compare/benchmark lens tabs. Users couldn't tell where to click, and every new chart triggered a "does this go in analytics, toolkit, or the game page?" debate.

## Actual architecture (the thing the original framing got wrong)

The three routes were **not** three independent codebases. They were all the same shared `ToolkitShell` + lens engine with different default lenses and visible lens subsets:

- `components/toolkit/ToolkitShell.tsx` — single lens engine.
- 7 lenses in `components/toolkit/lenses/`: `trends`, `builder`, `market-map`, `explorer`, `sentiment` (drill), `compare`, `benchmark`.
- `/analytics` → default `trends`, visible `[trends, builder, market-map, explorer]`.
- `/toolkit`   → default unset, visible = **all 7** (zero tests ever existed for this route).
- `/compare`   → default `compare`, visible `[compare, sentiment, benchmark]`.
- `/genre/[slug]` and `/tag/[slug]` → ToolkitShell with `[explorer, market-map, trends]` (unchanged by this work).
- `/games/[appid]/[slug]` → ToolkitShell with `lockedFilters={appids:[X]}`, visible `[sentiment, compare, benchmark]`, sentiment lens content overridden by the full long-form `GameReportClient`. Lens tabs were visible on a single-game page, which was the biggest source of in-game confusion.
- `BenchmarkLens.tsx` → a 9-line "under construction" stub. The only working benchmark was `components/game/CompetitiveBenchmark` rendered inline on the game page.
- Only three internal hrefs pointed at `/analytics`, `/toolkit`, `/compare` — all in `components/layout/Navbar.tsx`. The "Compare with…" CTA at `GameReportClient.tsx:186` deep-linked to `/compare?appids=...`.
- `frontend/next.config.ts` had `headers()` and `rewrites()` but **no `redirects()`** — this work added the first one.

That reframing made the fix mostly about route semantics, lens visibility, naming, and deleting dead code — not a rewrite.

## Decisions

1. **Canonical catalog route name: `/explore`.** Neutral, action-oriented, matches BI/market-intel conventions (Amplitude, Mode). `/analytics` and `/toolkit` 308-redirect here.
2. **`BenchmarkLens.tsx`: deleted.** The inline `CompetitiveBenchmark` on the game page remains the only "this vs cohort" surface. Re-introduce later if demand appears.
3. **Game page: `ToolkitShell` wrapper fully removed.** Renders as a clean long-form doc; no lens tab bar; no multi-lens illusion on a single-entity page.
4. **Two top-level analysis surfaces, not three:** `/explore` (catalog-wide) and `/compare` (N-game workspace). Entity pages are a third surface by nature but are not a top-nav peer.
5. **"Compare with…" CTA** at the top of the game page is the **only** path from an entity page to multi-game compare.
6. **The word "drill" is retired** from user-facing UI. Internal jargon.

## Final IA

| Purpose | Route | Default lens | Visible lenses |
|---|---|---|---|
| Catalog explorer | `/explore` | `trends` | `[trends, builder, market-map, explorer]` |
| Compare workspace | `/compare` | `compare` | `[compare]` |
| Entity detail | `/games/[appid]/[slug]` | — | no lens tabs; long-form doc |

Nav top-level: **Explore** + **Compare** (plus the existing Browse/Hidden Gems/New/Trending/Pro links which are unrelated to this consolidation).

Game page section order (all one page, no tabs):
1. **Overview** — hero, verdict (with "Compare with…" CTA), quick stats, market reach, about
2. **Analysis** — all LLM narrative sections (design strengths, friction, audience, sentiment trend, genre context, promise gap, wishlist, churn triggers, dev priorities, competitive context)
3. **Trends & Benchmarks** — sentiment timeline, playtime × sentiment, inline cohort benchmark, tags, GameAnalyticsSection (audience overlap, playtime deep dive, early access impact, review velocity, top reviews)

## What does / does not belong where (mental model)

- **"One game over time"** → Trends & Benchmarks on the game page. Not a lens elsewhere.
- **"One game vs its cohort"** → inline `CompetitiveBenchmark` on the game page. Not a standalone lens.
- **"N named games side by side"** → `/compare` workspace.
- **"Patterns across the whole catalog"** → `/explore` with its four lenses.
- **"One game vs another named game, from an entity page"** → "Compare with…" CTA → `/compare?appids=...`.

If a new feature doesn't fit one of those five sentences, stop and reconsider before adding it.

## Scope boundaries (kept tight on purpose)

- No new charts, no new API endpoints, no backend changes.
- No visual redesign (colors, typography, spacing) beyond what the IA change required.
- Pro paywall boundaries unchanged.
- `/genre/[slug]`, `/tag/[slug]`, `/developer`, `/publisher` untouched — they already use a sensible lens subset.
- Saved comparisons and shareable compare URLs beyond `?appids=` — deferred.

## Research notes (abbreviated)

The "three analysis surfaces" model comes from BI / market-intel convention:
- **BI dashboards** (Amplitude, Mode, Metabase) separate "explore the dataset" from "drill into one entity" cleanly — usually a global explorer + an entity detail view.
- **Market-intel products** (SimilarWeb, SteamDB, Gamalytic) keep entity pages as long-form documents and pull comparison out to a separate workspace when more than one entity is involved.
- **Compare vs Benchmark** is a real distinction: benchmark = "this vs cohort (unnamed aggregate)," compare = "this vs N specific named peers." Conflating them confuses users. We resolved by keeping benchmark inline on entity pages (where cohort context lives) and making compare a standalone workspace.

Naming: "Explore" beats "Analytics" because "Analytics" gets read as "dashboards" (a specific product category) and beats "Toolkit" because "Toolkit" is internal jargon with no user-facing meaning.

## Files touched (for reference when revisiting)

- `frontend/next.config.ts` — added `redirects()` with 308s for `/analytics` and `/toolkit`
- `frontend/app/explore/page.tsx` — new
- `frontend/app/analytics/page.tsx` — deleted
- `frontend/app/toolkit/page.tsx` — deleted
- `frontend/app/compare/page.tsx` — narrowed `visibleLenses` to `[compare]`
- `frontend/app/games/[appid]/[slug]/GameReportClient.tsx` — removed ToolkitShell wrapper
- `frontend/components/layout/Navbar.tsx` — 3 analysis links collapsed to 2 (Explore + Compare)
- `frontend/components/toolkit/lenses/BenchmarkLens.tsx` — deleted
- `frontend/lib/lens-registry.ts` — removed benchmark lens entry, label pass
- `frontend/tests/*.spec.ts` — route updates + redirect tests

## If you're revisiting this

Before adding anything to `/explore`, `/compare`, or the game page, ask the five-sentence question above. If you're tempted to re-add a "benchmark lens" or a "sentiment drill lens" at the top level, re-read the Research Notes section — that shape was tried and rejected.
