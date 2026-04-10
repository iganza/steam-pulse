# SteamPulse Value Assessment — Claude Code Analysis Prompt

## Task

Perform a comprehensive, honest value assessment of SteamPulse as a product. This is
not a code review — it is a product intelligence audit. Your job is to explore the
codebase deeply, understand what the product actually delivers today, and produce a
structured analysis of real value vs. perceived value for each target stakeholder.

Be honest. Identify gaps, weaknesses, and missed opportunities as clearly as strengths.
The goal is to produce something a founder can use to make pre-launch decisions.

---

## Stakeholders to Assess

Assess each stakeholder independently:

1. **Indie game developer** — pre-launch competitive research, sprint prioritization,
   understanding what players hate/love about games in their genre
2. **Marketing / UA manager** — positioning, audience targeting, store page optimization,
   understanding what review language to lean into
3. **Game publisher / investor** — portfolio intelligence, acquisition targets, genre
   trends, hidden gem identification
4. **Gamer / consumer** — deciding whether to buy a game, discovering games by sentiment

---

## What to Explore

Read and analyze the following before writing your assessment. Do not skip any of these:

### Report Schema & LLM Output Quality
- `src/library-layer/library_layer/analyzer.py` — full chunk prompt + synthesis prompt,
  section definitions, constraints, anti-duplication rules, self-check
- `src/library-layer/library_layer/models/` — all report models, what fields exist
- Understand what each section (`dev_priorities`, `churn_triggers`, `player_wishlist`,
  `store_page_alignment`, `refund_signals`, `community_health`, etc.) actually delivers
  and who benefits from each

### Frontend — What Users Actually See
- `frontend/app/games/[appid]/[slug]/GameReportClient.tsx` — the full game report page
- `frontend/components/game/` — all game-level components (what's rendered, what's gated)
- `frontend/components/toolkit/` and `frontend/components/toolkit/lenses/` — the analytics
  toolkit: what lenses exist, what they show
- `frontend/app/explore/page.tsx`, `frontend/app/trending/page.tsx`,
  `frontend/app/compare/page.tsx` — discovery and comparison surfaces
- `frontend/app/genre/[slug]/page.tsx`, `frontend/app/tag/[slug]/page.tsx`,
  `frontend/app/developer/[slug]/page.tsx` — cross-linking index pages
- `frontend/app/pro/page.tsx` — the premium upsell page, what's promised
- `frontend/lib/types.ts` — the full GameReport type as the frontend sees it

### API Surface
- `src/lambda-functions/lambda_functions/api/routes/` — all API endpoints, what data
  is returned, what is gated behind premium
- `src/library-layer/library_layer/repositories/` — what data is actually stored and
  queryable (games, reviews, reports, analytics)

### Data Completeness
- `src/library-layer/library_layer/schema.py` — full DB schema
- Understand what fields are populated vs. nullable/optional in practice
- Note any sections that are defined but not yet implemented or always empty

### Premium Gating
- What sections are locked behind premium (`ProLockOverlay`, `usePro` hook)
- Whether the free tier provides enough value to create upgrade desire
- Whether the premium tier's additional value is clearly communicated

---

## Assessment Framework

For each stakeholder, evaluate:

### 1. Core Value Proposition
What is the single most valuable thing SteamPulse delivers to this person today?
Is it genuinely better than existing alternatives (manual review reading, SteamSpy,
Metacritic, IGDB, VGInsights)?

### 2. Workflow Fit
Where in their actual workflow does SteamPulse fit? Is the UX designed for that
workflow, or does it require significant effort to extract value?

### 3. Data Quality Threshold
At what review count does the report become genuinely useful vs. misleading?
Are there safeguards against showing confident-sounding but thin-signal reports?

### 4. Gaps — What's Missing
What data, features, or UX elements would make this dramatically more valuable for
this stakeholder? Be specific.

### 5. Friction Points
What in the current product would cause this stakeholder to leave without getting value?
(Confusing UI, stale data, gated content before they see value, etc.)

### 6. Monetization Fit
Would this stakeholder pay? If yes, what would they pay for specifically, and does
the current premium offering match that?

---

## Output Format

Write a structured markdown report saved to `docs/value-assessment.md`.

Structure:
```
# SteamPulse Value Assessment

## Executive Summary
3-5 bullet points on the strongest findings across all stakeholders.
Which stakeholder has the highest value alignment today?
Which has the lowest? What is the single highest-leverage improvement?

## Stakeholder Assessments

### [Stakeholder Name]
**Core value today:** one sentence
**Workflow fit:** paragraph
**Data quality threshold:** specific recommendation (e.g., "hide dev_priorities below 200 reviews")
**Key gaps:** bulleted list
**Friction points:** bulleted list
**Monetization fit:** paragraph with specific price/value observations

[repeat for each stakeholder]

## Cross-Cutting Issues
Issues that affect multiple stakeholders (freshness, quality gates, premium gating UX, etc.)

## Highest-Leverage Improvements
Ranked list of 5-8 specific changes (not vague suggestions) that would most increase
real value delivery. Each should name the file/component to change and the expected impact.

## What SteamPulse Should NOT Be
Honest list of directions that sound appealing but the current product is not positioned
to deliver well. Saves the team from building the wrong things.
```

---

## Constraints

- Do not write marketing copy. Write like a product consultant who will not be hired again
  if they sugarcoat findings.
- Every gap or weakness must cite a specific file, component, or schema field that
  illustrates it — not abstract observations.
- Every strength must be tied to something a real user would notice in a session —
  not architectural decisions they'd never see.
- Do not recommend adding entirely new data sources or LLM passes unless the existing
  data clearly supports it.
- The assessment should be completable in one Claude Code session — do not design
  a research project, write a product audit.
