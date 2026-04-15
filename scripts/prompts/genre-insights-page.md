# Genre insights page (frontend) — `/genre/[slug]/insights`

## Context

The user-facing surface of the Wedge Strategy
(`steam-pulse.org` → "Wedge Strategy: Roguelike Deckbuilder Deep
Coverage"). Reads from the synthesis row produced by
`cross-genre-synthesizer-matview.md` — that prompt must ship first
and have produced a row for at least `roguelike-deckbuilder` before
this page goes live.

This is **the demo**. The page that gets tweeted, posted to
r/gamedev, linked from the waitlist confirmation email, and indexed
by Google for queries like "roguelike deckbuilder player feedback."
SEO and shareability are first-class requirements, not afterthoughts.

## What to do

### 1. Route — `frontend/app/genre/[slug]/insights/page.tsx`

New route, **separate from** the existing `/genre/[slug]/page.tsx`
(which is the broader genre listing). The `/insights` suffix is the
synthesis-driven editorial page.

Server component. Fetches at request time via the existing API
client in `frontend/lib/api.ts` (add a `getGenreInsights(slug)`
helper). Uses Next.js `revalidate = 3600` for ISR — the underlying
synthesis only changes weekly, but we want the page to pick up edits
within the hour.

Returns `notFound()` if the API returns 404.

### 2. API client method — `frontend/lib/api.ts`

```ts
export async function getGenreInsights(slug: string): Promise<GenreInsights | null>
```

Add `GenreInsights` to `frontend/lib/types.ts` mirroring the
backend Pydantic `GenreSynthesis` shape exactly (don't drift —
backend is source of truth).

### 3. Page sections (FREE tier, in order)

The page's `<main>` is a single column on mobile, two columns on
desktop (insights main column + sticky sidebar with stats /
methodology / share buttons).

**Header block** (above the fold):
- `<h1>` — "What {Display Name} Players Want, Hate, and Praise"
- One-paragraph `narrative_summary` from the synthesis row
- "Last updated {computed_at}" + "Synthesized from {input_count} games"
- Share buttons: Twitter, copy link, Reddit (r/gamedev, r/{genre})

**Top 10 Friction Points** (`<section>`):
- Numbered list (`<ol>`)
- Each item: title (h3), description (p), blockquote with quote +
  link to the source game's `/games/[appid]/[slug]` page
- Show `mention_count` as a small badge ("18 of 141 games")

**Top 5 Wishlist Features**:
- Same shape as friction. Numbered list.
- Frame as opportunities, not complaints — these are the gaps in
  the genre.

**Benchmark Games** (`<section>`):
- 5-card grid. Each card: cover image (from `games.header_image`),
  game name, `why_benchmark` blurb, "View report →" link to
  `/games/[appid]/[slug]`.
- These are the most important cross-links for SEO. Use `<Link>`
  not raw `<a>` so Next.js prefetches.

**Churn Wall**:
- Single-stat callout. Big number (`typical_dropout_hour` formatted
  as "~4 hours"), `primary_reason` underneath, blockquote with the
  representative quote and link to source game.

**Genre stats sidebar/footer**:
- Game count, avg sentiment %, median review count, top 3
  developers (by total review_count of their games in this genre).
- Price distribution: small inline bar chart (or just "Most games
  $X–$Y, median $Z"). Source: `analytics_repo` — already exists.

**Methodology footer**:
- 2-3 sentences explaining the synthesis (LLM-aggregated from N
  games' reports, refreshed weekly, links to per-game pages for
  full reviews). Trust signal.
- "Notice an issue? Email feedback@steampulse.io"

### 4. PRO sections (UI shell only — V1 not gated)

Per CLAUDE.md "No payment integration until explicitly planned" and
the wedge spec "V1 placeholder UI only." Render these as visible
sections with a "Pro" pill badge but without a paywall (V1 has
`PRO_ENABLED=true` everywhere). When auth ships they'll be gated at
the API; the frontend just consumes whatever the endpoint returns.

- **Full friction list** (top 20 not 10) — collapsible `<details>`
  block under the top-10 list
- **Per-game contribution drill-down** — a "Which games drove this?"
  link on each insight that opens a modal listing the source appids
- **Cross-genre comparison** — placeholder card linking to a future
  `/genre/{slug}/compare` page, marked "Coming soon"
- **`dev_priorities`** ranked table — frequency × effort matrix

Ship these as real components consuming real data from the V1 full
payload. Don't stub them out.

### 5. SEO meta + structured data

In `generateMetadata()`:

```ts
return {
  title: `${displayName}: What Players Want, Hate, and Praise | SteamPulse`,
  description: narrative_summary.slice(0, 155),  // truncate for SERP
  openGraph: {
    title: ...,
    description: ...,
    images: [`/og/genre/${slug}.png`],  // future: per-genre OG image
    type: "article",
  },
  alternates: { canonical: `https://steampulse.io/genre/${slug}/insights` },
};
```

In the page body, add JSON-LD `<script type="application/ld+json">`
with `@type: Article`, `datePublished: computed_at`, `author: SteamPulse`,
`about: {@type: VideoGameSeries, name: displayName}`. Schema.org
markup helps Google understand the page is editorial content about
a game category, not a product listing.

### 6. Navigation entry

Add a "Genre Insights" link to the main nav under the existing
genres dropdown. For V1 only `roguelike-deckbuilder` has a
synthesis row — the dropdown should query the available syntheses
via `GET /api/genres/insights/available` (new lightweight endpoint
that returns `[{slug, display_name, computed_at}]` from the
synthesis table). Don't show genres without a synthesis row.

This unlocks the natural expansion — when broader Roguelike or
Survival gets synthesized, it appears in the dropdown automatically.

### 7. Tests — Playwright

Per CLAUDE.md: "any frontend change that alters user-visible
behaviour must include test updates in the same PR."

In `frontend/tests/`:

- New test file `genre-insights.spec.ts`
- Mock the API in `frontend/tests/fixtures/api-mock.ts` to return a
  canned `GenreInsights` for `roguelike-deckbuilder`
- Tests:
  - Page renders with correct h1 and narrative summary
  - All 10 friction points display
  - All 5 benchmark game cards render with cover images
  - Benchmark cards link to correct `/games/[appid]/[slug]` URLs
  - Churn wall stat displays
  - Methodology footer displays
  - Pro sections (full friction list, dev_priorities) render in V1
  - 404 page when slug has no synthesis (mock API returns 404)
- Update `frontend/tests/fixtures/mock-data.ts` with sample
  `GenreInsights` payload

### 8. Smoke test — `tests/smoke/`

Add `tests/smoke/test_genre_insights.py`:
- `GET /api/genres/roguelike-deckbuilder/insights` returns 200
- Response shape matches `GenreInsights` (use Pydantic to validate)
- Required fields populated: `narrative_summary` non-empty,
  `friction_points` ≥ 10, `wishlist_items` ≥ 5, `benchmark_games` ≥ 5

## Verification

1. `cd frontend && npm run dev` — visit
   `http://localhost:3000/genre/roguelike-deckbuilder/insights`
   against a local DB with a real synthesis row. Inspect every
   section.
2. **SEO check**: `view-source:` the page. Verify `<title>`,
   `<meta name="description">`, `<link rel="canonical">`, OG tags,
   and the JSON-LD script all populate correctly.
3. **Mobile**: Chrome DevTools mobile emulation. Two-column layout
   collapses to single column. Touch targets are large enough.
4. **Cross-links**: click each benchmark game card → lands on the
   correct `/games/[appid]/[slug]` page.
5. **404 path**: visit `/genre/nonexistent-slug/insights` →
   Next.js 404.
6. **Lighthouse**: aim for ≥ 90 on all four categories. Slow LCP
   usually means an image issue — use `next/image` for cover art.
7. `cd frontend && npm run test:e2e` — Playwright passes.
8. `poetry run pytest tests/smoke/test_genre_insights.py -v` —
   smoke passes against staging once deployed.

## Out of scope (separate prompts later)

- **Per-genre OG image generation** (Vercel OG / dynamic image
  route) — placeholder static image acceptable for V1.
- **Cross-genre comparison page** (`/genre/{slug}/compare`) —
  needs the synthesizer to support comparing two rows.
- **Pro paywall integration** — happens with auth0.
- **Additional genres beyond roguelike-deckbuilder** — same page,
  different slug. No code change needed; just produce more synthesis
  rows.

## Rollout

- Frontend deploys with the rest of the Next.js bundle via
  `bash scripts/deploy.sh --env staging` (then `--env production`
  once verified).
- Soft-launch verification on staging URL before flipping production.
- After production deploy: manually visit the page, copy the URL,
  craft the Twitter thread / Reddit posts.
- No deploy from Claude — user runs the deploy script.
