# Unify Landing Hero — Genre Synthesis + In-Genre Game Strip

## Context

The homepage at `frontend/app/page.tsx` currently renders two separate hero
sections:

1. **`FeaturedReport`** (line 221) — genre-wide synthesis card pointing at
   `/genre/roguelike-deckbuilder`. Powered by a single fast call to
   `/api/tags/{slug}/insights`.
2. **`GameShowcase`** (line 234) — tabbed 3-game intelligence card for three
   hardcoded appids (BG3 / Stardew / Cyberpunk). Powered by **9 SSR API calls**
   (`getGameReport` + `getReviewStats` + `getAudienceOverlap`, ×3).

`GameShowcase` is silently broken in prod: cold-start windows on the API
Lambda push individual `getGameReport` calls past the 25 s SSR timeout in
`frontend/lib/api.ts:37`. `Promise.allSettled` swallows the rejections,
`showcaseGames` filters down to empty, and the section renders nothing.
That empty render gets captured by Next.js ISR and served stale via
`stale-while-revalidate=2592000` — checked live: rendered HTML at
`https://d1mamturmn55fm.cloudfront.net/` shows `Featured Report` once and
**zero** showcase markers (no Baldur / Stardew / Cyberpunk / "Game
Intelligence in Action" strings anywhere).

`IntelligenceCards` (line 224) sits between them and depends on the same
broken showcase data, so it likewise renders nothing.

The three hardcoded games (BG3 / Stardew / Cyberpunk) were chosen as
**SEO/search-traffic anchors** — high-volume titles that gamers actually
google, supporting a "intelligence works for any Steam game" breadth
signal alongside the genre-depth signal of the FeaturedReport. Preserve
that pick. The bug isn't the *choice* of games, it's the heavy fan-out
needed to render them.

## Goal

Collapse the two heroes into **one** unified `FeaturedReport` card that
shows the genre synthesis pitch *plus* a 3-tab strip showing the same
hardcoded SEO-anchor games (BG3 / Stardew / Cyberpunk). Use **one cheap
API call** for the strip instead of nine heavy ones. Preserve the
genre's free-synthesis CTA. Drop `GameShowcase` and `IntelligenceCards`
entirely.

This is the smallest change that fixes the silent breakage while keeping
both signals: genre-depth (synthesis) + breadth (intelligence works for
any game, including the AAA titles people search for). No CloudFront
cache-policy changes, no cold-start tuning — those are separate concerns.

## Free-vs-paid alignment

The genre synthesis stays **free** — see
`memory/feedback_packaging_principle.md` and
`memory/project_business_model_2026.md`. Free = the publishable insight
that drives SEO and virality; the $499 Per-Genre Market Atlas PDF is the
paid layer (already wired via `ReportBuyBlock` on `/genre/[slug]/`). Do
not gate the synthesis or the game strip.

## Design

### 1. Backend — broaden `/api/games/basics` with sentiment fields

The endpoint at `src/lambda-functions/lambda_functions/api/handler.py:203`
already returns `{appid, name, slug, header_image}` in a single DB
round-trip with `Cache-Control: public, s-maxage=3600, stale-while-revalidate=86400`.
The hero strip needs sentiment metadata too: positive_pct + review_count
for the "94% positive · 215K reviews" chip.

**`src/library-layer/library_layer/repositories/game_repo.py`** —
`find_basics_by_appids` (line 533): extend the SELECT to include
`positive_pct` and `COALESCE(review_count_english, review_count) AS review_count`.
Both columns already exist on `games` and are indexed/filterable in
the existing schema; no join needed. Update the docstring to reflect
the broader contract.

**`src/lambda-functions/lambda_functions/api/handler.py`** — no change
needed; the endpoint just returns whatever the repo returns. Keep the
existing `Cache-Control` header.

**Tests** — update `tests/repositories/test_game_repo.py` if there's a
test for `find_basics_by_appids` (grep first); add a case asserting
positive_pct + review_count are returned. Update any
`tests/handlers/test_*` or smoke test asserting the basics response shape.

### 2. Frontend — `getGamesBasics` already exists

Confirm `frontend/lib/api.ts` has `getGamesBasics` (used by the genre
synthesis page). Update its return-type to include the two new fields.
If a `BasicsGame` type exists in `frontend/lib/types.ts`, extend it; if
not, add one.

### 3. Frontend — redesign `FeaturedReport` to embed the game strip

**`frontend/components/home/FeaturedReport.tsx`**

Current shape: a single `<Link>` wrapping the headline + blurb + stats +
"Read the free synthesis →" CTA.

New shape:

- Outer `<section>` with the same card chrome (`var(--card)` background,
  `var(--border)` outline, rounded-2xl, p-8/10).
- Header block: same "Featured Report · New" eyebrow, headline ("What
  {display_name} Players Want, Hate, and Praise"), blurb, three-stat
  pill row (X games synthesised · Y% positive · median Z reviews/game).
- "Read the free synthesis →" CTA — keep it as the primary button-style
  link to `/genre/{slug}` so it's still the dominant click target.
- **New: 3-tab strip below** the CTA, separated by a subtle horizontal
  rule. Each tab is a small horizontal card:
  - 96×44 thumbnail (`header_image`)
  - game name (truncate to one line)
  - sentiment chip: `{positive_pct}% positive · {review_count} reviews`
  - chevron-right; whole tab is a `<Link>` to `/games/{appid}/{slug}`
- Tabs render in a horizontal row on `md+`, stack vertically on mobile.
- Section header above the strip: "Game intelligence in action" in
  the same typography the standalone showcase was using — preserves the
  breadth-signal copy that the previous component carried.

Component signature changes from `{ insights }` to
`{ insights, strip }` where `strip` is `BasicsGame[]` (length 0–3).
If `strip` is empty, omit the entire strip block (graceful fallback —
e.g. if `getGamesBasics` fails, the genre hero still renders).

### 4. Frontend — `frontend/app/page.tsx` cleanup

- Drop imports: `getGameReport`, `getReviewStats`, `getAudienceOverlap`,
  `getAnalyticsTrendSentiment` (the last one only feeds
  `IntelligenceCards.trendData`), `IntelligenceCards`, `GameShowcase`,
  `ShowcaseGame`.
- **Keep** the `SHOWCASE_GAMES` constant (line 29) — same three
  appids/slugs (BG3 / Stardew / Cyberpunk). These are the SEO/search
  anchors and stay deliberately hardcoded.
- Remove the 9 per-game fetches and the `trendSentiment` fetch from
  `Promise.allSettled` (lines 88–97).
- Add **one** fetch to the same `Promise.allSettled` array:
  `getGamesBasics(SHOWCASE_GAMES.map(g => g.appid))`. One DB round-trip,
  cached at origin (`s-maxage=3600`). Settled-failure ⇒ strip omitted,
  genre hero still renders.
- Drop the `scResults` / `showcaseGames` assembly block (lines 119–147).
- Build `strip: BasicsGame[]` from the basics result, preserving the
  order from `SHOWCASE_GAMES`. Each basics row already includes
  `{appid, name, slug, header_image, positive_pct, review_count}` — the
  exact shape the redesigned `FeaturedReport` expects. Use the slug from
  the API response (canonical) rather than the hardcoded one in
  `SHOWCASE_GAMES` (which exists only as a hint for clarity).
- Drop the `IntelligenceCards` (lines 224–231) and `GameShowcase`
  (lines 233–236) JSX blocks.
- Update `<FeaturedReport ... />` to pass both `insights` and `strip`.
- Drop `hasIntelCards` (line 154) — no longer used.

The homepage SSR call count drops from ~17 → ~9. The biggest fragile
cluster (showcase trio × 3 endpoints each) is gone, replaced by a
single cheap basics call.

### 5. Components — leave on disk, drop from render

- `frontend/components/home/GameShowcase.tsx` — **do not delete**. Removed
  from the homepage render path here, but kept in source for the follow-up
  positioning-reconcile prompt (`02-landing-positioning-reconcile.md`),
  which may revive it with a sustainable data source.
- `frontend/components/home/IntelligenceCards.tsx` — **do not delete**.
  Same reasoning — the 4-card "What You Get" block is in the positioning
  spec and the next prompt will rewire it to a non-fragile data path.
- Just remove the imports and JSX from `frontend/app/page.tsx`. No
  `ShowcaseGame` imports needed anymore.

### 6. Picking the 3 games

Three hardcoded appids in `SHOWCASE_GAMES` (BG3 / Stardew / Cyberpunk),
chosen as SEO/search anchors. **Do not change them in this prompt.**

If a future story wants a curated per-genre strip instead, that's a
separate change — surface it via a `featured_appids` column on
`mv_genre_synthesis` and prefer it over the hardcoded list when present.
Out of scope here.

## Acceptance criteria

1. Live homepage at `https://d1mamturmn55fm.cloudfront.net/` renders the
   `FeaturedReport` card with three game tabs for BG3 / Stardew /
   Cyberpunk (verifiable: HTML contains those names + `header_image`
   URLs from `cdn.akamai.steamstatic.com`).
2. `GameShowcase` and `IntelligenceCards` JSX no longer present in the
   rendered HTML (no "Game Intelligence in Action" string).
3. Homepage SSR's `Promise.allSettled` array has ≤10 entries.
4. `/api/games/basics?appids=...` response includes
   `positive_pct` (number-or-null) and `review_count` (number-or-null)
   for each returned game.
5. Genre synthesis page at `/genre/roguelike-deckbuilder` is unaffected
   (still free, still shows `ReportBuyBlock` upsell when wired).
6. Existing tests pass; new test covers the broadened
   `find_basics_by_appids` shape.

## Out of scope

- CloudFront cache policy for `/api/*` (still `CACHING_DISABLED`; fixing
  that is a separate, more invasive change).
- Lambda cold-start tuning (separate observability + perf prompt).
- Per-genre curated override for the 3 selected games (future
  enhancement; current list is hardcoded SEO anchors).
- Any change to `/genre/[slug]/` or `ReportBuyBlock` — those stay as-is.
