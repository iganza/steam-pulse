# Genre synthesis page — `/genre/[slug]/`

*Drop-in prompt for Claude Code in the SteamPulse project repo.*

*The Phase-A and Phase-B surface of the Tier 1 launch.*

---

## Context

The `/genre/[slug]/` page is the **free flagship artifact** of the
two-tier catalog business model. It renders the Phase-4 cross-genre
synthesis (`mv_genre_synthesis`) as an editorial-quality web page. It
is:

- The page the landing-page CTA points at
- The page that gets shared on r/gamedev / Bluesky / indie Discords
- The page that Google indexes for queries like *"roguelike deckbuilder player feedback"*
- The page that hosts the **pre-order / buy** block for the paid PDF (Phase B)

Depends on `cross-genre-synthesizer-matview.md` — that prompt must
have shipped and produced an `mv_genre_synthesis` row for at least
`roguelike-deckbuilder` before this page goes live.

Every section on this page is free. There are no Pro tiers, no blur,
no CTA overlays, no "upgrade to unlock" buttons. The paid product is
the PDF, advertised in a single pre-order block; there is no
on-page-content paywall.

## Route

**`frontend/app/genre/[slug]/page.tsx`** — a server component at the
genre root. Replace whatever currently occupies this route. If an
older "broader genre listing" page exists here, delete it; anything
useful from it (game list, genre stats) folds into this page's
sidebar.

No `/insights` suffix. The synthesis page IS the genre page.

## What to do

### 0. Schema migration — editorial columns on `mv_genre_synthesis`

Two new text columns on the synthesis matview store the human-written
curation that distinguishes the free preview page from the raw
synthesiser output:

```sql
-- depends: <prev>
ALTER TABLE mv_genre_synthesis
  ADD COLUMN IF NOT EXISTS editorial_intro TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS churn_interpretation TEXT NOT NULL DEFAULT '';
```

Both are operator-populated at curation time via a small ops script
(`scripts/ops/update_editorial.py slug --intro-file ... --churn ...`)
or directly via psql. The matview refresh job **does not touch
these columns** — they're human content layered on top of the
synthesiser output. Refresh the matview freely; the editorial text
persists as long as the row's primary key holds.

Empty string is the "not yet curated" state. The page component
falls back to `narrative_summary` (for `editorial_intro`) and omits
the line entirely (for `churn_interpretation`) when empty. Rolling
out the page before editorial is written is therefore safe, just
thinner.

### 1. Server component + data fetch

```tsx
// frontend/app/genre/[slug]/page.tsx
import { notFound } from 'next/navigation';
import { getGenreInsights, getReportForGenre } from '@/lib/api';

export const revalidate = 3600;  // ISR — synthesis refreshes weekly

export default async function GenrePage({ params }: { params: { slug: string } }) {
  const [insights, report] = await Promise.all([
    getGenreInsights(params.slug),
    getReportForGenre(params.slug),  // may return null
  ]);
  if (!insights) notFound();
  // render...
}
```

### 2. API client — `frontend/lib/api.ts`

```ts
export async function getGenreInsights(slug: string): Promise<GenreInsights | null>

export async function getReportForGenre(slug: string): Promise<ReportSummary | null>
```

`ReportSummary` is a thin type holding what the pre-order block needs:

```ts
type ReportSummary = {
  slug: string;                    // "rdb-2026-q2"
  display_name: string;
  tiers: { tier: 'indie' | 'studio' | 'publisher'; price_cents: number; stripe_price_id: string }[];
  published_at: string;            // ISO; > now() ⇒ pre-order
  is_pre_order: boolean;           // derived server-side: published_at > now()
};
```

Mirror `GenreInsights` in `frontend/lib/types.ts` exactly matching the
backend Pydantic `GenreSynthesis` shape. Backend is source of truth.

Backend endpoint for report lookup: `GET /api/genres/{slug}/report` →
returns the active `reports` row for that genre joined across its
three tiers, or 404 if none exists. Owned by
`stripe-checkout-report-delivery.md`'s scope; this prompt just
consumes it.

### 3. Page sections (in order, top to bottom)

The page is a **curated preview** of the synthesis — not the raw
Phase-4 output. The free page proves the research is real and worth
paying for; the paid PDF (buy block in section 4) is the full
analysis. This distinction is load-bearing for two reasons:

1. **Google's 2026 core update** demotes mass-produced AI content
   without human editing / named expert attribution. The editorial
   intro + author byline + curated counts satisfy the "substantially
   edited by a named human expert" test.
2. **Anti-cannibalisation.** AI Overview / Claude / Perplexity can
   cite the preview but cannot "finish" the buyer's question from
   it — the deep context, full quote sets, all ten friction items,
   benchmark deep-dives, and dataset all live in the paid PDF.

Single column on mobile. Two columns on desktop: main content + a
sticky right sidebar with stats / methodology / share / buy block.

**Header block** (above the fold):
- `<h1>` — `"What {Display Name} Players Want, Hate, and Praise"`
- **Author byline** — *"Analysis by {author_name} · Methodology →"*. `author_name` comes from a config constant (one human name — yours — for now). The byline link anchors to the methodology footer. This is the Google 2026 "named human expert" signal.
- **Editorial intro** (200–300 words) — human-written paragraph framing what the synthesis found and why it matters to an indie dev building in this genre. NOT the raw `narrative_summary`. Written by the operator at curation time and stored alongside the synthesis row (new column `mv_genre_synthesis.editorial_intro TEXT NOT NULL DEFAULT ''`; fall back to `narrative_summary` while empty). Original perspective satisfies the Google 2026 expertise signal.
- Meta line: *"Synthesised from {input_count} games · {total_reviews} reviews · last updated {computed_at}"*
- Share buttons: Twitter/X, Bluesky, copy link, Reddit (`r/gamedev`, `r/{genre}`)

**Top 5 Friction Points** (`<section>`):
- Numbered list (`<ol>`), items 1–5 from `insights.friction_points` (highest `mention_count` first — the repo already orders this way).
- Each item: title (`<h3>`), short description, `<blockquote>` with verbatim quote + link to source game (`/games/[appid]/[slug]`).
- `mention_count` badge — *"18 of 141 games"*.
- Closing line below the list: *"Five more friction clusters, with full quote sets, are in the PDF →"* anchoring to the buy block.

**Top 3 Wishlist Features**:
- Same shape as friction. Items 1–3.
- Framed as opportunities, not complaints — the genre's gaps.
- Closing line: *"Seven more wishlist items are in the PDF →"*.

**Benchmark Games** (`<section>`):
- 3-card grid. Each card: cover image (`games.header_image`), game name, one-sentence pull-quote from `why_benchmark`, *"Read the per-game analysis →"* link to `/games/[appid]/[slug]`.
- These are important internal cross-links for SEO. Use `<Link>` so Next.js prefetches.
- Closing line: *"Two more benchmark games, with 3–4 page deep-dives each, are in the PDF →"*.

**Churn Wall**:
- Single-stat callout. Big number (`typical_dropout_hour` formatted as *"~4 hours"*), `primary_reason` underneath in one line.
- **One-line editorial interpretation** written by the operator at curation time (new column `mv_genre_synthesis.churn_interpretation TEXT NOT NULL DEFAULT ''`; fall back to empty if unset). Example: *"Unlock grind hits around the 8-hour mark — players drop before meta-progression kicks in."* No blockquote on the free page; the full quote + context lives in the PDF.

**Dev Priorities teaser** (`<section>`):
- Render **first 2 rows** only from `insights.dev_priorities` as a compact two-row table (action · why it matters · frequency · effort).
- Below the table: *"The full ranked priorities table — all {N} actions, plus strategic recommendations — is in the PDF →"* anchoring to the buy block.

**Methodology footer**:
- 2–3 sentences explaining the synthesis (three-phase LLM pipeline, `mention_count ≥ 3` threshold, curated by a human before publication, weekly refresh, links to per-game pages for full review context).
- Anchor target for the byline link.
- *"Notice an issue? Email feedback@steampulse.io"*

### 4. Pre-order / Buy block (the commerce surface)

Renders **only if** `report !== null` (i.e. a `reports` row exists for
this genre). If `report === null`, the section is simply absent — the
page is a pure research page.

Two visual states depending on `report.is_pre_order`:

**Pre-order state** (`published_at > now()`):

```
┌─────────────────────────────────────────────────────────────┐
│  Want this as a print-ready report?                         │
│  {display_name} ships {formatted ship date}.                │
│                                                             │
│  Indie      $49   PDF                                       │
│  Studio     $149  PDF + CSV dataset + 1-yr updates          │
│  Publisher  $499  PDF + CSV + raw JSON + team license       │
│                                                             │
│  [ Pre-order Indie ]  [ Pre-order Studio ]  [ Pre-order Publisher ]│
│                                                             │
│  You'll receive a confirmation email now and the download   │
│  link on ship date.                                         │
└─────────────────────────────────────────────────────────────┘
```

**Live state** (`published_at <= now()`):

```
┌─────────────────────────────────────────────────────────────┐
│  Want this as a print-ready report?                         │
│  {display_name} — available now.                            │
│                                                             │
│  Indie      $49   PDF                                       │
│  Studio     $149  PDF + CSV dataset + 1-yr updates          │
│  Publisher  $499  PDF + CSV + raw JSON + team license       │
│                                                             │
│  [ Buy Indie ]  [ Buy Studio ]  [ Buy Publisher ]           │
│                                                             │
│  Instant download link emailed on purchase.                 │
└─────────────────────────────────────────────────────────────┘
```

Each button `POST`s to `/api/checkout/start` with
`{ report_slug, tier }` and redirects to the returned Stripe Checkout
URL. See `stripe-checkout-report-delivery.md`.

Place the block **above the methodology footer** (bottom of main
column) and **in the sticky right sidebar** on desktop. Two
placements; one block component.

Voice on this block: matter-of-fact, no "Limited time!" or hype. The
report ships when it ships; buyers who value print-ready get it.

### 5. SEO meta + structured data

In `generateMetadata()`:

```ts
return {
  title: `${displayName}: What Players Want, Hate, and Praise | SteamPulse`,
  description: narrative_summary.slice(0, 155),  // SERP truncation
  openGraph: {
    title: ...,
    description: ...,
    images: [`/og/genre/${slug}.png`],
    type: 'article',
  },
  alternates: { canonical: `https://steampulse.io/genre/${slug}/` },
};
```

In the page body, JSON-LD `<script type="application/ld+json">` with
`@type: Article`, `datePublished: computed_at`,
`author: { @type: Organization, name: "SteamPulse" }`,
`about: { @type: VideoGameSeries, name: displayName }`. Signals to
Google that the page is editorial content about a game category, not
a product listing.

### 6. Navigation entry

Add genre links to the **Browse** nav item (part of
`fix-landing-page.md` / `simplify-ui-for-tier1.md`). Query available
genres via `GET /api/genres/insights/available` — a lightweight
endpoint returning `[{slug, display_name, computed_at, has_report}]`
from the synthesis table. Don't show genres without a synthesis row.

When more genres get synthesised, they appear in Browse automatically.

### 7. Tests — Playwright

New test file `frontend/tests/genre-page.spec.ts`:

- Mock the API in `frontend/tests/fixtures/api-mock.ts` to return a canned `GenreInsights` for `roguelike-deckbuilder`
- Tests:
  - Page renders with correct h1, author byline, editorial intro, and narrative meta line
  - Exactly 5 friction points display (curated preview, not the full 10)
  - Exactly 3 wishlist items display
  - Exactly 3 benchmark game cards render with cover images + working `/games/[appid]/[slug]` links
  - Churn wall stat + one-line editorial interpretation display (no blockquote on the free page)
  - Dev priorities teaser renders exactly 2 rows plus the "full table in PDF" anchor
  - Every closing "…in the PDF →" anchor resolves to the buy block
  - Methodology footer displays and is the anchor target for the byline link
  - **Pre-order block:** when mock `getReportForGenre` returns a row with future `published_at`, block renders with *"Pre-order"* buttons and ship date
  - **Live block:** when mock returns a row with past `published_at`, block renders with *"Buy"* buttons
  - **No-report state:** when mock returns null, no pre-order / buy block renders at all
  - 404 when slug has no synthesis (mock API returns 404)
- Update `frontend/tests/fixtures/mock-data.ts` with sample `GenreInsights` + `ReportSummary` payloads

### 8. Smoke test — `tests/smoke/`

Add `tests/smoke/test_genre_page.py`:
- `GET /api/genres/roguelike-deckbuilder/insights` returns 200
- Response shape matches `GenreSynthesis` Pydantic model
- Required fields populated for the **underlying synthesis row** (the page curates down from these): `narrative_summary` non-empty, `friction_points ≥ 10`, `wishlist_items ≥ 10`, `benchmark_games ≥ 5`, `dev_priorities ≥ 3`. The extra material beyond the curated preview is what the paid PDF delivers.
- `GET /api/genres/roguelike-deckbuilder/report` returns 200 or 404 depending on seed state

## Verification

1. `cd frontend && npm run dev` — visit `http://localhost:3000/genre/roguelike-deckbuilder/` against a local DB with a real synthesis row. Inspect every section.
2. **SEO check**: `view-source:` the page. Verify `<title>`, `<meta name="description">`, `<link rel="canonical">`, OG tags, and the JSON-LD script all populate correctly.
3. **Mobile**: Chrome DevTools 375px width. Two-column layout collapses cleanly; pre-order block readable; touch targets ≥ 44px.
4. **Cross-links**: click each benchmark game card → lands on correct `/games/[appid]/[slug]`.
5. **404 path**: `/genre/nonexistent-slug/` → Next.js 404.
6. **Pre-order state**: seed a `reports` row with future `published_at` → refresh page → block shows *"Pre-order"* buttons + ship date.
7. **Live state**: flip `published_at` to past → refresh → block shows *"Buy"* buttons + *"available now"*.
8. **No-report state**: delete the `reports` row → refresh → no block at all; the rest of the page renders unchanged.
9. **Lighthouse** (mobile): Performance ≥ 90, Accessibility ≥ 95, SEO ≥ 90.
10. `cd frontend && npm run test:e2e` — Playwright passes.
11. `poetry run pytest tests/smoke/test_genre_page.py -v` — smoke passes against staging.

## Out of scope

- **Per-genre OG image generation** (Vercel OG / dynamic image route) — placeholder static image acceptable. Spin off a separate prompt if it becomes a priority.
- **Cross-genre comparison page** — Tier-2-gated speculative feature. Do not build.
- **Filtering / sorting / search within the synthesis** — Tier-2-gated toolkit territory. Killed for Tier 1.
- **Drill-down modal per friction item** — Tier-2-gated.
- **Additional genres beyond `roguelike-deckbuilder` at launch** — same route, same component, different slug. No code change needed. The per-genre work is: run the synthesiser + write the editorial_intro (200–300 words) + write the churn_interpretation (one line) + publish. The raw synthesis row ships automatically; the curated editorial bits are the unavoidable 1–2 hours of human curation per genre page.

## Voice guardrails

Same rules as `fix-landing-page.md` — use the forbidden-vocabulary
list and preferred register from that prompt. Peer-to-peer, cited,
anti-hype. Don't duplicate the list here.

## Rollout

- No users. No external traffic. No migration. Single PR, direct replace of whatever's at `/genre/[slug]/`.
- No feature flag. No A/B.
- After merge + prod deploy: manually visit the page, verify all three report-block states (pre-order / live / no-report) by flipping the seed row, craft the amplification posts (Reddit, Bluesky, community share).
- No deploy from Claude — user runs the deploy script.

## PR description template

```
## Summary
Ship the free cross-genre synthesis page at /genre/[slug]/ as a
curated preview (not the raw Phase-4 dump). Author byline + editorial
intro + top-5 friction + top-3 wishlist + 3 benchmarks + churn wall
with one-line interpretation + 2-row dev priorities teaser.
Conditionally renders a pre-order / buy block when a reports row
exists for the genre. The full depth lives in the paid PDF.

## Changes
- frontend/app/genre/[slug]/page.tsx — server component, ISR 1h
- frontend/lib/api.ts — getGenreInsights, getReportForGenre
- frontend/lib/types.ts — GenreInsights, ReportSummary
- frontend/components/genre/* — synthesis sections + pre-order block
- frontend/tests/genre-page.spec.ts — Playwright coverage
- tests/smoke/test_genre_page.py — staging smoke

## Why
The synthesis page is the flagship proof artifact of the Tier 1
launch. It replaces the landing page's paid-funnel destination: the
landing CTA points here, and this page hosts both the free research
content and the pre-order / buy surface for the paid PDF.
```
