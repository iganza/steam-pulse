# Expand "New Releases" into a Three-Lens Catalog Feed

> **Status:** Implemented. This document describes both the motivation and the
> as-built design so it can serve as reference for future changes.

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

Strong SEO surface area too: "new Steam releases today/this week", "upcoming [genre] games",
"Steam games released this month" are evergreen queries we don't currently own.

The existing `/new-releases` page is expanded in place from a single flat list into a
three-lens feed, keeping the same URL (and its SEO equity / sitemap / inbound nav).

---

## Naming (UX)

Use the user's language, not internal codenames. The page stays **"New Releases"**. The
three sub-tabs are:

- **Released** (default lens)
- **Coming Soon**
- **Just Added**

These match how Steam, Epic, GOG, and Metacritic label the same concepts — recognition over
recall. No user-visible "Pulse" or "Catalog Pulse" branding anywhere.

---

## Three lenses

### Lens 1 — Released (default)
Games where `release_date` is within the window AND `coming_soon = FALSE`.

Fields per row:
- name, header_image, slug, appid, type
- developer + developer_slug, publisher + publisher_slug (rendered as a GameHero-style
  "by *developer* · *publisher*" line with teal links; publisher hidden when it matches
  developer — same self-published rule as `GameHero.tsx`)
- release_date, days_since_release
- top 3 tags (display) + full tag slug list (filter)
- price_usd / is_free
- review_count (English), positive_pct, review_score_desc
- **Early sentiment badge logic:** if `review_count_english >= 10`, show `{positive_pct}%`;
  otherwise show "Reviews coming in · {count}" or "No reviews yet"
- has_analysis — "Analyzed" pill in the top-right of the card image

### Lens 2 — Coming Soon
Games where `coming_soon = TRUE`, ordered by `release_date ASC NULLS LAST`. Same row shape
minus review fields. Summary bucket counts shown above the grid:
- Releasing this week
- Releasing this month
- Later this quarter
- Date TBA

**No time-window pills** (by design — see *Time windows* section below for rationale).
Genre and Tag filters still apply.

### Lens 3 — Just Added (new on Steam)
Games whose `app_catalog.discovered_at` falls in the selected window. Includes rows where
metadata hasn't been crawled yet — those render as a **"metadata pending" skeleton card**
with just the name and "added {relative} ago" instead of being hidden.

---

## Time windows (Released and Just Added only)

Released and Just Added each expose four window pills with live counts. The two lenses
use slightly different bound semantics because they operate on different column types:

| Pill | Released (DATE, inclusive calendar days) | Just Added (TIMESTAMPTZ, rolling) |
|---|---|---|
| **Today** | `release_date = CURRENT_DATE` — 1 calendar day | `discovered_at >= now - 24h` — last 24 hours |
| **This Week** | `release_date >= today - 6` — 7 inclusive days | `discovered_at >= now - 7d` |
| **This Month** | `release_date >= today - 29` — 30 inclusive days | `discovered_at >= now - 30d` |
| **This Quarter** | `release_date >= today - 89` — 90 inclusive days | `discovered_at >= now - 90d` |

**Why the off-by-one on Released.** The repo WHERE clause is
`release_date >= since AND release_date <= today` (both inclusive). For N calendar days
of data the lower bound must be `today - (N-1)` — subtracting N directly would yield
N+1 days. `_window_start_date()` encodes this; `_window_start()` for Just Added stays at
the straight N-day subtraction because it's a half-open `>=` on a TIMESTAMPTZ.

**No "All time" option.** The feed answers "what's fresh?" not "show me the full catalog."
`/search` and `/genre/*` already cover exhaustive browsing. The empty-state offers both
"Try This Quarter →" and "Browse the full catalog →" (linking to `/search`) so users who
want a wider scope have an obvious path.

### Coming Soon deliberately has no time-window pills

This is an intentional exception, not an oversight. Five reasons:

1. **The list is already sorted by the dimension the windows would filter.** Coming Soon is
   `ORDER BY release_date ASC NULLS LAST` — the first page of results *is* next week's
   releases, the next page is next month's, and so on. A window filter over an
   already-date-sorted list duplicates what scrolling already does. Released and Just Added
   don't have this property because their firehose is too large for scroll to be a
   substitute for a cutoff.
2. **The cohort is small and curated.** Released has thousands of new rows per week; Coming
   Soon is bounded by however many developers have flagged `coming_soon=TRUE` on Steam
   (typically a few thousand total). Users can page meaningfully without narrowing first.
3. **The user's mental model is different.** Released and Just Added answer *"what happened
   recently?"* — a backward-looking question where windows are natural. Coming Soon answers
   *"what should I watch?"* — a scanning/bookmarking task, not a cutoff task.
4. **Genre + Tag filters still carry their weight on this lens.** "Upcoming roguelikes" is
   a real question; those filters stay. Time pills are the ones that don't earn their pixels
   on this lens specifically.
5. **The bucket summary strip already surfaces the flow metric.** "This week: N · This
   month: N · Later: N · TBA: N" is the actual insight users want from time information on
   Coming Soon. It's informational, not navigational — and that's the right role here.

If this ever feels wrong in user testing, the right move is to add forward-looking pills
(next 7d / 30d / 90d / TBA), NOT to reuse the backward-looking Released/Just Added pills.
Mixing directions in one pill row would be the worst outcome.

---

## Filters

Two dropdown filters next to the window pills, applying to all three lenses:

- **Genre** — populated from `/api/genres`
- **Tag** — populated from `/api/tags/top?limit=40`

Both are single-select, slug-valued, and deep-linkable via `?genre=...&tag=...`. A
**Clear filters** button appears when either is set; an active-filter chip row shows the
human-readable names below the filter row.

These are the two dimensions that actually matter for a freshness feed. Other `FilterBar`
dimensions (sentiment, min-reviews, year range, deck compatibility, analyzed-only) don't
fit the mental model of "what's new this week?" and are intentionally out of scope —
users who want those dimensions go to `/search`.

---

## Backend architecture

### Materialized view: `mv_new_releases`

Everything on the page reads from a single materialized view. **Never the base tables.**

**Schema (migration `0034_new_releases_matview.sql`):**

```sql
CREATE MATERIALIZED VIEW mv_new_releases AS
SELECT
    ac.appid, COALESCE(g.name, ac.name) AS name,
    g.slug, g.type,
    g.developer, g.developer_slug, g.publisher, g.publisher_slug,
    g.header_image, g.release_date,
    COALESCE(g.coming_soon, FALSE) AS coming_soon,
    g.price_usd, COALESCE(g.is_free, FALSE) AS is_free,
    g.review_count, g.review_count_english, g.positive_pct, g.review_score_desc,
    ac.discovered_at, g.crawled_at AS meta_crawled_at,
    (g.appid IS NULL) AS metadata_pending,
    CASE WHEN g.release_date IS NOT NULL AND NOT COALESCE(g.coming_soon, FALSE)
         THEN (CURRENT_DATE - g.release_date) END AS days_since_release,
    EXISTS(SELECT 1 FROM reports r WHERE r.appid = ac.appid) AS has_analysis,
    top_tags       text[],   -- names, top 3 by votes DESC (display)
    top_tag_slugs  text[],   -- all slugs (filter)
    genres         text[],   -- names (display)
    genre_slugs    text[]    -- slugs (filter)
FROM app_catalog ac
LEFT JOIN games g ON g.appid = ac.appid
WHERE (g.type IS NULL OR g.type = 'game')
  AND (
    (g.release_date IS NOT NULL AND NOT COALESCE(g.coming_soon, FALSE)
     AND g.release_date >= CURRENT_DATE - INTERVAL '365 days')
    OR COALESCE(g.coming_soon, FALSE) = TRUE
    OR ac.discovered_at >= NOW() - INTERVAL '90 days'
  );
```

**Why these bounds:**
- **LEFT JOIN games** so newly discovered appids without metadata still show up in the
  Just Added lens with a pending badge.
- **`type IS NULL OR type = 'game'`** excludes DLC / demos / music / tools from the feed.
- **365-day released window** is wide enough that "This Quarter" (90d) can never hit the
  boundary, and gives us headroom if we ever want a "This Year" pill.
- **90-day discovered window** bounds the Just Added lens.
- **coming_soon rows** are always included regardless of date.

**Indexes:**
- `UNIQUE INDEX mv_new_releases_appid_idx (appid)` — required for `REFRESH CONCURRENTLY`
- Partial b-tree on `release_date DESC` where `coming_soon = FALSE` — Released lens ordering
- Partial b-tree on `release_date ASC NULLS LAST` where `coming_soon = TRUE` — Upcoming lens
- b-tree on `discovered_at DESC` — Just Added lens
- **GIN index on `genre_slugs`** — supports array-contains filters like
  `genre_slugs @> ARRAY['action']::text[]`. Do NOT use `'action' = ANY(genre_slugs)` —
  that's equivalent in result but Postgres won't use the GIN index for it.
- **GIN index on `top_tag_slugs`** — same rule, use `@> ARRAY[...]::text[]`.

**Mirrored** in `src/library-layer/library_layer/schema.py` under `MATERIALIZED_VIEWS` so
the test suite (`create_all`) builds the same shape against `steampulse_test`.

### Refresh wiring

**Do not write a new refresh path.** Just register the matview in the existing pipeline
by appending its name to the **module-level** `MATVIEW_NAMES` tuple in
`library_layer/repositories/matview_repo.py` (it's a module constant, NOT a class
attribute on `MatviewRepository` — don't reference it as `MatviewRepository.MATVIEW_NAMES`):

```python
# src/library-layer/library_layer/repositories/matview_repo.py
MATVIEW_NAMES: tuple[str, ...] = (
    ..., "mv_new_releases",
)
```

That's the entire wiring. The existing `admin/matview_refresh_handler.py` Lambda picks it up
automatically — it's triggered by SQS (report-ready, catalog-refresh-complete) and by an
EventBridge schedule (every 6h) with a 5-minute debounce, and writes to `matview_refresh_log`.
`REFRESH MATERIALIZED VIEW CONCURRENTLY` is used because of the unique index.

### Repository: `NewReleasesRepository`

`src/library-layer/library_layer/repositories/new_releases_repo.py` — pure SQL I/O against
the matview. Uses the project's `BaseRepository` factory pattern (constructed with
`get_conn` callable for lazy / reconnect-safe connection handling, like every other repo).

Methods:
- `find_recently_released(since, until, limit, offset, genre, tag)` — `since=None` skips the
  lower bound (kept as a defensive branch, not currently used by the service)
- `count_released_between(since, until, genre, tag)`
- `find_upcoming(limit, offset, genre, tag)`
- `count_upcoming(genre, tag)`
- `find_recently_added(since, limit, offset, genre, tag)`
- `count_added_since(since, genre, tag)`

All return `list[NewReleaseEntry]` or `int`. Never dicts.

Filter SQL is assembled by a tiny `_filter_clause()` helper that emits
`" AND genre_slugs @> ARRAY[%s]::text[] AND top_tag_slugs @> ARRAY[%s]::text[]"` fragments
plus a params list. **Note:** the `@>` array-contains operator is mandatory — `= ANY(col)`
is functionally equivalent but Postgres will NOT use the GIN indexes for it. If you see
`= ANY(array_col)` in this repo, that's a bug.

### Model: `NewReleaseEntry`

`src/library-layer/library_layer/models/new_release.py` — a Pydantic `BaseModel` mirroring
the matview column set. `ConfigDict(from_attributes=True)` so it validates RealDictRow rows
straight from psycopg2.

### Service: `NewReleasesService`

`src/library-layer/library_layer/services/new_releases_service.py` — all business logic
lives here. Repository is SQL-only, handler is thin.

```python
Window = Literal["today", "week", "month", "quarter"]
```

Methods:
- `get_released(window, page, page_size, genre, tag)`
- `get_upcoming(page, page_size, genre, tag)`
- `get_added(window, page, page_size, genre, tag)`

Response envelope (Released / Just Added):
```json
{
  "items": [...],
  "total": 42,
  "window": "week",
  "page": 1,
  "page_size": 24,
  "filters": {"genre": null, "tag": null},
  "counts": {"today": 3, "week": 42, "month": 180, "quarter": 540}
}
```

Response envelope (Coming Soon) replaces `counts` with `buckets`:
```json
{"buckets": {"this_week": 5, "this_month": 22, "this_quarter": 60, "tba": 12}}
```

Page size is clamped to `[1, 100]`; page is clamped to `>= 1`. Window→datetime translation
(`_window_start` / `_window_start_date`) is the only non-trivial logic and lives here.

Headline counts are computed inline in the same call so the UI never needs a second
roundtrip. Each lens runs 5 count queries (1 total + 4 window counts); they hit the matview
+ GIN indexes and are effectively free.

### API endpoints

`src/lambda-functions/lambda_functions/api/handler.py`:

- `GET /api/new-releases/released?window=today|week|month|quarter&page&page_size&genre&tag`
- `GET /api/new-releases/upcoming?page&page_size&genre&tag`
- `GET /api/new-releases/added?window=today|week|month|quarter&page&page_size&genre&tag`

All three set `Cache-Control: public, s-maxage=300, stale-while-revalidate=600` so
CloudFront absorbs traffic. Invalid `window` values return **FastAPI's native 422
validation error** (the handler signature types `window` as the `Window` Literal, so
FastAPI validates against the allowed set automatically — no manual `_VALID_WINDOWS`
check, no `type: ignore`).
`page_size` is validated via FastAPI `Query(ge=1, le=100)`.

---

## Frontend

### Page

`frontend/app/new-releases/NewReleasesClient.tsx` — the existing page, rewritten in place.
Same route, no redirect, no rename, same sitemap entry. Default lens is **Released** so
cold landings behave as before.

URL state (all deep-linkable):
- `?lens=released|upcoming|added` (default: `released`)
- `?window=today|week|month|quarter` (default: `week`)
- `?genre=<slug>`
- `?tag=<slug>`
- `?page=<n>`

### Components

Self-contained inside the client file rather than extracted — the whole page is ~450 lines
and the components are tightly coupled to URL state. Split later if anything else needs them.

- **Lens tabs** — three buttons with Sparkles / Calendar / Clock icons, `data-testid="lens-*"`
- **Window pills** — four rounded pills with live count badges, hidden when lens=upcoming
- **Filter row** — two native `<select>` dropdowns (Genre, Tag) + Clear button + result count
- **Upcoming buckets** — flat "X · Y · Z · TBA" strip, shown when lens=upcoming
- **FeedCard** — card grid item; see below
- **Pagination** — Prev / Next with total-pages clamp

### FeedCard — nested-anchor fix

The card is a `<div>` container, **not** an outer `<Link>`. Inside it:

- Image area is its own `<Link href={gameHref}>` (block-level, fills aspect ratio)
- Title is its own `<Link href={gameHref}>`
- Developer is a `<Link href={/developer/slug}>`
- Publisher is a `<Link href={/publisher/slug}>` when `publisher_slug !== developer_slug`

This avoids the "`<a>` cannot be a descendant of `<a>`" hydration error we hit on the first
attempt when the whole card was wrapped in one outer `<Link>`. Hover scale animation is
preserved via `group` / `group-hover:` classes on the container div.

The developer/publisher line uses the **same pattern as `GameHero.tsx`** — teal links,
"by X · Y" format, self-published hiding. This is intentional duplication; if a third place
needs it, extract a `<DeveloperPublisherCredit>` component then.

`slugify` is imported from `@/lib/format` (shared with `GameHero.tsx`).

### API client

`frontend/lib/api.ts` adds:
- `type NewReleasesWindow = "today" | "week" | "month" | "quarter"`
- `NewReleaseEntry`, `NewReleasesFilters`, `NewReleasesWindowResponse`,
  `NewReleasesUpcomingResponse`
- `getNewReleasesReleased(window, opts)`, `getNewReleasesUpcoming(opts)`,
  `getNewReleasesAdded(window, opts)` — `opts` is `{ page, pageSize, genre, tag }`

All three set `next: { revalidate: 300 }` so Next.js ISR stacks on top of the CDN cache
and the matview for a three-layer cache.

### Empty state

- 0 results → "No games match these filters" + `Clear filters` button (if any set) +
  `Try This Quarter →` (if window isn't already quarter) + `Browse the full catalog →`
  linking to `/search`
- Just Added row with no metadata → skeleton card with `data-testid="pending-metadata-card"`
  and "metadata pending · added {relative} ago"
- Released row with `review_count_english < 10` → "Reviews coming in · {n}" or
  "No reviews yet" pill instead of a blank score

---

## Tests

### Backend unit tests

`tests/services/test_new_releases_service.py` — 11 tests covering:

- `_window_start` for today / week / quarter
- `_window_start_date` for quarter (90d ago)
- Released envelope shape + headline counts call count (5: total + 4 windows)
- Released with `window=quarter` passes a 90-day-old `since` to the repo
- Released with genre+tag filters passed through to the repo
- Just Added window→datetime translation (tz-aware UTC, ~24h for `today`)
- Just Added filter passthrough
- Upcoming bucketing (this_week / this_month / this_quarter / tba)
- Upcoming filter passthrough
- Page clamping (negative → 1, huge → 100)

All use `MagicMock` for the repo — no DB needed. **11/11 pass.**

### Playwright E2E

`frontend/tests/new-releases.spec.ts` — 10 tests covering:
- Default Released lens renders heading, window pills, grid
- Switching to Coming Soon hides pills, shows buckets
- Window pill click updates URL
- Quarter pill present and selectable
- Just Added metadata-pending card renders
- Coming Soon empty state
- Deep-link `?lens=added&window=today` sets both `aria-pressed`
- Genre filter dropdown updates URL and shows Clear button
- Tag filter deep-link reflected in dropdown
- Clear filters removes both `genre` and `tag` from URL

### Mocks

`frontend/tests/fixtures/api-mock.ts`:
- New `mockNewReleasesRoutes(page)` with routes for all three endpoints, returning two
  representative rows (one analyzed + tagged, one metadata-pending) and correct envelope
  shapes including `filters` and `counts`/`buckets`
- Wired into `mockAllApiRoutes`

`frontend/tests/navigation-flows.spec.ts` — the legacy "/new-releases page loads with tabs"
test was updated to assert the three new lens tabs via `data-testid`.

---

## Out of scope (called out, not built)

- Email digests / RSS / push notifications — separate prompt
- "Trending registrations" (velocity of new appids per genre) — separate analytics prompt
- Wishlist count — Steam doesn't expose it; do not fake it
- Backfilling `discovered_at` for historical rows — pre-feature games share one timestamp;
  the feature became meaningful immediately for new activity
- LLM-generated commentary on releases — belongs in the analysis pipeline
- Auth-gated / personalized "watchlist" features — needs Auth0 first
- "All time" window — deliberately omitted; a 12k-row grid scroll is not a feed.
  `/search` and `/genre/*` are the escape hatches.
- Reusing the `ToolkitState`-coupled `FilterBar` — mismatched mental model (sentiment /
  min-reviews / year range don't apply to "what's new this week")

---

## Drift checklist (for future changes)

- [x] `mv_new_releases` defined in migration 0034 and mirrored in `schema.py`
- [x] Matview registered in `MATVIEW_NAMES` — auto-refreshed by existing Lambda
- [x] Unique index on `appid` present (required for `REFRESH CONCURRENTLY`)
- [x] GIN indexes on `genre_slugs` and `top_tag_slugs` so filtering is index-backed
- [x] Repository methods contain SQL only; service does all window math; handlers are thin
- [x] All models are `pydantic.BaseModel`
- [x] API responses set `Cache-Control: public, s-maxage=300, stale-while-revalidate=600`
- [x] `type = 'game'` filter applied by default (DLC/demo/tool excluded)
- [x] `/new-releases` URL preserved; default lens is Released
- [x] No user-visible "Pulse" / "Catalog Pulse" branding — labels are
      Released / Coming Soon / Just Added, windows are Today / Week / Month / Quarter
- [x] Coming Soon has no time-window pills — bucket summary strip is display-only,
      intentional. See "Time windows" section for the five reasons.
- [x] Repository genre/tag filters use `@> ARRAY[%s]` (GIN-indexable), NOT `= ANY(array)`
      which would silently ignore the GIN indexes
- [x] `NewReleaseEntry.price_usd` has a field_serializer to emit float (not Decimal string)
      so the JSON contract matches the frontend's `number | null` expectation
- [x] Frontend validates `lens` and `window` URL params against allowed sets and falls back
      to defaults — an invalid deep link shouldn't render an empty grid
- [x] FeedCard uses a `<div>` wrapper with per-element `<Link>`s to avoid nested anchors
- [x] Developer/publisher credit line mirrors `GameHero.tsx` pattern exactly
- [x] Playwright tests cover all three lenses, all four windows, filter flow, and the two
      important empty/pending states
- [x] No business logic leaked into repositories; no SQL leaked into services
