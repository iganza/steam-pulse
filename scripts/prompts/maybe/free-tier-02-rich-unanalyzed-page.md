# Free Tier 02 — Rich unanalyzed game page (render every available signal)

## Parent prompt
Decomposed from `scripts/prompts/exploration/unanalyzed-game-free-tier.md` (section "The free page — anatomy of every game"). Renders the data layer surfaced by `free-tier-01-review-clusters-sklearn.md`.

## Context

Today's unanalyzed game page (`frontend/app/games/[appid]/[slug]/GameReportClient.tsx`) is a stub: header, basic stats, market-reach card, "Request Analysis" CTA. Visitors have very little reason to stay on the page or trust SteamPulse as a source.

This prompt refactors the page to **render every signal already available from automated processes**, so the unanalyzed surface becomes substantively rich on its own — no LLM analysis required, no manual curation, no cost per game.

Explicitly **out of scope here**: tier-aware rendering, locked sections, paywalls, `analysis_state` enum, Decision Pack CTAs, Stripe wiring. Those are packaging decisions, deferred until we see how rich the automated surface actually got. Per memory `feedback_packaging_principle`: the publishable insight comes first; packaging follows.

## What to do

### 1. Audit available signals

Inventory what data the existing API already exposes for unanalyzed games:

- Header / Steam metadata (name, dev, publisher, release, price, tags, header image)
- Aggregate review stats (count, positive %, recent vs all-time)
- `hidden_gem_score` denormalized column (badge)
- `mv_audience_overlap` matview (top neighbors)
- `getReviewStats` API: weekly sentiment timeline + playtime histogram
- `getBenchmarks` API: cohort comparisons
- `find_top_reviews` (top helpful reviews)
- **New**: `review_clusters` from `free-tier-01` — the "What reviewers emphasize" data

If any of these aren't fetched in the unanalyzed code path today, wire them in.

### 2. Refactor `GameReportClient.tsx`

Restructure the unanalyzed path to render this layout (mirroring the doc's `## The free page` anatomy, minus the locked sections):

```
HEADER
  - Image, title, dev, sentiment, price, release, tags
  - Hidden Gem badge (if score qualifies)

AT A GLANCE
  - Sentiment trend (90d direction + delta) — from getReviewStats
  - Review velocity (current vs cohort median) — from getBenchmarks if available
  - Engagement signal (playtime distribution top stat) — from getReviewStats

WHAT REVIEWERS EMPHASIZE (new)
  - All themes from review_clusters: label, mention count, sentiment %
  - 1–3 representative quotes per theme with playtime + helpful-vote context
  - Tag votes (top 6) as a complement

TOP REVIEWS
  - Top 3 positive + top 3 negative by helpful votes
  - Playtime + helpful-vote context per review

COMPETITIVE LANDSCAPE
  - Top 5 audience-overlap competitors from mv_audience_overlap
  - Per row: overlap %, sentiment, price

PLAYTIME / SENTIMENT CHART
  - Existing PlaytimeChart + sentiment heatmap (already rendered for analyzed games — extend to unanalyzed)
```

Each section renders fully — no `<LockedSection>` wrappers, no teasers, no CTAs other than the existing `RequestAnalysis` button (kept as-is).

### 3. Component reuse

The analyzed-game path already has many of these components (`QuickStats`, `MarketReach`, `PlaytimeChart`, `RelatedAnalyzedGames`, `SentimentTimeline`). Where possible, reuse them on the unanalyzed path rather than building parallel ones — they're presentational and don't require an LLM `GameReport` to function.

Most likely refactor: the analyzed/unanalyzed branch in `GameReportClient.tsx` collapses substantially. Many sections move from "analyzed only" to "always render". Only the **LLM-prose sections** (Design Strengths, Gameplay Friction, Audience Profile, Dev Priorities, Competitive Context, Genre Context) remain analyzed-only.

### 4. New component: `ReviewThemes`

Add `frontend/components/game/ReviewThemes.tsx` rendering the `review_clusters` payload from `free-tier-01`. Visual design: each theme as a card with label, sentiment chip, mention count, and 1–3 quote pull-outs. No interactive expand/collapse needed — render everything.

### 5. SEO floor (basic)

Per the exploration doc: every page needs ≥500 unique words from real data. With the new layout, count words on a representative unanalyzed game page in dev. If under 500, expand the at-a-glance and lifecycle copy with more matview-derived numeric content (not filler text).

Note: full SEO hardening (schema.org markup, canonical tags, sitemap regeneration) is deferred — that's downstream packaging-adjacent work.

### 6. TF-IDF / RAKE keywords (optional bonus)

Cheap, no ML deps beyond what `free-tier-01` adds. `TfidfVectorizer` over a game's review corpus + multi-word phrase extraction = "Reviewers emphasize: [keyword chips]". Surface as a complement to themes, not a replacement.

If it adds complexity to the prompt scope, defer to a follow-up.

## Files to modify / create

| Path | Change |
|------|--------|
| `frontend/app/games/[appid]/[slug]/page.tsx` | Ensure all signal-fetching APIs are called for unanalyzed games (audit + wire) |
| `frontend/app/games/[appid]/[slug]/GameReportClient.tsx` | Refactor: many sections move from analyzed-only to universal |
| `frontend/components/game/ReviewThemes.tsx` | New component for the cluster section |
| `frontend/lib/types.ts` | Add `ReviewCluster` type |
| `frontend/lib/api.ts` | Wire any newly-needed fetches |

## Out of scope

- No `<LockedSection>` primitive, no `<DecisionPackCTA>` component, no tier-aware logic
- No `games.analysis_state` migration
- No new API endpoints beyond what `free-tier-01` adds — only consumption
- No Stripe wiring, no PDF generation, no SEO schema markup
- No data-intelligence-roadmap features (Health Score breakdown, archetype profile sheet, hedonic pricing, survival curves, anomaly detection) — those have their own roadmap; render them when they ship

## Dependencies

- **Hard**: `free-tier-01-review-clusters-sklearn.md` shipped (the `review_clusters` API payload exists)
- **Soft**: existing matviews (`mv_audience_overlap`, etc.) and existing API endpoints (`getReviewStats`, `getBenchmarks`)

## Verification

- Visit a known unanalyzed wedge game in dev — page is substantively richer than today: themes section, top reviews, audience overlap, sentiment timeline all render
- Visit a known analyzed game — same universal sections render plus the existing LLM-prose blocks; no regressions
- Word count on unanalyzed pages ≥ 500
- Frontend `npm run build` succeeds; no broken types
- Spot-check page in browser at multiple viewports for layout integrity
