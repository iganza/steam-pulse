# Add publisher pages to the sitemap (deduped against developers)

## Problem

`frontend/app/sitemap.ts` emits hub routes, games, developers, genres, and top
tags — but never publisher pages. `/publisher/[slug]` exists at
`frontend/app/publisher/[slug]/page.tsx:49` and is a substantive surface
(stats tiles, sentiment-across-catalog widget, `PublisherPortfolio` analytics,
game grid), so it's an indexable SEO entry point being left on the table.

The naive fix — emit one URL per publisher the same way developers are
emitted — would generate duplicate-shape content for self-published indies
where `publisher == developer`. The two pages would render essentially the
same game list under different canonicals (`/developer/X` vs `/publisher/X`),
which is the pattern Google's helpful-content updates demote.

## Approach

Add a publisher loop to the sitemap, but only emit a publisher slug when it
differs from the game's developer slug. Self-published indies stay
single-surface (developer page only); AAA / multi-publisher catalogs get the
publisher page indexed.

`Game` already carries `publisher` and `publisher_slug`
(`frontend/lib/types.ts:110-111`), so we don't need ad-hoc slugification like
the developer loop does at `frontend/app/sitemap.ts:67`.

Single forward path, no flag.

## Files to modify

### 1. `frontend/app/sitemap.ts`

Inside the existing game pagination loop (currently L58–77), after the
developer dedup block, add a parallel publisher dedup block:

- Add `const pubSlugs = new Set<string>();` adjacent to `devSlugs`.
- For each game, after the developer push, check:
  - `game.publisher_slug` is non-empty
  - `game.publisher_slug !== <derived dev slug>` (compare against the same
    slugified developer string already computed for the developer dedup, not
    the raw `developer` field)
  - `pubSlugs.has(game.publisher_slug)` is false
  - `routes.length < GAME_LOOP_CAP`
- If all true: add to `pubSlugs`, push
  `{ url: \`${BASE_URL}/publisher/${game.publisher_slug}\`, changeFrequency: "weekly", priority: 0.5 }`.

Match the developer entry shape exactly (no `lastModified` — publishers don't
have a per-entity timestamp; `weekly`/`0.5` mirrors developers).

### 2. (No type changes)

`Game.publisher_slug` already exists. `getGames` already returns it. No API
or type edits needed.

## Out of scope

- Bumping `MAX_URLS` or splitting into a sitemap index. We're well under the
  49k cap today; revisit if the combined game+dev+pub count crosses ~45k.
- Publisher pages with zero distinct content beyond the developer page.
  The dedup-against-developer rule handles the common case (self-published
  indies). Edge cases — e.g. a publisher who also self-publishes one title
  *and* publishes others — will emit a publisher URL because at least one
  game has `publisher_slug != dev slug`. That's correct: the publisher page
  for that entity *does* show a different game set than any single developer
  page.
- `<lastmod>` for publisher entries. Same reason developers don't have one:
  no per-publisher timestamp on the Game record.

## Verification

1. **Local rebuild** — `cd frontend && npm run build && npm run start`, then
   `curl http://localhost:3000/sitemap.xml | grep '/publisher/' | wc -l`
   returns a non-zero count.
2. **Dedup correctness** — pick a known self-published indie (developer ==
   publisher); confirm its slug appears under `/developer/` but NOT under
   `/publisher/` in the sitemap output.
3. **Real publisher** — pick a known multi-game publisher (e.g. Devolver
   Digital, Annapurna Interactive, Raw Fury); confirm the slug appears under
   `/publisher/`.
4. **Cap headroom** — log or one-shot count: `routes.length` after the
   publisher loop should still leave room for genres + top-100 tags. If the
   total cracks ~45k, revisit `MIN_REVIEWS` or sitemap-index split (out of
   scope for this prompt, but flag it).
5. **Smoke** — `curl https://steampulse.io/sitemap.xml` post-deploy returns
   valid XML; spot-check one publisher URL resolves 200 and renders the
   `PublisherPortfolio` block.
