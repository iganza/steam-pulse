# SteamPulse — Free-First Discovery Engine: Full Redesign

## Catalog Scope (important — read first)

SteamPulse shows **all ~100k Steam games**, not just analyzed ones. Every Steam game has a page. AI-generated analysis is only present for games that have crossed the review threshold (exact number TBD, roughly 100–500 reviews). Games below the threshold show metadata — name, genres, tags, description, review count, screenshots — with an "Analysis not yet available" state. This distinction must be respected throughout the UI.

---

## Vision

SteamPulse is a **free Steam game intelligence platform**. No paywalls, no locked content, no license keys. The site is a discovery engine for the full Steam catalog, with AI-synthesized review intelligence layered on top for eligible games. Think RAWG.io or IGDB for discovery, with Metacritic-style AI synthesis as the value-add layer.

Premium is a **subscription tier for advanced analysis** — genre synthesis, competitive research, trend analysis across the catalog. These go above the per-game view and are not implemented yet. The free site should be designed with natural, non-intrusive upgrade paths for developer users.

---

## Part 1: Remove All Locked/Premium Content

Delete or gut the following — they represent the old per-game paywall:

- `components/game/PremiumUnlock.tsx` — delete entirely
- All blur CSS in `globals.css` (`.premium-blur-content`, `.premium-overlay`, `::after` gradient)
- All `"Unlock for $7"` / `"$15 for 5-pack"` CTAs and pricing text
- All `<SectionLabel premium>` amber badges
- The `fullReport` / `setFullReport` state in `GameReportClient.tsx`
- The `useUserTier()` hook in `lib/auth.ts` — delete entirely
- The `validateKey()` API call and license key `localStorage` in `lib/api.ts`
- All conditional rendering that hides or blurs sections based on tier

---

## Part 2: Navigation (implement across all pages)

Add a persistent top navigation bar. There is currently none. This is required on every page.

**Layout:**
```
[SteamPulse logo]   Browse ▾   Hidden Gems   New Releases   Trending      [🔍 Search bar]   [For Developers →]
```

**Browse dropdown expands to:**
- Genres (shows top 10 genres with game counts, "View all genres →")
- Tags (shows top 10 tags, "View all tags →")
- Developers (search or top developers, "View all →")

**"For Developers →"** links to `/pro` — a stub page for now listing planned Pro features.

**Breadcrumbs** appear on all leaf pages (game reports, genre/tag/developer index pages):
```
Home > Action > Half-Life 2
Home > Tags > Roguelike > Hades
Home > Developers > Valve > Half-Life 2
```

---

## Part 3: Home Page (`/`)

Redesign as a discovery engine, not a marketing page. Remove all marketing copy. Structure:

### 3.1 Search Hero
Large, central search input. Placeholder: `"Search 100,000+ Steam games…"`. Autocomplete on game name as user types (calls `GET /api/games?q=&limit=8` for typeahead). Pressing enter navigates to `/search?q=`.

### 3.2 Curated Discovery Rows
Four horizontal scrollable rows, each showing 8–10 `GameCard` tiles with a "See all →" link:

| Row label | Sort / Filter | "See all" links to |
|---|---|---|
| **Most Popular** | `sort=review_count` | `/search?sort=review_count` |
| **Top Rated** | `sort=sentiment_score`, min 200 reviews | `/search?sort=sentiment_score` |
| **Hidden Gems** | `sort=hidden_gem_score` | `/search?sort=hidden_gem_score` |
| **New on Steam** | `sort=release_date` (last 90 days) | `/new-releases` |

### 3.3 Just Analyzed
A smaller row showing 6 games most recently processed by SteamPulse (`sort=last_analyzed`). Shows a "freshly analyzed" badge. "See all →" links to `/search?sort=last_analyzed`.

### 3.4 Browse by Genre
Grid of genre cards. Each shows genre name, game count, and analyzed game count. Clicking navigates to `/genre/{slug}`.

### 3.5 Browse by Tag
Horizontal scrollable tag cloud. Clicking navigates to `/tag/{slug}`.

---

## Part 4: Game Catalog Page (`/search`)

This is the primary browse/search interface. It must handle ~100k records efficiently via server-side pagination.

### Layout
Two-column layout: **filter sidebar (left, ~280px)** + **results area (right)**. On mobile, filters collapse to a top filter bar.

### Filter Sidebar
All filters are reflected in the URL query string so searches are shareable and bookmarkable.

| Filter | Type | Notes |
|---|---|---|
| Search | Text input | Live search on game name, `?q=` |
| Genre | Multi-select checkboxes | Show up to 20 genres with counts |
| Tags | Multi-select with search | Show top tags, searchable |
| Developer | Text search → select | Typeahead search |
| Release Year | Range slider or year select | `?year_from=&year_to=` |
| Review Count | Range presets | Any / 50+ / 200+ / 1000+ / 10000+ |
| Sentiment | Radio: All / Positive / Mixed / Negative | Only applies to analyzed games |
| Analysis | Checkbox: "Analyzed only" | Filters to games with AI reports |
| Price | Radio: All / Free / Under $10 / $10–$20 / $20+ | |

### Results Area
**View toggle (top right):** Grid view (default) | List/Table view

**Grid view:** 3–4 columns of `GameCard` tiles. Each shows: header image, game name, primary genre, sentiment badge (if analyzed), review count, hidden gem indicator.

**List/Table view:** Denser, sortable table. Columns:
- Game name + thumbnail
- Primary Genre
- Tags (first 3)
- Release Date
- Review Count
- Sentiment Score (or "—" if not analyzed)
- Hidden Gem Score (or "—")
- Analysis status badge (Analyzed / In Progress / Not Yet)

All column headers are clickable to sort. Active sort column shows direction arrow.

**Sort options (above results, also in sidebar):**
- Most Reviewed (default)
- Best Sentiment
- Hidden Gem Score
- Recently Released
- Recently Analyzed
- Alphabetical A–Z

**Pagination:** Page number navigation (not infinite scroll) — important for SEO and navigating large result sets. Show: `← Prev | 1 2 3 … 142 | Next →`. Show result count: `Showing 25–48 of 2,341 games`.

### URL pattern
`/search?q=hollow+knight&genre=action&tag=roguelike&sort=review_count&view=list&page=2`

All state lives in the URL. Browser back/forward works naturally. No client-side-only state.

---

## Part 5: Genre Index Pages (`/genre/[slug]`)

One page per genre, e.g., `/genre/action`, `/genre/survival-horror`.

**Header:**
- Genre name + game count + analyzed game count
- One-paragraph AI-generated genre overview (from `genres` table if available, otherwise omit)
- Sort + filter controls (inherits search page filters, pre-filtered to this genre)

**Content:**
- Same grid/list toggle as the search page
- Same pagination
- "Top Picks" section above the main list: 3 highlighted games (highest sentiment + highest review count)

**URL pattern:** `/genre/action?sort=hidden_gem_score&page=3`

Implement ISR with 1-hour revalidation.

---

## Part 6: Tag Index Pages (`/tag/[slug]`)

Same structure as genre index pages. `/tag/roguelike`, `/tag/open-world`, etc.

**Additional:** Show related tags (tags that frequently co-occur with this one). E.g., on `/tag/roguelike` show chips: `turn-based`, `indie`, `dungeon-crawler`.

---

## Part 7: Developer Pages (`/developer/[slug]`)

One page per developer, e.g., `/developer/valve`.

**Header:** Developer name, total games on Steam, games in SteamPulse catalog, average sentiment across all their analyzed games.

**Content:**
- List of all their games, same grid/list toggle
- Sorted by release date by default

**Contextual Pro CTA (subtle, non-blocking):**
> "Want a competitive analysis across all games in this developer's primary genre? → Developer Intelligence (Pro)"

---

## Part 8: Game Report Page (`/games/[appid]/[slug]`)

### 8.1 For Analyzed Games
All sections visible, no blur, no lock. Full report:

1. Hero (header image, name, genres, tags, sentiment badge, hidden gem badge)
2. The Verdict (one-liner + score bar)
3. Quick Stats (review count, release year, price, developer, last analyzed date)
4. Design Strengths
5. Gameplay Friction
6. Audience Profile
7. Sentiment Trend
8. Genre Context
9. Player Wishlist
10. Churn Triggers
11. Developer Priorities
12. Competitive Context
13. **Related Games** — two rows:
    - "More in [Primary Genre]" — 6 games from the same genre, sorted by sentiment
    - "You might also like" — 6 games sharing the most tags with this game

**Footer of Developer Priorities section — contextual Pro CTA (one line, subtle):**
> "Researching the [genre] market? See what players want that no game currently delivers. → Genre Intelligence (Pro)"

### 8.2 For Unanalyzed Games (below review threshold)
Show the game metadata page — this is still valuable:
- Hero section with header image, name, genres, tags
- Store description
- Quick stats (review count, release date, price, developer)
- Review count bar (progress toward analysis threshold: "412 of 500 reviews needed")
- Screenshots carousel
- Related Games section (same logic)
- Message: "AI analysis available once this game reaches [N] reviews. Check back soon."

Do NOT show empty analysis sections. The metadata page is a clean, intentional experience.

---

## Part 9: New Releases Page (`/new-releases`)

Games released on Steam in the past 90 days (from `release_date`), filtered to games in the SteamPulse catalog. Paginated list/grid, same controls as search page. Secondary tab: "Just Analyzed" — games with freshest `last_analyzed` timestamp.

Two tabs:
- **New on Steam** (sorted by `release_date` desc)
- **Just Analyzed** (sorted by `last_analyzed` desc)

---

## Part 10: Trending Page (`/trending`)

Three curated sections (ISR, 1-hour revalidation):

1. **Rising** — games with the most new reviews in the last 30 days (requires `review_count` delta tracking, or use a proxy: games added/updated recently with high counts)
2. **Top Rated** — best `sentiment_score` with minimum 200 reviews
3. **Hidden Gems** — top `hidden_gem_score` — full paginated list

---

## Part 11: Backend Changes

### `GET /api/games` — expand filter/sort support

Must support all of the following query params. All are optional and combinable:

| Param | Type | Description |
|---|---|---|
| `q` | string | Case-insensitive partial match on `name` |
| `genre` | string | Genre slug |
| `tag` | string | Tag slug |
| `developer` | string | Developer slug |
| `year_from` | int | Release year range start |
| `year_to` | int | Release year range end |
| `min_reviews` | int | Minimum review count |
| `has_analysis` | bool | Filter to games with completed AI reports |
| `sentiment` | `positive\|mixed\|negative` | positive ≥ 0.65, mixed 0.45–0.65, negative < 0.45 |
| `price_tier` | `free\|under_10\|10_to_20\|over_20` | Price range |
| `sort` | see values below | Default: `review_count` |
| `limit` | int | Page size, default 24, max 100 |
| `offset` | int | Pagination offset |

Sort values: `review_count`, `sentiment_score`, `hidden_gem_score`, `release_date`, `last_analyzed`, `name`

Response schema:
```json
{
  "total": 2341,
  "games": [ ... ]
}
```

### `GET /api/games/{appid}/report`

New endpoint. Returns the full `GameReport` JSON for analyzed games. If no report exists: `{"status": "not_available", "review_count": 312, "threshold": 500}`. Does not trigger analysis (analysis is triggered separately). This endpoint is used by the game report SSR page.

### `GET /api/genres` and `GET /api/tags`

These likely exist but must return `game_count` and `analyzed_count` per item. Used by filter sidebar and browse pages.

### `POST /api/preview`

Remove the IP rate limiter entirely. Return the full report (same as current `validate-key` response). Keep the route for backward compatibility.

---

## Part 12: SEO Considerations

Game report pages, genre pages, and tag pages must be server-rendered (SSR or ISR). Key requirements:

- Canonical URLs with slugs: `/games/440/team-fortress-2` not `/games/440`
- `<title>`: `{Game Name} Reviews & Analysis — SteamPulse`
- `<meta description>`: use the `one_liner` from the AI report, or the Steam description if not yet analyzed
- Open Graph tags with header image
- Genre and tag pages: ISR at 1-hour revalidation
- Game report pages: ISR at 24-hour revalidation
- Structured data (JSON-LD): `VideoGame` schema on game pages with `aggregateRating`

---

## Implementation Constraints

- No new npm dependencies unless absolutely necessary
- Keep shadcn/ui components and the existing dark design system
- Keep Next.js App Router — no `pages/` directory
- URL state over React state wherever possible (filters, sort, pagination, view mode)
- Keep SSR/ISR — no client-only pages for anything that should be indexed
- Do not add authentication of any kind

---

## Definition of Done

- [ ] All blur/lock/paywall code removed (`PremiumUnlock.tsx` deleted, blur CSS removed)
- [ ] Persistent nav bar with Browse dropdown, breadcrumbs on all pages
- [ ] Home page: search hero, 4 discovery rows, genre grid, tag cloud
- [ ] `/search` with filter sidebar, grid/list toggle, sortable table, URL-based state, page-number pagination
- [ ] `/genre/[slug]` index pages with top picks + paginated list
- [ ] `/tag/[slug]` index pages with related tags + paginated list
- [ ] `/developer/[slug]` pages with game list
- [ ] `/new-releases` with "New on Steam" and "Just Analyzed" tabs
- [ ] `/trending` with 3 sections
- [ ] Game report: all 12 sections visible, related games rows, breadcrumbs, metadata-only state for unanalyzed games
- [ ] `GET /api/games` supports all listed filter/sort params, returns `total`
- [ ] `GET /api/games/{appid}/report` endpoint added
- [ ] `POST /api/preview` returns full report, no rate limiter
- [ ] All pages have correct `<title>`, `<meta description>`, and Open Graph tags
