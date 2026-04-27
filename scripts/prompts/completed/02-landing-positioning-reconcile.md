# Reconcile Landing Page With Positioning Spec

## Context

The canonical landing-page spec is
`scripts/prompts/completed/landing-page-positioning.md` (Apr 15, 2026).
It was implemented correctly that day, then drifted on Apr 23 (commit
`ac93b96`, `feature/soft-launch-prep`) when `FeaturedReport` (the genre
synthesis CTA for the wedge) was bolted in above the intelligence cards
without revising the spec.

The drift produced two compounding problems:

1. **Above-fold competition**: `FeaturedReport` (a sales CTA pointing at
   `/genre/roguelike-deckbuilder`) sits between the hero and the "What
   You Get" intelligence cards. Per the spec the universal-intelligence
   preview is meant to land before any wedge-specific CTA. Two heroes,
   neither dominant.
2. **Fragile data path**: the 4 `IntelligenceCards` and the 3-game
   `GameShowcase` both depend on a 9-call SSR fan-out (3 games × {report,
   review-stats, audience-overlap}). Cold-start windows on the API
   Lambda push individual calls past the 25 s SSR timeout, the SSR
   captures empty data, ISR's `stale-while-revalidate=2592000` keeps
   serving the empty version. Verifiable: live HTML at
   `https://d1mamturmn55fm.cloudfront.net/` contains zero showcase
   markers.

Prompt **`01-landing-hero-unified.md`** ships the bug fix: drops the
9-call fan-out, replaces the standalone `GameShowcase` with a
lightweight 3-game strip embedded in `FeaturedReport`, and removes
`IntelligenceCards` from render (component file kept on disk). That
ships a working homepage but **deviates from the positioning spec** by
not rendering the 4 intelligence cards or the "For Game Developers"
section.

This prompt is **the second half**: bring the homepage back into
alignment with the spec, while preserving the bug-fix-friendly data
path established in 01.

## Pre-conditions

- 01-landing-hero-unified.md is **merged** before starting this prompt.
  The data-path simplification in 01 (single `getGamesBasics` call) is
  the foundation this prompt builds on.
- Live homepage shows the unified `FeaturedReport` card with the 3-game
  strip (BG3 / Stardew / Cyberpunk) and works without empty renders.

## Goal

Restore full alignment with `landing-page-positioning.md` while keeping
the resilient data path. Specifically:

1. Re-introduce the 4-card "What You Get" intelligence preview, with a
   sustainable (non-fragile) data source.
2. Add the missing **"For Game Developers"** section.
3. Resolve the above-fold competition between `FeaturedReport` and the
   intelligence cards by deciding render order with the spec in hand.
4. Keep the discovery rows where they are (per spec, Section 5 — they
   stay, just moved DOWN, which they already are).

## Free-vs-paid alignment

Same rules as before: free synthesis stays free; the $499 Atlas PDF is
the paid layer. "For Developers" CTA points to `/pro` (waitlist /
sub signup), which is the next paid surface. See
`memory/feedback_packaging_principle.md` and
`memory/project_business_model_2026.md`.

## Design

### 1. Sustainable data source for `IntelligenceCards`

The original cards used **showcase game 0**'s data (timeline, overlaps,
report) plus an analytics trend fetch. That coupled the cards to the
fragile per-game fan-out. Replace it with a precomputed homepage
intel snapshot.

**Backend — new endpoint**:
`GET /api/home/intel-snapshot`

Returns a single payload covering the 4 cards, refreshed daily by a new
matview / scheduled job. Suggested shape:

```json
{
  "sentiment_sample": {
    "appid": 1086940,
    "name": "Baldur's Gate 3",
    "timeline": [{"period": "2025-W01", "positive_pct": 95.2}, ...]
  },
  "overlap_sample": {
    "appid": 1086940,
    "overlaps": [{"appid": 413150, "name": "Stardew Valley", "overlap_pct": 18.4}, ...]
  },
  "trend_sample": {
    "periods": [{"period": "2025-12", "positive_pct": 81.3}, ...]
  },
  "report_sample": {
    "appid": 1086940,
    "name": "Baldur's Gate 3",
    "one_liner": "...",
    "design_strengths": ["...", "..."]
  },
  "computed_at": "2026-04-26T03:00:00Z"
}
```

Implementation options (pick the lightest):

- **Option A — direct DB pulls behind one endpoint** (recommended for
  v1). The endpoint reads existing tables/matviews:
  - `mv_review_velocity` or weekly_sentiment for timeline
  - `mv_audience_overlap` for overlaps
  - `mv_analytics_trend_sentiment` for trend
  - `reports` table for the report sample (BG3 specifically)
  Single round-trip, ≤200 ms warm. Cache-Control: `public,
  s-maxage=21600, stale-while-revalidate=86400` (6 h).
- **Option B — new matview** `mv_home_intel_snapshot` that pre-joins
  these. Adds a refresh job to existing cron infra. Worth it only if
  Option A is measurably slow — start with A.

Pick A. Document B as the upgrade path in code comments.

**Frontend — `frontend/lib/api.ts`**: add `getHomeIntelSnapshot()` with
`next: { revalidate: 21600, tags: ["home-intel"] }`.

### 2. Re-introduce `IntelligenceCards`

The component already exists at `frontend/components/home/IntelligenceCards.tsx`
and renders the 4 cards correctly per spec. It just needs a different
data source.

- Update `IntelligenceCardsProps` to accept the snapshot shape from §1
  instead of `(timeline, overlaps, trendData, report)`.
- Internals stay the same — `MiniSentimentChart` / `MiniOverlapList` /
  `MiniTrendLine` / report-snippet.
- All four cards always render; if a sub-field is missing the affected
  card shows a graceful empty state ("Sample updates daily" or similar)
  rather than the whole block disappearing.

### 3. Add the "For Game Developers" section

Spec lines 223–242. New component:
`frontend/components/home/ForDevelopers.tsx`.

Content (verbatim from spec where it specifies copy):

- **Eyebrow**: `For game developers` (small, mono, uppercase, teal)
- **Headline**: "Built for the people who make games"
- **Three value props** (each a small card or row, no mini-viz needed
  unless trivial — keep this section text-forward):
  - **Understand your players** — review intelligence, sentiment trends,
    playtime analysis, churn detection
  - **Know your competition** — audience overlap shows which games your
    reviewers actually play
  - **Read the market** — genre trends, pricing analysis, release
    timing, platform coverage
- **CTA**: button-style link, "Join the Pro waitlist →", `href="/pro"`

Visual treatment matches the existing card chrome (`var(--card)`,
`var(--border)`, rounded-2xl). Use a single full-width container with
the three value props in a `grid-cols-1 md:grid-cols-3` layout inside.

**Constraint from spec line 241–242**: "Only describe features that are
live. Don't promise the 16 data-intelligence features from the roadmap
until they ship. Credibility > hype." The copy above sticks to live
capabilities.

### 4. Render order in `frontend/app/page.tsx`

After this prompt, the section order should be:

1. Hero (existing)
2. **`FeaturedReport`** (with embedded 3-game strip from prompt 01) —
   wedge soft-launch CTA. The spec didn't explicitly call this out, but
   it's now a deliberate addition: "we just finished a deep study of
   this genre" anchors the depth signal *and* it's the highest-value
   conversion surface today (Atlas PDF upsell on click-through).
3. **`IntelligenceCards`** ("What You Get") — universal intelligence
   preview, 4 cards, snapshot-driven (per §1)
4. `MarketTrendsPreview` (existing)
5. Discovery rows: Most Popular / Top Rated / Hidden Gems / New / Just
   Analyzed (existing — already in correct position per spec)
6. **`ForDevelopers`** — new
7. Browse by Genre / Tag (existing)
8. `FooterCTA` (existing)

Note that `FeaturedReport` is at slot 2, `IntelligenceCards` at slot 3.
The spec puts intelligence cards at slot 2 with no FeaturedReport.
We're keeping the wedge CTA at slot 2 because:

- It's the active monetization surface (per
  `memory/project_business_model_2026.md` Phase B/C)
- The 3-game strip inside it now serves the breadth-anchor role the
  standalone showcase used to fill
- Pushing it below the cards risks burying the wedge

If reviewer feedback prefers strict spec compliance, swap the order —
trivial reorder, no API changes.

### 5. Keep `GameShowcase` deleted from render path

01 already removed it from render. Decision for this prompt: **also
delete the file** (`frontend/components/home/GameShowcase.tsx`) once
the `FeaturedReport` strip + restored `IntelligenceCards` cover the
spec's intent. The standalone full-stack showcase is no longer needed
— the strip is a lighter version of the same idea, and the
`IntelligenceCards` cover the "what you get" scan.

If the team disagrees and wants to revive `GameShowcase` later, the
git history has it (and the spec at line 171 documents it).

## Acceptance criteria

1. Live homepage renders all four intelligence cards (Player Sentiment,
   Competitive Intelligence, Market Intelligence, Deep Review Reports)
   with mini-visualizations populated from `/api/home/intel-snapshot`.
2. Live homepage renders the "For Game Developers" section with the
   three value props and `/pro` CTA.
3. Section order matches §4 above.
4. SSR call count remains ≤10 (one extra call for `home-intel`,
   replacing nothing in 01's lean baseline).
5. Cold-start failures no longer produce empty-render captures: even if
   `home-intel` times out, each individual card renders its empty state
   gracefully and the rest of the page is intact.
6. No "AI", "discover" (as primary verb), "revolutionary", or
   "game-changing" appears in any new copy. Vocabulary audit per spec
   lines 290–296.
7. New endpoint `/api/home/intel-snapshot` has tests covering the
   happy path and the partial-data fallback.
8. New component `ForDevelopers` is referenced only from `page.tsx`
   (no other importers expected — keep scope local).

## Out of scope

- CloudFront cache policy for `/api/*` (still `CACHING_DISABLED`; design
  intent per `game-report-cache-invalidation.md` is that Next.js fetch
  cache + ISR is the cache layer, with API authoritative).
- Lambda cold-start tuning.
- Splitting the wedge CTA from a generic "studied genres" carousel
  (would require multiple synthesized genres; today there's one wedge).
- Any change to `/genre/[slug]/`, `/games/[appid]/[slug]/`, or
  navigation labels.
- The "developer landing → /pro" funnel itself (waitlist signup,
  Stripe wiring, etc. — separate prompts).
