# SteamPulse — Freemium Simplification: Free-First Discovery Engine

## Vision

SteamPulse is being repositioned from a per-game paywall model to a **free discovery engine with a developer subscription tier**. Every game intelligence report is now fully free. The site is a Steam game discovery platform with AI-synthesized review intelligence — think Metacritic meets a search engine, but with LLM synthesis instead of score aggregation.

Premium is no longer about unlocking sections of a single report. It's about **stepping up in scope** — from one game to a genre, from a snapshot to a trend, from reading to acting.

---

## The Big Picture: Premium Tier (do NOT implement — context only)

These are the subscription features that will justify a monthly fee from indie developers. They are listed here so the free UI is designed with natural upgrade paths in mind:

| Feature | Description |
|---|---|
| **Genre Intelligence** | Cross-game synthesis for an entire genre: "What do players consistently want in Survival Horror that no game delivers?" |
| **Market Gap Analysis** | Features consistently requested across a genre that no current game provides — gold for pre-launch research |
| **Competitive Landscape** | Structured head-to-head: pick your game, see how it stacks up against its top competitors across every intelligence dimension |
| **Developer Dashboard** | Track your own game over time — sentiment trend, how your dev priorities evolve after patches |
| **Fresh Analysis on Demand** | Request a re-analysis using the latest reviews (vs the cached public report) |
| **Multi-game Comparison** | Side-by-side comparison of 2-5 games across all intelligence sections |
| **Custom Prompts** | Ask any question about a game's reviews: "What do players think about the economy system?" |
| **Export** | PDF / CSV / structured JSON export for investor decks and research |
| **API Access** | Programmatic access to intelligence data |

The upgrade CTAs on the free site should speak to developers, not gamers. Examples:
- "Analyzing a game in this genre? See what players want that nobody is building →"
- "Developing a competitor? Get the full competitive landscape →"

---

## What to Remove (frontend)

Delete or gut the following — they represent the old paid-unlock model:

- `components/game/PremiumUnlock.tsx` — delete entirely
- All blur CSS in `globals.css` (`.premium-blur-content`, `.premium-overlay`, `::after` gradient)
- All `"Unlock for $7"` / `"$15 for 5-pack"` CTAs
- All `<SectionLabel premium>` amber badges
- The `fullReport` / `setFullReport` state in `GameReportClient.tsx`
- The `useUserTier()` hook in `lib/auth.ts` — delete, it currently does nothing meaningful
- The `validateKey()` API call in `lib/api.ts`
- The license key `localStorage` storage
- All conditional rendering that hides or blurs sections based on tier

---

## Free Tier: What the Site Becomes

### Home Page (`/`)

Redesign as a **game discovery engine**, not a marketing page. Three zones:

**1. Search hero** — large search input, front and center. Placeholder: "Search 6,000+ Steam games…". This is the primary action. The `/search` route must be implemented (it currently exists as a form action but has no page).

**2. Discovery rows** — three horizontal scroll rows:
- "Most Discussed" (sorted by `review_count`)
- "Hidden Gems" (sorted by `hidden_gem_score`)
- "Recently Analyzed" (sorted by `last_analyzed`)

**3. Browse by Genre** — grid of genre cards with game count and a one-sentence aggregate insight where available.

No hero marketing copy. The product speaks for itself through the content.

---

### Search Page (`/search`) — implement this, it currently has no page

- Text search across game names (`?q=`)
- Filter sidebar:
  - Genre (multi-select)
  - Tag (multi-select)
  - Sentiment: Positive / Mixed / Negative
  - Review count range
- Sort: Most Reviewed, Best Sentiment, Hidden Gem Score, Recently Analyzed
- Paginated results using the existing `GameRow` card component
- Show total result count

---

### Trending Page (`/trending`) — implement this, it currently has no page

Three sections:
- Most new reviews in the last 7 days
- Biggest positive sentiment shift recently
- Top hidden gems (high `hidden_gem_score`, lower review count)

---

### Game Report Page (`/games/[appid]/[slug]`)

All sections are fully visible — no blur, no lock, no CTA to unlock. Display the complete report in order:

1. Hero (header image, name, genres, sentiment badge, hidden gem badge)
2. The Verdict (one-liner + score bar)
3. Quick Stats (review count, release year, price, developer)
4. Design Strengths
5. Gameplay Friction
6. Audience Profile
7. Sentiment Trend
8. Genre Context
9. Player Wishlist ← previously locked, now free
10. Churn Triggers ← previously locked, now free
11. Developer Priorities ← previously locked, now free
12. Competitive Context ← previously locked, now free
13. Related Games (cross-links to similar games by genre/tag)

At the bottom of the Developer Priorities section, add a **contextual developer upgrade CTA** — this is not a paywall, it is an organic upgrade prompt:

> "Developing a game in this genre? See what players want that no current game delivers. → Genre Intelligence (Pro)"

This CTA should be subtle — a single line with an arrow link, not a banner or modal.

---

### Navigation

Add a persistent nav bar (currently there is none — only a back arrow on the game report page):

- **Left**: Logo → home
- **Center**: Browse (dropdown: Genres, Tags, Developers) | Hidden Gems | Trending
- **Right**: Search icon | "For Developers →" (stub link to `/pro` — just a placeholder page for now)

The nav should be present on all pages.

---

## Backend Changes (`src/lambda-functions/lambda_functions/api/handler.py`)

### `POST /api/preview`

Currently returns a limited subset of fields (the old free tier). Now that everything is free, it should return the **full report JSON** — same as what `validate-key` returns. Keep the route name for backward compatibility. Remove the IP-based rate limiter (`rate_limiter.py` call) — there is no longer a free limit.

### `POST /api/validate-key`

Already stubbed to return the full report. Keep the route as a no-op stub. The frontend should stop calling it for content purposes — it's just dead code now but harmless to leave on the server.

### `GET /api/games`

Already exists and powers browse/listing pages. Ensure it supports all of the following query parameters:

| Parameter | Type | Description |
|---|---|---|
| `q` | string | Text search on game name (case-insensitive, partial match) |
| `genre` | string | Filter by genre slug |
| `tag` | string | Filter by tag slug |
| `developer` | string | Filter by developer slug |
| `sentiment` | `positive\|mixed\|negative` | Filter by sentiment band: positive ≥ 0.65, mixed 0.45–0.65, negative < 0.45 |
| `sort` | `review_count\|hidden_gem_score\|last_analyzed\|sentiment_score` | Sort order (descending) |
| `limit` | int | Page size (default 24) |
| `offset` | int | Pagination offset |

Response must include a `total` count field alongside the `games` array so the frontend can render pagination.

---

## Implementation Constraints

- Keep all existing TypeScript types in `lib/types.ts` — remove `tier`-related fields only
- Keep shadcn/ui components
- Keep ISR revalidation on browse/listing pages (3600s)
- Keep the dark theme and design tokens in `globals.css` — the aesthetic is correct
- No new npm dependencies unless absolutely necessary
- Keep SSR for game report pages — critical for SEO
- `GameReportClient.tsx` will shrink significantly after removing all conditional premium rendering — expected and good
- Do not add authentication — the site remains fully public with no login

---

## Definition of Done

- [ ] Home page: search hero + 3 discovery rows + genre grid
- [ ] Search page (`/search`) implemented with text search, filters, and sort
- [ ] Trending page (`/trending`) implemented with 3 sections
- [ ] Game report shows all 12 sections with no blur, no lock, no unlock CTA
- [ ] `PremiumUnlock.tsx` deleted
- [ ] All blur CSS removed from `globals.css`
- [ ] Persistent nav bar on all pages
- [ ] Contextual developer upgrade CTA at bottom of Developer Priorities section
- [ ] `/api/games` supports `q`, `sentiment`, all sort options, and returns `total`
- [ ] Rate limiter removed from `/api/preview`
- [ ] `/api/preview` returns full report
- [ ] All existing pages render without errors
