# Soft-launch SEO discipline — robots, sitemap, structured data, AI crawlers

## Context

Soft-launch goal: get all ~6,000 game pages + browse / genre / tag
pages indexed by Google **and** discoverable by AI search engines
(GPTBot, ClaudeBot, PerplexityBot — these are now ~13% of
search-equivalent query volume per 2026 SEO research). The strategy
relies on per-game pages being index-worthy without LLM reports — see
`audit-game-page-no-report-state.md` for the page-template work that
must precede this.

This prompt owns the **site-wide SEO infrastructure**:
`robots.txt`, sitemap generation, site-wide JSON-LD, canonical tags,
and OG/Twitter card defaults. Per-page game schema lives in the
sibling prompt above.

## What to do

### 1. `robots.txt`

`frontend/public/robots.txt` (or Next.js dynamic
`app/robots.ts`). Allow:

- `Googlebot`, `Bingbot`, `DuckDuckBot` — traditional search
- `GPTBot` (OpenAI), `ClaudeBot` (Anthropic), `PerplexityBot`,
  `Google-Extended`, `CCBot` — AI crawlers / training data
- `Twitterbot`, `facebookexternalhit`, `LinkedInBot` — social
  preview generators

Disallow:
- `/api/*` — JSON endpoints have no SEO value, save crawl budget
- `/admin/*` if any exists
- Any preview / draft URL paths

Reference the sitemap at the bottom: `Sitemap: https://steampulse.io/sitemap.xml`.

### 2. Sitemap

`frontend/app/sitemap.ts` (Next.js dynamic sitemap). Generate from
the live DB on each build / ISR refresh:

- Homepage, top nav pages
- All `/genre/[slug]` pages — from `tag_repo.find_genres()`
- All `/tag/[slug]` pages — top N by game count, threshold by review_count to skip dead tags
- All `/genre/[slug]/insights` pages with a synthesis row — from
  `genre_synthesis_repo.find_available_slugs()` (when the wedge ships)
- All `/games/[appid]/[slug]` pages — from
  `game_repo.find_indexable()` returning every game with
  `review_count >= 10` (or whatever threshold matches the page-template
  enrichment threshold from `audit-game-page-no-report-state.md`).
  Skip games below the threshold to avoid spam-tier indexing.
- `/developer/[slug]` pages — top N by game count

Each entry: `loc`, `lastmod` (max of relevant `*_at` timestamps),
`changefreq`, `priority` (homepage 1.0, hubs 0.8, leaf game pages 0.6).

For sites approaching 50k URLs, split into a sitemap index +
multiple `sitemap-{n}.xml` files. Likely needed once the catalog
exceeds ~50k indexable games.

Cache the sitemap response (`Cache-Control: public, s-maxage=3600`).
The DB queries are bounded and cheap (matview + indexed lookups), but
sitemap generation per request would still be wasteful.

### 3. Site-wide JSON-LD

In `frontend/app/layout.tsx`, inject `Organization` JSON-LD:

```json
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "SteamPulse",
  "url": "https://steampulse.io",
  "description": "AI-powered Steam game intelligence — synthesised review reports, audience overlap, and genre insights for the Steam catalog.",
  "sameAs": ["https://twitter.com/steampulse_io"]
}
```

Per-page schema (`VideoGame` for game pages, `CollectionPage` for
genre/tag pages, `Article` for the genre insights pages) is owned by
the page-specific prompts (`audit-game-page-no-report-state.md`,
`genre-insights-page.md`).

### 4. Canonical tags

In `app/layout.tsx` `generateMetadata()` default + every page-level
`generateMetadata()`:
- `alternates.canonical: \`https://steampulse.io${pathname}\``
- For paginated lists: canonical to page 1 unless the page itself is
  unique (test with a sample paginated genre).

### 5. OG / Twitter card defaults

In `app/layout.tsx`:

```ts
openGraph: {
  type: "website",
  siteName: "SteamPulse",
  locale: "en_US",
  images: ["/og/default.png"],  // 1200x630
},
twitter: {
  card: "summary_large_image",
  site: "@steampulse_io",
  creator: "@steampulse_io",
}
```

Per-page overrides (game pages, insights pages) inherit and override
specific fields.

### 6. Operational steps (no code, runbook)

Once deployed:
- Submit `https://steampulse.io/sitemap.xml` to Google Search Console
- Submit to Bing Webmaster Tools
- Manually request indexing for top 10 highest-value pages (homepage,
  top 5 genres, top 5 game pages by review_count) via Search Console
- Set up Search Console alerts for crawl errors + manual actions
- Verify `Crawl Stats` report after 7 days — should show GoogleBot
  and at least one AI crawler hitting pages

## Verification

1. **`/robots.txt`** loads at production URL; visually inspect.
2. **`/sitemap.xml`** loads, validates against the sitemap XSD, and
   contains expected URL counts.
3. **JSON-LD validates** in [Google's Rich Results Test](https://search.google.com/test/rich-results)
   for the homepage and a sample game page.
4. **Lighthouse SEO score ≥ 95** on homepage, a genre page, a
   no-report game page, and a with-report game page.
5. **Smoke test in `tests/smoke/`** — `tests/smoke/test_seo.py`:
   - `GET /robots.txt` returns 200 with expected user-agent allowlist
   - `GET /sitemap.xml` returns 200, parses as XML, contains > 1000
     `<url>` entries
6. **Manual**: `curl -A "GPTBot" https://steampulse.io/games/440/team-fortress-2`
   returns 200 (not 403/blocked).
7. `poetry run pytest tests/smoke/ -v && cd frontend && npm run test:e2e`.

## Out of scope (separate prompts later)

- **Per-page Schema.org markup** (VideoGame on game pages,
  CollectionPage on genre, Article on insights) — owned by their
  respective page prompts.
- **Per-genre OG image generation** (Vercel OG dynamic image route)
  — placeholder default OG acceptable for soft launch.
- **AI Search Console / GPTBot analytics** — not yet a first-class
  surface from any provider; defer until tooling exists.
- **hreflang tags** — only relevant when launching i18n.

## Rollout

- All Next.js / config changes — single PR.
- Deploys with the rest of the bundle via `bash scripts/deploy.sh
  --env staging`, then `--env production`.
- After production: do the operational submission steps within 24
  hours of deploy so indexing starts immediately.
- No deploy from Claude — user runs the deploy script.
