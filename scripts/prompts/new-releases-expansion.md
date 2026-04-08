# Expand "New Releases" into a Three-Lens Catalog Feed

## Why this exists

Now that the metadata-freshness work keeps `app_catalog`, game metadata, and tags continuously
synced with Steam, we have something genuinely valuable that nobody else surfaces well: a
real-time view of **what's appearing on Steam** and **what's actually shipping**. The two are
not the same thing and matter to different audiences:

- **Indie developers** want to know who's competing in their lane *before* launch
  (newly added) and who just shipped near them (released) so they can time announcements,
  watch wishlist competition, and benchmark.
- **Publishers / market analysts** want flow metrics — how many games appeared this week
  vs. last, genre mix shifting, release-day sentiment landing.
- **Players / press** want a fresh "what dropped today" feed with enough signal
  (early reviews, tags, price) to decide whether to look closer.

This is also strong SEO surface area: "new Steam releases today/this week", "upcoming
[genre] games", "Steam games released this month" are evergreen queries we don't currently
own.

We already have a `/new-releases` page. This prompt expands it from a single flat list into a
three-lens feed under the same URL — keeping the SEO equity, sitemap entries, and inbound nav
intact while adding the new value.

---

## What we already have

- `app_catalog.discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW()` — when our hourly catalog
  refresh first saw the appid. This is our **"first added on Steam (as observed by us)"**
  timestamp. Good enough as a proxy now that the catalog refresh runs hourly.
- `games.release_date DATE` and `games.coming_soon BOOLEAN` — populated by metadata crawl.
- `games.review_count`, `positive_pct`, `review_score_desc` — denormalized; perfect for
  "early reviews are landing" badges.
- `games.type` — lets us cleanly exclude `dlc | demo | music | tool` from the headline feeds.
- `frontend/app/new-releases/page.tsx` + `NewReleasesClient.tsx` — the existing page. Audit it
  first; it should be replaced/extended in place, keeping the same route.
- `/api/games` list endpoint with filters (genre/tag/sentiment).

## What's missing

1. No API endpoint that surfaces **newly added** appids (`app_catalog.discovered_at`) by window.
2. No API endpoint that surfaces **releases** (games that crossed `release_date`) by window
   with enriched fields (early review counts, has-analysis flag, tags).
3. No window-aware aggregate counts ("X games added today / N this week / M this month") for
   either dimension — these are the headline numbers that make the page feel alive.
4. No upcoming-releases view (`coming_soon = TRUE` ordered by `release_date`) — this is the
   highest-value cut for developers watching competition.
5. The existing `/new-releases` page does not distinguish *added* vs *released* and has no
   time-window switcher.

---

## Naming (UX)

Use the user's language, not internal codenames. The page stays **"New Releases"**. The three
sub-tabs are:

- **Released** (default lens)
- **Coming Soon**
- **Just Added**

These match how Steam, Epic, GOG, and Metacritic label the same concepts — recognition over
recall. Do not introduce brand names like "Pulse" or "Catalog Pulse" anywhere user-visible.

---

## Scope of this prompt

Build a three-lens feed at `/new-releases`, exposed as both a single page with sub-tabs and
reusable API endpoints:

### Lens 1 — Released (default)
Games where `release_date` is within the window AND `coming_soon = FALSE`. This is the
"shipped today/this week/this month" feed.

Fields per row:
- name, header_image, slug, appid, type
- developer, publisher
- release_date, days_since_release
- top tags (up to 3, from joined `game_tags`)
- price_usd / is_free
- review_count (English), positive_pct, review_score_desc
- "early sentiment" badge logic: if `review_count_english >= 10`, show the score; otherwise
  show "Reviews coming in" pill with the count
- has_analysis (we have a stored report) — links to it if so

### Lens 2 — Coming Soon
Games where `coming_soon = TRUE`, ordered by `release_date ASC NULLS LAST`. Group buckets:
- Releasing this week
- Releasing this month
- Later this quarter
- Date TBA

Same row shape minus review fields.

### Lens 3 — Just Added (new on Steam)
Games whose `app_catalog.discovered_at` falls in the selected window (today / 7d / 30d).
Excludes `type != 'game'` from the default view. Sortable by discovery time, release date,
or review count once any reviews land.

Same fields as Released plus:
- discovered_at (relative: "3h ago")
- May not yet have full metadata — see empty/loading states below

### Headline counts (every lens)
Each lens shows three pill counters at the top: **Today / This Week / This Month**, clicking
sets the window. These need to be cheap — single aggregate query per lens, cached.

---

## Backend work

### Repository layer
Add to `library_layer/repositories/catalog_repo.py` (or create
`new_releases_repo.py` if catalog_repo is getting crowded — judgment call after reading it):

- `find_recently_released(since: date, until: date, limit, offset) -> list[NewReleaseEntry]`
  `games` only, `coming_soon = FALSE`, `release_date BETWEEN since AND until`,
  `type = 'game'`.
- `count_released_between(since, until) -> int`
- `find_upcoming(limit, offset) -> list[NewReleaseEntry]`
  `coming_soon = TRUE`, ordered by `release_date NULLS LAST`.
- `count_upcoming() -> int`
- `find_recently_added(since: datetime, limit: int, offset: int, type_filter: str = 'game') -> list[NewReleaseEntry]`
  Joins `app_catalog` → `games` (LEFT JOIN — a newly added appid may not yet have metadata).
- `count_added_since(since: datetime, type_filter: str = 'game') -> int`

All return Pydantic models defined alongside (`NewReleaseEntry`) — never raw dicts. Reuse
`Game` / `GameSummary` from `library_layer/models/` if the field set matches; otherwise
define a thin feed-specific model.

**Indexes needed** (new migration, e.g. `0033_new_releases_indexes.sql`):
```sql
-- depends: <previous>
-- transactional: false
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_catalog_discovered_at
  ON app_catalog(discovered_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_games_release_date_released
  ON games(release_date DESC) WHERE coming_soon = FALSE;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_games_coming_soon_release_date
  ON games(release_date ASC NULLS LAST) WHERE coming_soon = TRUE;
```
Update `schema.py` to mirror.

### Service layer
`library_layer/services/new_releases_service.py`:
- `get_released(window: Literal['today','week','month'], page, page_size)` →
  `{ items, total, counts: {today, week, month} }`
- `get_upcoming(page, page_size)` → `{ items, total, buckets: {this_week, this_month, this_quarter, tba} }`
- `get_added(window, page, page_size)` → `{ items, total, counts: {today, week, month} }`

The window→datetime translation lives here, computed against `datetime.now(UTC)`. Counts are
returned in the same response so the UI never needs a second roundtrip.

### API layer
Add to `lambda_functions/api/`:
- `GET /api/new-releases/released?window=today|week|month&page=1&page_size=24`
- `GET /api/new-releases/upcoming?page=1&page_size=24`
- `GET /api/new-releases/added?window=today|week|month&page=1&page_size=24`

All return the same envelope: `{ items: [...], total, counts | buckets, window }`.

These endpoints are public (free tier). They are **read-mostly and very cacheable** — set
`Cache-Control: public, s-maxage=300` so CloudFront absorbs traffic.

---

## Frontend work

### Page
Expand `frontend/app/new-releases/page.tsx` in place — same route, no redirect, no rename.
The existing `NewReleasesClient.tsx` should be replaced (or refactored) to host the three-lens
UI. The default lens is **Released** so the page's existing behaviour is preserved for anyone
landing on it cold.

Routing options for sub-tabs (pick one in implementation, lean toward query string for
simplicity unless deep-link SEO wins out):
- Query string: `/new-releases?lens=released|upcoming|added&window=today|week|month`
- Nested routes: `/new-releases/released`, `/new-releases/upcoming`, `/new-releases/added`

Either way, each lens must be deep-linkable and shareable.

### Components (under `frontend/components/new-releases/`)
- `LensTabs` — three-lens switcher (Released / Coming Soon / Just Added)
- `WindowPills` — Today / This Week / This Month, updates query string
- `NewReleasesGrid` — card grid using existing game card primitives from `components/game/`.
  Do NOT build a new card from scratch; extend the existing one with the lens-specific
  metadata strip (days_since_release, "early reviews" badge, or "added 3h ago").
- `UpcomingBuckets` — grouped list view for the Coming Soon lens

### Empty / loading / error states
Each lens must handle:
- 0 results in window (e.g., quiet day) — friendly message + suggest a wider window
- Game in Just Added with no metadata yet — show skeleton card with just name +
  "metadata pending" badge instead of hiding it
- Game in Released with 0 reviews yet — show "Reviews coming in" pill, not blank

### SEO
- Per-lens `<title>` and `og:title` (e.g. "New Steam Releases This Week — SteamPulse",
  "Upcoming Steam Games — SteamPulse", "Just Added to Steam — SteamPulse")
- JSON-LD `ItemList` for the grid
- If using nested routes, add them to `frontend/app/sitemap.ts`. If using query strings, the
  existing `/new-releases` sitemap entry is sufficient — add canonical link tags per lens.
- The existing home-page nav link to `/new-releases` stays as-is

### Tests (mandatory — see CLAUDE.md frontend testing rule)
- `frontend/tests/` E2E tests for at least: lens switching, window pill switching, deep
  links, empty state, "added with no metadata" rendering, "released with no reviews" rendering
- Update `frontend/tests/fixtures/mock-data.ts` and `api-mock.ts` with the new endpoints and
  a representative payload for each lens (including a no-metadata-yet row and a
  no-reviews-yet row)

---

## Out of scope (call out, don't build)

- Email digests / RSS / push notifications — tempting follow-on, separate prompt
- "Trending registrations" (velocity of new appids per genre) — separate analytics prompt
- Wishlist count — Steam doesn't expose it; do not fake it
- Backfilling `discovered_at` for historical rows — accept that pre-feature games all share
  one timestamp; the feature gets meaningful immediately for new additions
- LLM-generated commentary on releases — out of scope here, would belong in analysis pipeline
- Auth-gated / personalized "watchlist" features — needs Auth0 first

---

## Drift checklist (verify before merging)

- [ ] `ARCHITECTURE.org` updated with the new API endpoints under the API surface section
- [ ] Migration is `CONCURRENTLY` + `transactional: false` and chained to the latest number
- [ ] `schema.py` reflects the new indexes
- [ ] Repository methods contain SQL only; service methods do all window math; handlers are thin
- [ ] All new models are `pydantic.BaseModel`, never dict / dataclass
- [ ] Responses set `Cache-Control: public, s-maxage=300`
- [ ] `type = 'game'` filter applied by default; DLC/demo/tool excluded from headline feeds
- [ ] `/new-releases` URL preserved; default lens is Released so cold landings are unchanged
- [ ] No new user-visible "Pulse" / "Catalog Pulse" branding anywhere — labels are
      Released / Coming Soon / Just Added
- [ ] Playwright tests cover all three lenses, window switching, and the two important empty
      states (no-metadata-yet, no-reviews-yet)
- [ ] No business logic leaked into repositories; no SQL leaked into services
