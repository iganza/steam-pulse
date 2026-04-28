# Lean Landing Page Redesign for Launch

## Context

The site is a **game intelligence platform** for studios — not a Steam discovery destination. The current landing page (`frontend/app/page.tsx`) does eleven things at once: a hero, a featured-genre cross-synthesis report, four intelligence cards with charts, a market-trends preview with two embedded charts, four discovery rows (Most Popular / Top Rated / Hidden Gems / New on Steam), a Just Analyzed strip, a "For Developers" Pro waitlist block, a tag browser, a genre browser, and a footer CTA. The discovery rows in particular reinforce a "Steam game discovery" framing that the product is not.

We're launching very soon. Two constraints shape this redesign:

1. **The cross-genre synthesis lead (`FeaturedReport`, currently set to `roguelike-deckbuilder`) must come off the page.** The synthesis isn't ready to share publicly yet.
2. **Billing is not yet built.** The CTA cannot sell — it must capture an email for a Pro waitlist using the existing `POST /api/waitlist` + SES infrastructure.

Goal: a ruthlessly lean page that answers "what is this and why should I care" within ~3 seconds, has one obvious CTA above the fold, and gives repeat visitors a reason to come back (fresh just-analyzed games + live market-trends charts). Modeled on 2026 SaaS best practices: single dominant CTA above the fold, hero headline <44 chars, show the product early, email-only waitlist form, CTA repeated strategically (hero + bottom).

Section ordering follows a textbook B2B SaaS funnel: **Action → Trust signal → Product demo → Social proof / freshness → Action**. The "Featured analyses" row of name-recognition games (BG3 / Stardew / Cyberpunk) carries the trust-signal slot — without it, first-time visitors see only the no-name freshly-analyzed catalog and lose the brand-legitimacy cue.

## Target structure (top to bottom)

Roughly **2 viewports** total. Above the fold on a typical laptop (≥1280×800) = the entire hero **plus** the full Featured analyses panel — both visible together on first paint, no scrolling needed for the "hero + product preview" combo. This matches the 2026 Linear / Vercel / Amplitude / Zendesk pattern of embedding a slice of the actual product directly under the headline+CTA.

To make this fit, the spec is deliberately compact:
- Hero uses tight vertical padding (`pt-12 pb-6`, not `pt-20 pb-12`)
- `main` uses `space-y-12` between sections (not `space-y-16`)
- The Featured analyses heading sits **inline with the pill tabs** (flex row) instead of stacked above them — saves a row of vertical space
- Showcase panel uses 40/60 column split (image left, content right) and a tight content layout: `text-sm` italic one-liner clamped to 2 lines, `text-xs` strength/friction blocks clamped to 2 lines, `p-5` padding

1. **Hero** (above the fold)
   - Headline: `Steam, decoded` (keep — already pithy, already 14 chars)
   - Subhead (one line): `Game intelligence for studios. Sentiment, themes, and market gaps across every Steam game.`
   - **Primary CTA: email capture form** → `Join the Pro waitlist`
     - Single email input + button
     - Microcopy under button: `Free reports today. Pro launches soon. No spam.`
   - No catalog-stats proof line: `getCatalogStats()` returns total catalog size (~150k), not analyzed count (~140), so showing it would mislead. The Featured analyses panel below carries the proof-of-substance role with real `total_reviews_analyzed` numbers per anchor game.

2. **Featured analyses** (3 name-recognition games — interactive teaser panel)
   - Heading + tabs sit **on the same row** (flex justify-between): `Featured analyses` left, three pill tabs right (`Baldur's Gate 3` / `Stardew Valley` / `Cyberpunk 2077`) — keeps the section header tight
   - **Tabbed showcase** (Datadog / Vercel / Linear pattern): single featured panel below that swaps content when a tab is clicked
   - Active panel renders as a 40/60 column split on desktop / stacked on mobile:
     - Left (40%): header image, full bleed, no padding
     - Right (60%): game name + sentiment chip (`positive_pct`), the report's `one_liner` in serif italic (text-sm, clamp 2 lines), then two short blocks — `✓ What works` (first item from `design_strengths`, text-xs, clamp 2 lines) and `⚠ What hurts` (first item from `gameplay_friction`, text-xs, clamp 2 lines)
     - Footer of panel: `Based on {total_reviews_analyzed} reviews · Read full analysis →` linking to `/games/{appid}/{slug}`
   - Anchors: BG3 (1086940), Stardew Valley (413150), Cyberpunk 2077 (1091500) — fed by parallel `getGameBasics([...])` + per-appid `getGameReport(appid)` calls in the page-level `Promise.allSettled`
   - Per-game report cached for ~1 day on the homepage. `getGameReport` accepts an optional `revalidate` override; the homepage passes `revalidate: 86400`. The default (used by the deep `/games/{appid}/{slug}` page) remains `31536000` (~1 year) since reports are immutable until manually re-analysed (and tag-purged via `game-{appid}`).
   - If a report is missing for any anchor, that game falls back to basics-only (`one_liner`/strength/friction null) — panel still renders gracefully
   - Lives between hero and Market Trends so the trust signal + value proof both arrive before the platform demo; the headline insight pair (one strength + one friction) per game proves we synthesize, not just summarize Steam metadata

3. **Market Trends Preview** (the existing `MarketTrendsPreview` component, kept as-is)
   - Two live, interactive charts side-by-side: positive-rated releases trend + release volume
   - Year/quarter/month/week granularity toggle already wired
   - Acts as the "show the product" proof — live data demonstrates capability beyond static logos
   - Component is self-contained (its own client-side fetches); no new page-level data calls needed
   - Existing `Browse reports →` link inside the component is fine to keep

4. **Just analyzed** (3 games, not 6)
   - Section heading: `Just analyzed`
   - 3-tile grid using existing `GameCard` (full card with name + dev + score bar) — full-card variant, distinct from the compact Featured-analyses tiles
   - Fed by `getDiscoveryFeed("just_analyzed", 3)`
   - Caption: `Updated continuously. Each report is free to read.`
   - Provides freshness signal and a reason to revisit as the catalog grows

5. **Repeat CTA** (same form component as hero)
   - One-line headline: `Be first when Pro launches.`
   - Same email form — same `POST /api/waitlist` endpoint.

6. **Minimal footer** (existing site footer in `layout.tsx` — no change)

Everything else gets removed from the landing page.

## Sections to remove from `frontend/app/page.tsx`

Delete the imports, the `Promise.allSettled` data fetches, and the JSX for:

- `FeaturedReport` (cross-genre synthesis lead — `roguelike-deckbuilder`)
- All four discovery rows: `popular`, `top_rated`, `hidden_gem`, `new_release` (page.tsx ~lines 192–215)
- `IntelligenceCards`
- `TagBrowser` + the "Browse by Genre" / "Browse by Tag" section
- `ForDevelopers` (replaced by the new hero CTA + repeat CTA)
- `FooterCTA`
- `getHomeIntelSnapshot`, `getGenreInsights(FEATURED_REPORT_SLUG)`, `getGameBasics([3 showcase appids])`, `getTagsGrouped(200)`, `getGenres()` data fetches — drop these calls; they're only used by the removed sections

Keep: `MarketTrendsPreview` (renders in slot 3), `getDiscoveryFeed("just_analyzed", 3)` (changed limit from 6 → 3), `getGameBasics([1086940, 413150, 1091500])` for the Featured analyses panel, and `getGameReport(appid)` per anchor (3 parallel calls, ISR-cached for ~1 day) to populate `one_liner` + top `design_strength` + top `gameplay_friction` + `total_reviews_analyzed`.

## Component file disposition

Per the project's no-backwards-compat-shim convention, **delete** the now-unused components rather than leaving dead files on disk:

- `frontend/components/home/FeaturedReport.tsx` → delete
- `frontend/components/home/IntelligenceCards.tsx` → delete
- `frontend/components/home/MiniSentimentChart.tsx` → delete only if unused after IntelligenceCards is removed (grep first — if `MarketTrendsPreview` or any other component still imports it, keep)
- `frontend/components/home/MiniOverlapList.tsx` → same: delete only if unused after IntelligenceCards is removed
- `frontend/components/home/MiniTrendLine.tsx` → same: delete only if unused after IntelligenceCards is removed
- `frontend/components/home/TagBrowser.tsx` → delete (the genre/tag browse UX should move to a `/genres` or `/tags` page later if desired — out of scope here)
- `frontend/components/home/ForDevelopers.tsx` → delete
- `frontend/components/home/FooterCTA.tsx` → delete
- `frontend/components/home/ProofBar.tsx` → delete (replaced by inline proof line)

Keep: `frontend/components/home/MarketTrendsPreview.tsx`, `frontend/components/home/` directory itself, plus anything reused by deep pages. After deletion, grep the repo for each removed symbol and confirm no other imports break.

## New components

- **`frontend/components/home/WaitlistEmailForm.tsx`** — generic email capture form with copy props (`headline`, `buttonLabel`, `subtext`). Posts to `POST /api/waitlist` (existing endpoint, body `{ email }`, response `{ status: "registered" | "already_registered" }` — no `request_count`; that field belongs to the per-game `/api/reports/request-analysis` endpoint, not this one). Used in two places: hero and the repeat CTA. Add an early-return re-entrancy guard inside `handleSubmit` (`if (status === "submitting") return`) — the `disabled` prop alone doesn't prevent rapid double-submits before React re-renders. Form should fire a Plausible event on successful submit (`Waitlist Signup`, with `variant: "hero" | "repeat"` and `status` props) so we can measure conversion.

- **`frontend/components/home/JustAnalyzedStrip.tsx`** — small wrapper that renders the 3-tile strip + caption. Could also be inlined in `page.tsx` — author's call. Reuses the same tile component the existing discovery rows use today (look up the tile component currently rendered by the removed discovery rows and reuse it).

- **`frontend/components/home/FeaturedAnalysesShowcase.tsx`** — client component (uses `useState` for the active tab) that renders the pill tabs + featured panel pattern. Takes `entries: ShowcaseEntry[]` as a prop where each entry contains `appid`, `name`, `slug`, `header_image`, `positive_pct`, `one_liner`, `top_strength`, `top_friction`, `reviews_analyzed`. Reuses `getScoreColor` from `@/lib/styles`. ARIA tablist/tab/tabpanel wired correctly. The `ShowcaseEntry` type is exported from this file and consumed by `page.tsx`.

## Copy direction

| Slot | Copy |
|---|---|
| Hero headline | `Steam, decoded` |
| Hero subhead | `Game intelligence for studios. Sentiment, themes, and market gaps across every Steam game.` |
| Primary CTA button | `Join the Pro waitlist` |
| CTA microcopy | `Free reports today. Pro launches soon. No spam.` |
| Featured analyses heading | `Featured analyses` |
| Just Analyzed heading | `Just analyzed` |
| Just Analyzed caption | `Updated continuously. Each report is free to read.` |
| Market Trends heading | `Market trends` (kept from existing `MarketTrendsPreview`) |
| Repeat CTA headline | `Be first when Pro launches.` |
| Repeat CTA button | `Join the Pro waitlist` |

The implementer can adjust word-by-word, but should hold these properties: headline ≤44 chars, no "AI" language (per existing project convention), single CTA verb across both hero and repeat, no pricing mentioned anywhere.

## SEO / meta

`frontend/app/page.tsx` lines 33–54: update the `description` to match the new positioning, e.g. `Game intelligence for studios. Player sentiment, themes, and market gaps across every Steam game.` Title and OG image stay as-is. Canonical and JSON-LD (`layout.tsx`) unchanged.

## Critical files

- `frontend/app/page.tsx` — main rewrite (gut + restructure)
- `frontend/components/home/WaitlistEmailForm.tsx` — NEW
- `frontend/components/home/JustAnalyzedStrip.tsx` — NEW (or inlined in page.tsx)
- `frontend/components/home/MarketTrendsPreview.tsx` — kept as-is, just continues to be imported by `page.tsx`
- Component deletions listed above
- Existing reuse: `POST /api/waitlist` handler in `src/lambda-functions/lambda_functions/api/handler.py`, `src/library-layer/library_layer/repositories/waitlist_repo.py`, SES `waitlist_confirmation` template — **no backend changes needed**

## Verification

Local:
- `cd frontend && pnpm dev` (or whichever package manager — check `frontend/package.json`)
- Load `http://localhost:3000/`. Above-the-fold on a 1366×768 laptop (and 1280×800, 1440×900, 1512×982 — the panel bottom should land at ~664px) must show: headline + subhead + email input + primary button + microcopy + the entire Featured analyses panel (heading, all 3 pill tabs, image, game name, sentiment chip, one-liner, ✓ What works, ⚠ What hurts, "Based on N reviews · Read full analysis →"). Both hero CTA and a full slice of product proof visible without scrolling.
- Click each tab and verify the panel content swaps — image, name, sentiment %, one-liner, "What works" sentence, "What hurts" sentence, and "Based on N reviews · Read full analysis →" all change.
- Click "Read full analysis" on at least one panel and verify it lands on `/games/{appid}/{slug}` showing the full report.
- Scroll again → MarketTrendsPreview charts (granularity toggle still functional) → Just Analyzed (3 full GameCard tiles) → repeat CTA.
- Submit a test email. Verify it hits `POST /api/waitlist` and a confirmation email is sent via SES. Verify duplicate submission shows the `already_registered` state gracefully. Empty/whitespace submissions are blocked by the input's `required` + `type="email"` attributes (native browser tooltip); the JS `setError("Please enter your email address.")` path stays as defense-in-depth for programmatic submissions that bypass browser validation.
- `pnpm build` (or `next build`) — must pass with no broken imports from deleted components.
- `pnpm lint` and `pnpm typecheck` — no errors.
- Visual check: navigate via top nav to `/games/{appid}` and `/genre/{slug}` deep pages — they must still render correctly (they use their own data fetches, not landing-page imports).
- Plausible: `Waitlist Signup` event fires on successful form submission.

Cross-browser: Chrome + Safari at minimum.

Lighthouse on the new landing page should match or improve current Performance and SEO scores (fewer charts/data fetches → expect Performance to climb).

## Out of scope (intentional)

- `/pro` route or Pro feature page — none of the CTAs need it; both go to the email form on this same page.
- Stripe / billing wiring.
- Pricing tiers ($49/$149/$499) — not surfaced anywhere on landing until billing exists.
- Cross-genre synthesis pages (`/genre/{slug}`) — keep them live and reachable via direct URL; just don't promote from landing.
- A separate `/genres` or `/tags` browse page to replace `TagBrowser` — defer; can be a follow-up prompt if needed.
- Newsletter / Buttondown / Mailchimp — using the existing `waitlist` Postgres table.
- A/B testing framework — defer.
