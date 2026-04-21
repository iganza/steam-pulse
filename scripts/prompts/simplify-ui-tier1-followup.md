# Tier 1 UI follow-up — SEO hardening + /about + shared author byline

*Drop-in prompt for Claude Code in the SteamPulse project repo.*

*Ships on top of the already-merged `simplify-ui-for-tier1.md`.*

---

## Context

`simplify-ui-for-tier1.md` cleared the decks: Pro plumbing gone,
Toolkit deleted, enthusiast routes removed, nav reduced to four
items. Good. But the refined Tier 1 plan (two-tier catalog model +
curated synthesis preview + Phase A/B/C launch) added two SEO / trust
requirements that don't yet exist in the codebase:

1. **Named-author attribution on every LLM-generated page.** Google's
   March 2026 core update demotes mass-produced AI content *without*
   human editing or named-expert attribution. Per-game pages and the
   synthesis page are both LLM-synthesised. Even though per-game
   pages stay "fully visible, no curation," they need a visible
   byline + methodology link so they don't get caught in the AI-slop
   demotion sweep.
2. **An `/about` page** where the byline link actually resolves to.
   Right now every byline target is a 404.

This prompt adds both, plus a small shared config + schema.org
author attribution. It does **not** touch the Pro-plumbing deletes
(already done), the synthesis page (owned by `genre-insights-page.md`),
the landing page (owned by `fix-landing-page.md`), or Stripe
(owned by `stripe-checkout-report-delivery.md`).

## Goals

1. Every per-game page renders a named-author byline + methodology link.
2. Every per-game page emits schema.org `Article` JSON-LD with an `author` field.
3. An `/about` page exists, resolves from every byline link, and contains: methodology text + founder bio + a short "what SteamPulse is" paragraph.
4. A single `AUTHOR_NAME` config constant is the source of truth; every surface reads from it.
5. The nav `Reports` link points somewhere real until `/reports` ships (i.e. the flagship synthesis page).
6. Sitemap emits the post-refactor route set (`/`, `/about`, `/genre/[slug]/`, all `/games/[appid]/[slug]/`, all `/developer/[slug]/`, all `/publisher/[slug]/`, all `/tag/[slug]/`). Deleted routes are not emitted.

## What to do

### 1. Shared author config — `frontend/lib/author.ts` (new)

```ts
// One source of truth. Import where needed.
export const AUTHOR_NAME = 'Ivan Z. Ganza';   // fill in the real name
export const AUTHOR_HANDLE = '@iganza';        // or whichever handle is live
export const AUTHOR_BIO_SHORT = 'Built by a Steam dev on break from their own game.';
export const METHODOLOGY_PATH = '/about#methodology';
```

Keep it flat, no class, no context provider. Imported by byline
components, page metadata, JSON-LD builders. Changing the author
name in one place updates every surface.

### 2. Byline component — `frontend/components/shared/AuthorByline.tsx` (new)

Small presentational component:

```tsx
import Link from 'next/link';
import { AUTHOR_NAME, METHODOLOGY_PATH } from '@/lib/author';

export function AuthorByline({ className }: { className?: string }) {
  return (
    <p className={className}>
      Analysis by <span className="font-medium">{AUTHOR_NAME}</span>
      {' · '}
      <Link href={METHODOLOGY_PATH} className="underline">Methodology →</Link>
    </p>
  );
}
```

Used by:

- Per-game page header (this prompt)
- Synthesis page header (owned by `genre-insights-page.md` — it
  imports the same component)
- Landing page "What's in the free analysis" block (owned by
  `fix-landing-page.md` — same import)

Single component, three consumers, one name everywhere.

### 3. Per-game page — add byline + methodology footer

Target: `frontend/app/games/[appid]/[slug]/GameReportClient.tsx` (or
whichever component is the canonical per-game header/footer after
`simplify-ui-for-tier1.md`).

**Header block** — add `<AuthorByline />` immediately below the
`<h1>` / one-liner. No "Pro" pill. No date stamp yet (the page
inherits `GameReport.computed_at` if the client wants to render that
separately; don't block this prompt on it).

**Footer block** — add a methodology paragraph above the "related
games" section (or wherever the current footer lives). Copy:

> *This page was synthesised by the SteamPulse three-phase pipeline
> ({N} reviews analysed across chunk → merge → synthesise phases),
> reviewed and curated by {AUTHOR_NAME}. See the [methodology](/about#methodology)
> for the full pipeline and quote-traceability rules.*

Where `{N}` = `GameReport.total_reviews_analyzed`. The "reviewed and
curated by" phrasing matters for the Google 2026 signal — it names
a human in the loop, which is the difference between "AI content"
and "AI-assisted content" in Google's language.

### 4. Per-game page — schema.org `Article` JSON-LD

In the per-game page's server component (`page.tsx`, not the client
component), extend the existing JSON-LD block to include:

```ts
const articleJsonLd = {
  '@context': 'https://schema.org',
  '@type': 'Article',
  headline: `${game.name}: Player Sentiment Analysis`,
  datePublished: report.computed_at,
  dateModified: report.computed_at,
  author: {
    '@type': 'Person',
    name: AUTHOR_NAME,
    url: `https://steampulse.io/about`,
  },
  publisher: {
    '@type': 'Organization',
    name: 'SteamPulse',
    url: 'https://steampulse.io',
  },
  about: {
    '@type': 'VideoGame',
    name: game.name,
  },
};
```

Render inline: `<script type="application/ld+json" dangerouslySetInnerHTML={{__html: JSON.stringify(articleJsonLd)}} />`.

If the page currently emits a different `@type` (e.g. `Product` or
`VideoGame` alone), replace it with this one — `Article` is the
shape Google wants for editorial analysis pages.

### 5. `/about` page — new static route

Target: `frontend/app/about/page.tsx` (new).

One page, server component, static render, no API calls.

Sections:

**What SteamPulse is** (2 paragraphs)
- Deep market research for indie Steam devs
- How the synthesis works in plain language (LLM pipeline + human curation)

**Methodology** (anchor target `#methodology`, matches `METHODOLOGY_PATH`)
- The three-phase pipeline: chunk → merge → synthesise
- `mention_count ≥ 3` threshold for cross-game patterns
- Every claim quote-traceable to a Steam review with attribution
- Weekly refresh cadence on the underlying synthesiser; editorial
  content layered on top and stable between refreshes
- Limitations (sample bias, recency, Steam-only data)

**Who made this** (anchor target `#author`)
- Avatar + founder bio (2–3 sentences)
- Handle / contact (`AUTHOR_HANDLE` from config)
- Short, peer-to-peer register — write like a dev explaining a tool
  to another dev

**Contact** (anchor target `#contact`)
- One email address (`feedback@steampulse.io` or similar)
- No form. No newsletter signup. Nothing else.

Implementation notes:

- Render as plain prose (no interactive components).
- Metadata via `generateMetadata()` — `title: "About SteamPulse · Methodology"`, canonical set.
- Mobile: single column, prose max-width ~65ch.
- Lighthouse Accessibility ≥ 95, SEO ≥ 90.

### 6. Nav — provisional `Reports` target

The `simplify-ui-for-tier1.md` pass reduced nav to
`Logo · Reports · Browse · About`. Right now `Reports` links to
`/reports`, which doesn't exist yet (built by
`stripe-checkout-report-delivery.md`). Until that ships, point
`Reports` at the flagship synthesis page so it never 404s:

```tsx
// frontend/components/layout/Navbar.tsx
// BEFORE: <Link href="/reports">Reports</Link>
// AFTER:
<Link href="/genre/roguelike-deckbuilder/">Reports</Link>
```

When `stripe-checkout-report-delivery.md` ships `/reports`, flip
this one-line change back. No need to abstract further.

`Browse` stays pointing at wherever it points now (genre/tag hub or
`/search`). `About` links to the new `/about`. `Logo` links to `/`.

### 7. Sitemap — emit the post-refactor route set

Target: the dynamic sitemap route (`frontend/app/sitemap.ts` or
similar). Confirm it emits:

- `/`
- `/about`
- `/genre/[slug]/` for every row in `mv_genre_synthesis`
- `/games/[appid]/[slug]/` for every row in `reports`
- `/developer/[slug]/` for every distinct developer
- `/publisher/[slug]/` for every distinct publisher
- `/tag/[slug]/` for every tag with ≥ some threshold of games

And does **not** emit:

- `/pro`, `/compare`, `/explore`, `/trending`, `/new-releases` (deleted)
- `/genre/[slug]/insights` (path renamed to `/genre/[slug]/`)

If the sitemap still lists any deleted route, remove it. If the
synthesis-page path is wrong, fix it.

## What to keep untouched

- The `/reports` catalog route — owned by `stripe-checkout-report-delivery.md`. Not this prompt.
- The `/genre/[slug]/` synthesis page body — owned by `genre-insights-page.md`. This prompt only imports the shared `AuthorByline` into surfaces that aren't the synthesis page.
- The homepage — owned by `fix-landing-page.md`.
- Per-game analytics components, charts, review velocity, playtime distribution — already free after `simplify-ui-for-tier1.md`; do not refactor.
- Tests for the simplified per-game page — do not rewrite; extend if they assert byline presence.

## What this does NOT do (explicitly out of scope)

- Does NOT add a newsletter, Discord, waitlist, Pro tier, or any Tier-2-gated surface.
- Does NOT add testimonials, founder photo gallery, or multi-page About.
- Does NOT change the `GameReport` shape / sections / order.
- Does NOT update `/about` with rotating content, blog links, or anything that requires maintenance. Static page.
- Does NOT touch backend code. All changes are in `frontend/`.

## Voice guardrails

Same as `fix-landing-page.md` — forbidden vocabulary list, preferred
register, peer-to-peer, anti-hype. The About page copy especially:
no "we're on a mission to...", no "revolutionising", no
"empowering indie devs". Register = dev explaining the tool to
another dev.

## Verification

### Acceptance — per-game page

1. Load `/games/440/team-fortress-2` (or any game with a
   `GameReport`). Byline *"Analysis by {AUTHOR_NAME} · Methodology →"*
   appears below the h1. Clicking "Methodology →" navigates to
   `/about#methodology` and scrolls to the right anchor.
2. Scroll to the footer. Methodology paragraph renders with the
   review count and the author name substituted.
3. `view-source:` the page → `<script type="application/ld+json">`
   contains an `Article` object with `author.name === AUTHOR_NAME`
   and `author.url === "https://steampulse.io/about"`.

### Acceptance — /about

4. `/about` renders with four anchored sections (what / methodology /
   author / contact). Every anchor works.
5. `view-source:` the page → `<title>` and meta description populate;
   canonical is set.
6. Lighthouse on mobile: Accessibility ≥ 95, SEO ≥ 90, Performance ≥ 90.

### Acceptance — nav

7. Nav shows `Logo · Reports · Browse · About`. `Reports` resolves
   to `/genre/roguelike-deckbuilder/` with a 200 response.
8. Clicking `About` lands on `/about` without a redirect.

### Acceptance — sitemap + grep

9. `curl https://steampulse.io/sitemap.xml | grep -E '/(pro|compare|explore|trending|new-releases|insights)'`
   returns no matches.
10. Sitemap contains `/about` and `/genre/roguelike-deckbuilder/`.
11. `rg 'AUTHOR_NAME|AuthorByline' frontend/` — every byline surface
    imports from the shared config; no hard-coded author strings
    anywhere.

### Code hygiene

12. `cd frontend && npx tsc --noEmit` — clean.
13. `cd frontend && npm run build` — clean.
14. `cd frontend && npm test` — green.

## Rollout

- No users. No external traffic. Single PR, direct deploy.
- Expected diff: small additions (new files for `AuthorByline`, `/about`, `lib/author.ts`; small edits to per-game client + sitemap + navbar). No deletions. No feature flags.
- After merge + deploy, submit updated sitemap to Google Search Console + Bing Webmaster Tools. Request indexing for `/about`.

## PR description template

```
## Summary
Follow-up to simplify-ui-for-tier1: add the Google 2026 SEO signals
the refined Tier 1 plan requires. Per-game pages get a named-author
byline + methodology footer + schema.org Article JSON-LD. A new
static /about page hosts the methodology + founder bio where every
byline link resolves. Nav's "Reports" points at the flagship synthesis
page until /reports ships.

## Changes
- frontend/lib/author.ts — single-source author config constants
- frontend/components/shared/AuthorByline.tsx — byline component
- frontend/app/games/[appid]/[slug]/* — byline + methodology footer +
  Article JSON-LD
- frontend/app/about/page.tsx — new static page: what / methodology /
  author / contact
- frontend/components/layout/Navbar.tsx — "Reports" → /genre/roguelike-deckbuilder/
  provisional target; "About" → /about
- frontend/app/sitemap.ts — emit /about + /genre/[slug]/; stop emitting
  deleted routes

## Why
Google's March 2026 core update demotes AI content without named
human editing; every LLM-generated page now needs a visible byline +
methodology link + schema.org author. The /about page is where those
links resolve. Nav needs a real target for "Reports" until the
catalog page ships.
```
