# Rebuild the landing page for Tier 1 (funnel to free synthesis page)

*Drop-in prompt for Claude Code in the SteamPulse project repo.*

*Companion to `simplify-ui-for-tier1.md` (broader UI cleanup) and
`genre-insights-page.md` (the free synthesis page this one funnels to).*

---

## Context

SteamPulse ships under the **two-tier catalog business model** with a
**phased launch**:

- **Phase A** — free cross-genre synthesis page at `/genre/roguelike-deckbuilder/`. Ships Week 1. This is the proof artifact.
- **Phase B** — pre-order block added to the synthesis page. Stripe Checkout captures $49/$149/$499 with delayed delivery. Ships Week 2–4.
- **Phase C** — polished PDF ships; delivery worker fires for pre-order buyers; self-serve opens. Ships Week 4–8.

The landing page exists to do **one thing**: send visitors to the
free synthesis page. The synthesis page is where the proof lives and
where the pre-order funnel (Phase B) and the PDF purchase funnel
(Phase C) operate. The landing page does not handle commerce. It does
not collect email. It does not promise a newsletter. It points one
way: to the free analysis.

```
SEO (per-game pages + /genre/[slug]/)
        ↓
homepage hero CTA  ← THIS FILE
        ↓
/genre/roguelike-deckbuilder/   ← the free analysis page
        ↓
pre-order block on that page (Phase B+)
        ↓
Stripe Checkout → delivery worker → S3 signed URL
```

Everything on the homepage serves that arrow. Anything else gets cut.

## Positioning (locked — use verbatim where specified)

- **Tagline:** "Steam, decoded."
- **Hero sub-line:** *"Deep market research for indie Steam devs. Every player review across an entire genre, synthesised into one cited page."*
- **Mission line:** "Know before you commit."
- **Artifact names:** the free page is *the analysis*; the paid PDF is *the report*.
- **Primary audience:** solo and small-indie Steam game developers deciding what to build, launch, or patch next
- **Not the audience:** Steam enthusiasts/players, AAA studios, mobile devs

## Goals (measurable)

After this work, the landing page must:

1. Have **one primary CTA above the fold** — *"Read the Roguelike Deckbuilder analysis →"* linking to `/genre/roguelike-deckbuilder/`. No competing CTAs above the fold. No form, no email capture, no pricing button.
2. Name the paid PDF **once** in the page body, as a sub-point on the way to the analysis page: *"A print-ready PDF ships [date] — pre-order from $49 on the analysis page."* Single mention. No dedicated pricing section on the landing page.
3. Contain **zero newsletter signup, zero waitlist, zero Pro mention** anywhere on the page.
4. Contain **zero AAA/enthusiast catalog feeds** — no Most Popular, Trending, New Releases, Hidden Gems, Just Analyzed, Top Rated.
5. Make **"built for indie Steam devs"** explicit and visible in the hero.
6. Preserve **SEO-valuable navigation** (browse by genre / tag) below the fold.
7. Reflect the brand voice — cited, peer-to-peer, anti-hype.
8. Render cleanly on mobile (375px). 83% of traffic is mobile and mobile converts worst — do not make it worse with overflow, tiny text, or stacked CTAs.

## Hard deletes (remove from the page entirely — delete files, don't archive)

1. **"Most Popular" list** — surfaces AAA multiplayer (CS2, Dota 2). Zero indie-dev relevance.
2. **"Top Rated" list** in its current composition.
3. **"Hidden Gems" list** in its enthusiast-discovery framing.
4. **"New on Steam" feed** of recently-released un-analysed games.
5. **"Just Analyzed" feed** — internal admin signal.
6. **"Trending" / "New Releases" nav links** — enthusiast verbs.
7. **"Compare" nav link and any user-facing Compare UI** — killed in `simplify-ui-for-tier1.md`.
8. **"For Developers" nav link** — the whole site is for devs now. Replace with **"Reports"** (→ `/reports`, the catalog page once it exists; before it exists the nav link can point at the RDB synthesis page directly).
9. **"Join the Pro waitlist" CTA anywhere on the page** — no Pro tier exists, none is coming without a Tier 2 gate firing.
10. **Newsletter signup form anywhere on the page** — weekly newsletter is Tier 2 gated. No promise of a thing that doesn't exist.
11. **"Weekly Week in Genre" copy** — kill references throughout.
12. **`/pro` page and any link to it** — the route is deleted in `simplify-ui-for-tier1.md`; here just remove every link.
13. **Any pricing table / "Pricing" nav link / `$49 $149 $499` grid** on the landing page itself. Pricing is surfaced on the synthesis page next to the pre-order button, not as a standalone landing section.

## Page structure (top to bottom, final)

```
1. NAV (minimal)
   Logo · Reports · Browse · About
   (no Pro, no Compare, no Trending, no Developers)

2. HERO (above fold; one primary CTA)
   Steam, decoded.
   Deep market research for indie Steam devs. Every player review
   across an entire genre, synthesised into one cited page.

   [ Read the Roguelike Deckbuilder analysis → ]

   Cited · 141 games · 930k+ reviews synthesised · Free to read

3. MISSION BREAK (one line, visual pause)
   Know before you commit.

4. BUILT FOR INDIE STEAM DEVS
   Made for solo and indie Steam developers deciding what to build,
   launch, or patch next.
   · Understand what your players actually say
   · Know what the genre winners share in common
   · See the churn, the wishlist, the friction — cited to reviews

5. WHAT'S IN THE FREE ANALYSIS
   (The proof. Preview the actual synthesis page.)
   · Executive paragraph excerpt (first narrative_summary sentence
     from the live mv_genre_synthesis row)
   · One friction cluster with mention_count + representative quote
     + source-game attribution (playtime hours + helpful votes)
   · One benchmark game pull-quote (Slay the Spire / Balatro /
     Inscryption)
   · Dev priorities table preview (3 rows from the synthesis)

   [ Read the full analysis → ]
   (secondary micro-line:
     "A print-ready PDF ships [date] — pre-order from $49 on the
     analysis page.")

6. HOW THE ANALYSIS IS BUILT (methodology transparency)
   Short paragraph:
   "The analysis is built from the complete player-review corpus of
   a single Steam niche (141 games, ≥500 reviews each, for the
   Roguelike Deckbuilder edition). A three-phase LLM pipeline extracts
   structured signals, merges per-game syntheses, and surfaces patterns
   that show up in at least 3 games. Every claim traces back to a
   specific review with a specific author, playtime, and helpful-vote
   count."
   [ Read the methodology → ] (links to /about or /methodology)

7. RECENT ANALYSES
   (At launch: one genre synthesis page. Grid designed for 4-8 as
   catalog grows.)
   Cards link to /genre/[slug]/. Each card:
   genre · games analysed · narrative_summary first line · "Read →"

8. BROWSE FREE PER-GAME BREAKDOWNS
   (SEO substrate surfaced as credibility.)
   6-8 indie games with full GameReport data. Suggested seeds:
   Hollow Knight, Stardew Valley, Balatro, Vampire Survivors,
   Hades II, Dredge, Pizza Tower, Celeste.
   No AAA / multiplayer titles.
   [ Browse all 141 Roguelike Deckbuilder games → ]
   [ Browse all genres → ]

9. WHO MADE THIS (founder signal — required, not optional)
   Avatar + one sentence:
   "Built by a Steam dev on break from their own game. Find me at
   [handle]."

10. FINAL CTA (single — same destination as hero)
    [ Read the Roguelike Deckbuilder analysis → ]
    free to read · no signup · pre-order the PDF from $49 if you
    want it printable

11. SEO NAVIGATION (below the fold)
    Browse by Genre (programmatic SEO surface)
    Browse by Tag (programmatic SEO surface)

12. FOOTER
    © SteamPulse · Methodology · Terms · Contact
    (no social, no newsletter, no Discord, no community links —
     none of those exist yet)
```

## Specific component changes

### Hero

- Headline locked: **"Steam, decoded."**
- Sub-line locked (verbatim): *"Deep market research for indie Steam devs. Every player review across an entire genre, synthesised into one cited page."*
- Primary CTA: **"Read the Roguelike Deckbuilder analysis →"**. Links to `/genre/roguelike-deckbuilder/`. No trailing price. No "from $49" — the analysis is free; the price lives on the analysis page itself.
- Below the CTA: one line of high-density trust markers. Use numbers from the real data, not rounded-up vanity numbers. Example (fill with real numbers once the analysis is run): *"Cited · 141 games · 930k+ reviews synthesised · Free to read"*.
- No secondary CTA above the fold. Two above-fold CTAs halves conversion on the primary.

### "What's in the free analysis" section (critical — this is the proof)

Preview the actual live synthesis content. Pull from the API
(`GET /api/genres/roguelike-deckbuilder/insights`), not from hard-coded
placeholders. Four concrete blocks:

1. **Narrative excerpt** — first sentence of `narrative_summary`.
2. **One friction cluster** — highest-`mention_count` item from `friction_points`. Show: title, mention_count badge ("18 of 141 games"), representative quote with attribution (source game + playtime hours + helpful votes).
3. **One benchmark pull-quote** — a sentence from one of the top 3 `benchmark_games[].why_benchmark` entries, framed as a pull-quote.
4. **Dev priorities preview** — first 3 rows from `dev_priorities`: action · why it matters · frequency · effort.

Closing CTA in this section: **"Read the full analysis →"** linking
to `/genre/roguelike-deckbuilder/`. Below that, *one* micro-line
mentioning the PDF: *"A print-ready PDF ships [date] — pre-order from
$49 on the analysis page."* That sentence is the only place on the
landing page where price or PDF is named. Do not add a pricing section.

If the synthesis row doesn't exist yet at implementation time, the
section can render with placeholders flagged
`// TODO: replace with live mv_genre_synthesis data when Phase A batch analysis lands`.
But the component must consume the real API in production.

### Nav simplification

Four items total:

```
Logo · Reports · Browse · About
```

- `Reports` → `/reports` if the catalog page exists; otherwise `/genre/roguelike-deckbuilder/` (single report at launch).
- `Browse` → the genre/tag hub. Reuse whatever exists; do not create a new route for this prompt.
- `About` → `/about`. If the route doesn't exist, create a stub with methodology + founder bio. One page, static.

### Methodology section

Short paragraph (3–4 sentences) describing the three-phase pipeline
in plain language. No "AI-powered." Key phrases to include: *every
review*, *cited*, *three-phase synthesis*, *mention_count ≥ 3*, *quote
traceability*. The goal is to communicate *craft* — not to brag about
LLM tech.

### Founder signal

Non-negotiable for the Marcus persona. Peer-to-peer brand requires a
visible human. One sentence, avatar, real handle. If the handle
doesn't exist yet, create one before shipping; don't ship without.

## What to KEEP (minor polish only)

- **Hero headline "Steam, decoded."** — locked.
- **Sentiment Over Time chart** (if already embedded as part of a synthesis preview component) — dense, visual, proves synthesis quality.
- **Audience Overlap block** (same story — if used as a proof element) — differentiator.
- **Market Trends section** (positively-rated releases over time) — dev-relevant. Position as context for reading analyses, not as a standalone feature.
- **Browse by Genre + Browse by Tag** browsers at the bottom — programmatic SEO.

## Voice + tone guardrails (apply to ALL copy on the page)

### Never use

`AI-powered` · `AI-generated` · `AI-suggested` · `intelligent` (adjective) · `smart` (adjective) · `unlock` · `leverage` · `disrupt` · `revolutionise` · `game-changer` · `next-gen` · `empower` · `transform` · `actionable insights` · `seamless` · `cutting-edge` · `deep-dive` (overused) · `ideate` · `robust` · `end-to-end` (unless technical) · `synergy` · `journey` · `solution` (as product noun) · exclamation points · stacked em-dashes.

### Prefer

`research` · `synthesis` · `cited` · `data-backed` · `LLM-synthesised` (only when technical transparency required) · `pattern` · `signal` · `delta` · `cluster` · `methodology` · `benchmark` · `review mining` · `friction` · `wishlist` · `churn` · `cohort`.

### Register

- Peer-to-peer. Marcus is a solo Steam dev. Write for him, not at him.
- Anti-hype is a brand asset. Understate. Under-claim.
- Cite specific numbers, not round vanity numbers. "141 games · 930k reviews" beats "thousands of games · millions of reviews."
- No vendor-to-customer register. No "we're excited to announce." Ever.

## Non-goals (explicitly out of scope)

- Do NOT redesign the per-game report page (`/games/[appid]/[slug]`). Working. Out of scope.
- Do NOT build the synthesis page itself — that's `genre-insights-page.md`.
- Do NOT build the Stripe Checkout flow — that's `stripe-checkout-report-delivery.md`.
- Do NOT add newsletter, Discord, community, waitlist, login, user accounts, or pricing sections. All Tier-2-gated, killed, or lifted to the synthesis page.
- Do NOT add competitor comparison copy.
- Do NOT add testimonials until they exist. Placeholder testimonials are worse than none.
- Do NOT put Stripe buttons or price selectors on the landing page. Commerce happens on the synthesis page.

## Implementation notes

- Target: `frontend/app/page.tsx` and its immediate children under `frontend/components/home/`.
- Delete components that render KILLed sections. No `_legacy`, no comments out, no deprecation shims.
- The "What's in the free analysis" component consumes `getGenreInsights('roguelike-deckbuilder')` from `frontend/lib/api.ts` (same helper the synthesis page uses). Single data source.
- Keep Next.js ISR / static generation. Hero is static; the synthesis-preview block is an async server component with a short revalidate window (match the synthesis page's ISR cadence).
- Hero LCP budget: < 1.8s on mobile (Lighthouse).

## Verification

### Acceptance tests (functional)

1. Landing page renders at `/` with hero headline "Steam, decoded." and the locked sub-line verbatim.
2. Above-the-fold region contains exactly one primary CTA; that CTA links to `/genre/roguelike-deckbuilder/`.
3. The "What's in the free analysis" section pulls live data from `/api/genres/roguelike-deckbuilder/insights` and renders the four blocks (narrative excerpt, friction cluster, benchmark pull-quote, dev priorities preview).
4. Exactly **one** sentence on the page mentions the paid PDF + pre-order. Grep test: `rg 'pre-order' frontend/app/page.tsx` returns one occurrence.
5. Grep of rendered HTML returns zero matches for: `newsletter`, `waitlist`, `Pro tier`, `Pro subscription`, `Discord`, `Most Popular`, `Trending`, `New Releases`, `Hidden Gems`, `Just Analyzed`, `For Developers`, `AI-powered`, `Upgrade to Pro`.
6. Grep for the forbidden vocabulary list in `Voice + tone guardrails` → zero matches across landing-page copy.
7. The final-CTA section links to the same destination as the hero (`/genre/roguelike-deckbuilder/`).
8. Founder signal renders with an avatar and a non-empty bio sentence.
9. Browse-by-genre and browse-by-tag navigation exists below the fold and resolves to working routes.

### Acceptance tests (quality)

10. Mobile (375px viewport): all sections stack cleanly, no horizontal overflow, hero CTA reachable in one tap, touch targets ≥ 44px.
11. Lighthouse on `/` (mobile preset): **Performance ≥ 90, Accessibility ≥ 95, SEO ≥ 90**.
12. No 404s / broken internal links from the rendered homepage.
13. Time-to-understand test (manual, one cold reader): "Within 8 seconds, what is this site for, and what's the one thing to do?" Expected: "research analyses for indie Steam devs; read the Roguelike Deckbuilder analysis."

### Acceptance tests (voice)

14. Peer review pass: read aloud. Flag any sentence that sounds like marketing. Rewrite until it sounds like a dev explaining a tool to another dev at a conference bar.
15. Specificity pass: every vague claim replaced with a specific number or cut.

## Rollout

- No users. No external traffic. No migration. Single PR, direct replace.
- No feature flag. No A/B. No gradual rollout.
- After merge + prod deploy, submit updated sitemap to Google Search Console + Bing Webmaster Tools. Request re-indexing for `/`.

## PR description template

```
## Summary
Rebuild the landing page around the phased Tier 1 launch. Single
primary CTA → the free /genre/roguelike-deckbuilder/ analysis page.
Commerce (pre-order + PDF) lives on the analysis page, not here.

## Changes
- Hero: single CTA → /genre/roguelike-deckbuilder/
- "What's in the free analysis" proof section (live data from
  /api/genres/[slug]/insights)
- "How the analysis is built" methodology section
- Founder signal (avatar + one-sentence bio)
- One sentence mentions the paid PDF; no pricing section on landing
- Deletes: Most Popular, Top Rated, Hidden Gems, New on Steam,
  Just Analyzed, Trending/New Releases/Compare nav, For Developers
  nav, Pro waitlist, newsletter signup, /pro links
- Nav reduced to: Reports · Browse · About
- Voice-rule lint pass across all copy

## Why
The landing page's only job is funnelling visitors to the free
synthesis page. Commerce happens on that page (Phase B pre-order,
Phase C PDF delivery). Anything on the landing page that competes
with that arrow is cut.
```
