# Lean Landing Page Redesign for Launch

## Context

The site is a **game intelligence platform** for studios — not a Steam discovery destination. The current landing page (`frontend/app/page.tsx`) does eleven things at once: a hero, a featured-genre cross-synthesis report, four intelligence cards with charts, a market-trends preview with two embedded charts, four discovery rows (Most Popular / Top Rated / Hidden Gems / New on Steam), a Just Analyzed strip, a "For Developers" Pro waitlist block, a tag browser, a genre browser, and a footer CTA. The discovery rows in particular reinforce a "Steam game discovery" framing that the product is not.

We're launching very soon. Two constraints shape this redesign:

1. **The cross-genre synthesis lead (`FeaturedReport`, currently set to `roguelike-deckbuilder`) must come off the page.** The synthesis isn't ready to share publicly yet.
2. **Billing is not yet built.** The CTA cannot sell — it must capture an email for a Pro waitlist using the existing `POST /api/waitlist` + SES infrastructure.

Goal: a ruthlessly lean page that answers "what is this and why should I care" within ~3 seconds, has one obvious CTA above the fold, and gives repeat visitors a reason to come back (fresh just-analyzed games + live market-trends charts). Modeled on 2026 SaaS best practices: single dominant CTA above the fold, hero headline <44 chars, show the product early, email-only waitlist form, CTA repeated strategically (hero + bottom).

## Target structure (top to bottom)

Roughly **2 viewports** total. Above the fold = the entire hero + the start of the just-analyzed strip peeking.

1. **Hero** (above the fold)
   - Headline: `Steam, decoded` (keep — already pithy, already 14 chars)
   - Subhead (one line): `Game intelligence for studios. Sentiment, themes, and market gaps across every Steam game.`
   - **Primary CTA: email capture form** → `Join the Pro waitlist`
     - Single email input + button
     - Microcopy under button: `Free reports today. Pro launches soon. No spam.`
   - Trim proof line under CTA: `N games analyzed · M reviews processed · Updated daily` (use existing `getCatalogStats()`)

2. **Just Analyzed** (3 games, not 6)
   - Section heading: `Just analyzed`
   - 3-tile grid using existing `GameTile` / discovery-feed component, fed by `getDiscoveryFeed("just_analyzed", 3)`
   - Caption under section: `Updated continuously. Each report is free to read.`
   - Tiles link to existing `/games/{appid}` pages (deep pages stay accessible — just not promoted)

3. **Market Trends Preview** (the existing `MarketTrendsPreview` component, kept as-is)
   - Two live, interactive charts side-by-side: positive-rated releases trend + release volume
   - Year/quarter/month/week granularity toggle already wired
   - Acts as the "show the product" proof — live data on the landing page beats text bullets for conveying capability and gives a reason to come back as the data refreshes
   - Component is self-contained (its own client-side fetches); no new page-level data calls needed
   - Existing `Browse reports →` link inside the component is fine to keep

4. **Repeat CTA** (same form component as hero)
   - One-line headline: `Be first when Pro launches.`
   - Same email form — same `POST /api/waitlist` endpoint.

5. **Minimal footer** (existing site footer in `layout.tsx` — no change)

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

Keep: `MarketTrendsPreview` (renders in slot 3), `getDiscoveryFeed("just_analyzed", 3)` (changed limit from 6 → 3) and `getCatalogStats()` for the proof line.

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

- **`frontend/components/home/WaitlistEmailForm.tsx`** — generic email capture form with copy props (`headline`, `buttonLabel`, `subtext`). Posts to `POST /api/waitlist` (existing endpoint, body `{ email }`, response `{ status: "requested" | "already_requested", request_count }`). Used in two places: hero and the repeat CTA. Reuses the success/error state pattern from the existing per-game `RequestAnalysis.tsx` (`frontend/components/game/RequestAnalysis.tsx`) — extract the shared bits if cheap, otherwise duplicate the small amount needed. Form should fire a Plausible event on successful submit (e.g. `Waitlist Signup`) so we can measure conversion.

- **`frontend/components/home/JustAnalyzedStrip.tsx`** — small wrapper that renders the 3-tile strip + caption. Could also be inlined in `page.tsx` — author's call. Reuses the same tile component the existing discovery rows use today (look up the tile component currently rendered by the removed discovery rows and reuse it).

## Copy direction

| Slot | Copy |
|---|---|
| Hero headline | `Steam, decoded` |
| Hero subhead | `Game intelligence for studios. Sentiment, themes, and market gaps across every Steam game.` |
| Primary CTA button | `Join the Pro waitlist` |
| CTA microcopy | `Free reports today. Pro launches soon. No spam.` |
| Proof line | `{N} games analyzed · {M} reviews processed · Updated daily` |
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
- Load `http://localhost:3000/`. Above-the-fold on a 1366×768 laptop must show: headline + subhead + email input + primary button + microcopy + proof line. Nothing else.
- Scroll once → see all 3 just-analyzed tiles. Scroll again → MarketTrendsPreview charts and the repeat CTA. Granularity toggle on the charts must still work.
- Submit a test email. Verify it hits `POST /api/waitlist` and a confirmation email is sent via SES (check `RequestAnalysis.tsx` for the existing fetch pattern and replicate). Verify duplicate submission shows the `already_requested` state gracefully.
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
