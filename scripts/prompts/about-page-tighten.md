# about-page-tighten

Tighten `/about` so it (a) stops giving up the LLM-pipeline recipe and (b) names and links the founder's Steam game (currently a demo) as a credibility signal for indie-dev visitors.

## Why

The current copy at `frontend/app/about/page.tsx` reveals competitive specifics — "chain of language models," the named three-phase pipeline `chunk → merge → synthesise`, and the exact ≥3 mention threshold — that buy a small amount of trust at the cost of handing competitors most of the architectural moat. Trust can be earned more cheaply via integrity signals (human review, data-vs-interpretation labeling, traceability, named limitations) without revealing architecture.

Separately, the founder section says "a Steam dev on break from their own game" but doesn't name or link the game. SteamPulse's audience is indie Steam devs; the founder being a Steam dev with a live demo on the same store is the strongest possible credibility signal for that audience. Generic B2B-SaaS guidance ("don't link unrelated projects") doesn't apply — same platform, same player base, directly verifiable.

## Scope

**One file modified:** `frontend/app/about/page.tsx`.
**One file extended:** `frontend/lib/author.ts` (add two constants for the game).

No homepage changes. No pricing-page changes. No footer changes. No screenshots, badges, banners, or CTAs. No feature flags or dual-path shims.

## Changes

### 1. `frontend/lib/author.ts` — add game constants

Add (alongside the existing `AUTHOR_NAME`, `AUTHOR_HANDLE`, `CONTACT_EMAIL` exports):

```ts
export const STEAM_GAME_NAME = "Corner Quest";
export const STEAM_GAME_URL = "https://store.steampowered.com/app/4254260/Corner_Quest/";
```

Before committing: verify the canonical game title on the live Steam page — the user typed "CorerQuest" in chat, which is likely a typo for "Corner Quest" (matches the URL slug). Use whatever Steam itself shows on the store page.

### 2. `frontend/app/about/page.tsx` — methodology rewrite

**Remove from the Methodology section:**
- The phrase "chain of language models."
- The named three-phase pipeline and its parenthetical descriptions: `*chunk* (extract per-review signal), *merge* (cluster recurring patterns across the corpus), and *synthesise* (assemble the final narrative with quote traceability)`.
- The explicit "at least three" mention threshold.

**Replace the first paragraph of Methodology with neutral framing:**
> Each report combines automated review-corpus analysis with editorial review. Cross-game patterns are surfaced only when there is sufficient supporting evidence across the corpus, so anecdotes never pose as trends.

**Keep verbatim (these are integrity signals, not recipe):**
- The full second paragraph of Methodology starting "Steam-sourced facts (sentiment %, …)" through the limitations sentence ending "…the corpus is Steam-only."
- The "What SteamPulse is" section's line "every claim anchored to a counted review quote."
- The "What SteamPulse is" section's line "A human editor reviews every published synthesis before it ships — the pipeline is AI-assisted, not AI-only." (Strongest trust signal on the page.)

After the edit, the Methodology section should read as a credibility/integrity statement, not a how-we-built-it document.

### 3. `frontend/app/about/page.tsx` — founder section

Current copy:
> SteamPulse is built and operated by Ivan Z. Ganza — a one-person shop, written by a Steam dev on break from their own game. Reports are produced offline and sold as catalog PDFs; everything else on the site is free.

The game is **in development with a public Steam demo**, not shipped — copy must reflect that accurately.

New copy:
> SteamPulse is built and operated by Ivan Z. Ganza — a one-person shop. SteamPulse was built on a break from his own game, **{STEAM_GAME_NAME}**, currently in development with a free demo on Steam. Reports are produced offline and sold as catalog PDFs; everything else on the site is free.

- `{STEAM_GAME_NAME}` is the only linked text. Wrap it in an `<a>` with `href={STEAM_GAME_URL}`, `target="_blank"`, `rel="noopener noreferrer"`.
- Style the link with the existing teal accent used for section headers (look for the existing color class on `<h2>` elements and reuse it inline).
- Import `STEAM_GAME_NAME` and `STEAM_GAME_URL` from `@/lib/author` alongside the existing `AUTHOR_NAME` import — same pattern.

## Constraints

- One inline link only — no screenshot, no banner, no card, no CTA.
- Link appears **only** on `/about`. Do not touch homepage, pricing, footer, or report pages.
- No feature flags or dual-path shims (per `feedback_no_pre_launch_flags`).
- New code comments are one line max (per `feedback_terse_comments`).
- Do not run `git add` / `commit` / `push` (per `feedback_no_commit_push`).

## Verification

1. Start the frontend dev server: `cd frontend && npm run dev`.
2. Load `http://localhost:3000/about`.
3. Visually confirm:
   - Methodology section contains no occurrence of `chain of language models`, `chunk`, `merge`, or `synthesise`.
   - Methodology section contains no occurrence of "at least three" or any literal threshold number for cross-game patterns.
   - Founder section names the game and the name links to its Steam page in a new tab.
4. `grep -iE "chain of language|chunk|merge|synthesise|at least three" frontend/app/about/page.tsx` returns no matches.
5. `cd frontend && npm run build` succeeds.
6. Spot-check `/` (homepage) and `/pricing` — game name/link must not appear there.
