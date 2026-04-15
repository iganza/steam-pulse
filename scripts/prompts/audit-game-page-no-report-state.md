# Audit & enrich per-game page when no LLM report exists

## Context

Soft-launch strategy requires that **every per-game page is
index-worthy by Google's standards even without an LLM-synthesised
report**, since most of the ~6,000 games in the catalog won't have
reports at launch (only the top 200 by review_count + the 141
roguelike-deckbuilder wedge — see `steam-pulse.org` → "Wedge Strategy"
and the "Soft-launch architecture" notes).

Google's Aug + Dec 2025 Scaled Content Abuse policy updates penalise
sites that ship sparse pages; the bar is "unique data + distinct
user query," not "deep AI narrative." Comparable sites (SteamDB,
HowLongToBeat, ProtonDB, Backloggd) rank tens of thousands of game
pages on structured data alone with no LLM. SteamPulse can do the
same — *if* the no-report template is rich enough.

This prompt has two phases: **audit** the current state of the
no-report rendering, then **enrich** sections that don't carry
their own analytical weight.

## Phase 1 — Audit

Read `frontend/app/games/[appid]/[slug]/page.tsx` and every
component it imports from `frontend/components/game/`. Map every
section of the page (`<h2>`/`<section>`/card) to one of:

| Status     | Meaning                                                              |
|------------|----------------------------------------------------------------------|
| **A**      | Renders rich content from non-report data (Steam, matviews) — keep   |
| **B**      | Renders thin/empty content when `report=null` — needs enrichment     |
| **C**      | Hidden cleanly when `report=null` — keep, no work needed             |
| **D**      | Renders an empty section header / "N/A" placeholder — fix to be C or B-then-A |

Output the audit as a markdown table at the top of the
implementation PR description so the diff that follows is justified.

## Phase 2 — Enrich

For every B and D section, do one of:

**Option 1 — hide the section cleanly when null** (status → C):
- Best for sections that are *fundamentally* about LLM synthesis
  (`gameplay_friction`, `dev_priorities`, `churn_triggers`,
  `audience_profile`).
- React: `{report?.section ? <Section /> : null}`.

**Option 2 — replace with a structured-data fallback** (status → A):
- Best for sections that have a meaningful no-report rendering using
  data already in `games`, `reviews`, or matviews.
- Examples (cite the existing repo/matview each pulls from):
  - **Genre-relative ranking**: "Top 18% sentiment in Roguelike
    (vs. 124 games with 500+ reviews)" — from `mv_genre_*` matviews.
  - **Audience overlap mini-card**: top 5 games with highest reviewer
    overlap — from existing `/api/games/{appid}/audience-overlap`
    endpoint.
  - **Review velocity sparkline**: monthly review volume trend (24
    months) — from existing `/api/games/{appid}/review-velocity`.
  - **Price context**: "$X (vs. genre median $Y)" — from
    `mv_price_summary` or `analytics_repo`.
  - **Release timing context**: "Released in {month/year}, the
    {Nth} game in {genre} that quarter" — from `mv_release_timing`.
  - **Related games strip**: top 6 by tag intersection — from
    `tag_repo` or a new lightweight repo method.
  - **Steam metadata richness**: developer / publisher (linked to
    those pages), platforms (with badges), Steam Deck status when
    added, Workshop/mod support flag.
  - **Top reviews surface**: top 3 by helpfulness — from existing
    `/api/games/{appid}/top-reviews`.

The principle: the no-report page should look like a credible
analytical dashboard, not a stub that says "Coming soon: AI
analysis." It's already a useful page on its own. The LLM report,
when present, is icing.

## Phase 3 — SEO defaults

- **`<head>` metadata**: `title`, `description`, `og:*`, `twitter:*`
  derived from Steam metadata + sentiment summary even without a
  report.
- **Schema.org `VideoGame` JSON-LD** populated from Steam fields +
  `aggregateRating` from `positive_pct` and `review_count`. Include
  `applicationCategory`, `genre`, `gamePlatform`, `datePublished`,
  `offers`. (Goes hand-in-hand with `soft-launch-seo-discipline.md`
  — coordinate on which prompt owns the implementation; suggest this
  one owns game-page schema, that one owns site-wide config.)
- **Canonical tag** to the slugified game URL.
- **No `noindex`** — every game page is index-worthy after this work.

## Verification

1. **Visual audit**: `cd frontend && npm run dev`. Pick 5 appids
   that have reports and 5 that don't. Compare side-by-side. The
   no-report pages should look ~70%+ as rich as the report pages —
   different content shape, similar density.
2. **Lighthouse SEO ≥ 90** on a sample no-report page.
3. **Google Rich Results test** passes with the VideoGame JSON-LD.
4. **Playwright E2E**: add a test fixture for "game without report"
   to `frontend/tests/fixtures/api-mock.ts`; new test in
   `game-no-report.spec.ts` verifies all expected fallback sections
   render and the LLM-only sections are absent (not empty).
5. **No empty section headers in the DOM** when `report=null` — a
   simple integration assertion.
6. `cd frontend && npm run test:e2e`.

## Out of scope

- Building any new repository methods or API endpoints — use what
  exists. If a fallback section needs data that isn't already
  exposed, defer it to a separate prompt rather than expanding scope.
- LLM-driven enrichment of the no-report page. Defeats the purpose
  (cost) and isn't needed (Steam + matview data is enough).

## Rollout

- Frontend-only PR. Deploys with the rest of the Next.js bundle via
  `bash scripts/deploy.sh --env staging` then `--env production`.
- After deploy: spot-check 10 random no-report game URLs in
  production.
- No deploy from Claude — user runs the deploy script.
