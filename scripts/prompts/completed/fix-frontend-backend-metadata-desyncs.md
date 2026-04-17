# Fix frontend/backend metadata desyncs

## Context

Copilot surfaced three data-plumbing bugs on `main` during PR #97
review. All three were the same shape: a field exists in the Python
model and the frontend type, but one hop in the data pipeline never
populates it, so the frontend silently falls back to URL-derived text
or an all-language number that doesn't line up with Steam's
English-implicit sentiment metrics.

A follow-up audit of the same area (handler.py + the game page
resolver + every other per-entity page) turned up three more
instances of the same pattern.

PR #97 was reverted, so the original three fixes never made it onto
`main`. This PR therefore lands **both** sets together — Part 1
(reapplied from the reverted PR #97) and Part 2 (the audit
follow-ups) — so reviewers see the full arc and the backlog clears in
one go. Part 1 below is no longer "already shipped"; treat the
descriptions as the actual changes in this diff.

Backlog pointer: when this PR lands, delete the "Pre-existing bugs
(fix before resuming feature work)" sub-section from `steam-pulse.org`
→ Backlog, and replace it with a completed-work note in the
stage-0 operational log.

---

## Part 1 — Reapplied from PR #97 (now part of this diff)

These three were originally part of PR #97 and reverted along with
the rest of that branch. They are reapplied here so the full arc
ships in one PR.

### 1.1 `game_meta` was missing `name` and `slug`
`src/lambda-functions/lambda_functions/api/handler.py` — `get_game_report`

The `/api/games/{appid}/report` response's `game_meta` dict did not
include `game.name` or `game.slug`. Both fields exist on the `Game`
pydantic model (`src/library-layer/library_layer/models/game.py:14-15`)
and are always populated in the DB. The dict-construction in the
handler just never reached for them.

**Fix in this PR:** added `"name": game.name`, `"slug": game.slug`, and
(related — see 1.3 below) `"review_count_english":
game.review_count_english` to the dict.

### 1.2 `gameData.gameName` was never populated on the server page
`frontend/app/games/[appid]/[slug]/page.tsx` — `GameReportPage`

The resolver built a `gameData` object with `gameName?: string` but
never assigned to it. Consequences:
- `GameReportClient` fell back to the hardcoded literal `"Game Report"`
  for the hero title of unanalyzed pages.
- JSON-LD `@type: VideoGame` emitted `"name": "Unknown Game"` for the
  same pages — visible to Google/Bing crawlers.

**Fix in this PR:** once `g.name` is present on `game_meta` (1.1), set
`gameData.gameName = g.name`; after the try/catch, fall back to a
slug-derived title cased string matching the `generateMetadata`
helper, so the client component always receives a string.

### 1.3 `gameData.reviewCount` desynced from English-implicit sentiment
`frontend/app/games/[appid]/[slug]/page.tsx`

The resolver first set `gameData.reviewCount = reportData.review_count`
(top-level field; backend computed as `review_count_english or
review_count`, English-aligned with fallback), then a few lines later
overwrote it with `g.review_count` (all-language). The resulting
number was shown next to `positive_pct` and `review_score_desc`,
both of which are English-implicit — so the review count was
silently inconsistent with the sentiment it was displayed beside.

**Fix in this PR:** the backend now exposes `review_count_english` on
`game_meta` explicitly (1.1); the frontend consumes
`g.review_count_english` instead of `g.review_count`. The
English-aligned count now stays aligned with `positive_pct` and
`review_score_desc`.

---

## Part 2 — What this PR fixes

Same shape as Part 1 — a field exists backend-side but the frontend
uses a URL-derived fallback or an inconsistent source. Implement all
three in one PR.

### 2.1 Developer / publisher pages slug-derive the display name

**File:** `frontend/app/developer/[slug]/page.tsx:14-33, 41-43`
**File:** `frontend/app/publisher/[slug]/page.tsx:14-33, 41-43`

Both `generateMetadata` and the page body title-case the URL slug:

```ts
const name = slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
```

That slug-derived string is then used as:
- the `<h1>` hero on the page
- the `<title>` element
- OpenGraph + Twitter card titles
- the breadcrumb label

The page has *already fetched* `getGames({ developer: slug, ... })` /
`getGames({ publisher: slug })`. Every returned `Game` row carries
the canonical `developer` (or `publisher`) string — that field is
never read. Edge cases that currently mangle:

| Slug            | Current render      | Canonical (from DB)  |
|-----------------|---------------------|----------------------|
| `4a-games`      | `4 A Games`         | `4A Games`           |
| `11-bit-studios`| `11 Bit Studios`    | `11 bit studios`     |
| `playism`       | `Playism`           | `PLAYISM`            |

**Change:**
1. In the page body, resolve canonical name from the first game:
   ```ts
   const canonical = games.find((g) => g.developer_slug === slug)?.developer;
   const name = canonical ?? slug.replace(/-/g, " ")...;
   ```
2. `generateMetadata` runs before the page body in Next.js, so hoist
   the same logic: issue an awaited `getGames({ developer: slug,
   limit: 1 })` inside `generateMetadata`, read the canonical
   developer, fall back to slug-derived title-case if no rows.
3. Publisher page mirrors the same change (read `publisher`,
   compare against `publisher_slug`).

**Alternative (larger, not in scope for this PR):** add
`/api/developers/{slug}` / `/api/publishers/{slug}` metadata
endpoints returning `{name, slug, game_count}`. Noted for the backlog.

**Don't touch:** genre / tag pages — they have their own `name`/`slug`
rows in `genres` / `tags` tables and are handled differently.
Verify but do not refactor in this PR.

### 2.2 Compare picker pills show `"App 12345"` on reload

**File:** `frontend/components/toolkit/compare/GamePicker.tsx:40-97`

`pillCache` is a module-level in-memory `Map<number, PillData>` that
only gets populated when the user clicks-to-add a game in the *current
session*. On page reload or when opening a shared `/compare?games=570,440`
link, the pill initializes to:

```ts
selectedAppids.map((id) => pillCache.get(id) ?? { appid: id, name: `App ${id}`, header_image: null })
```

The rehydrate effect then tries to match each appid via
`getGames({ q: String(id), limit: 5 })` — a full-text search using
the numeric appid as the query string. The explicit inline comment
acknowledges the workaround:

> We don't have a by-appid endpoint; try a broad search and match by
> appid. As a fallback, leave as "App {id}".

This breaks routinely: users share links, users reload, the keyword-
search-on-a-number rarely returns the expected row.

**Change (pick the smaller option):**
- **Option A (recommended, small):** reuse the now-enriched
  `/api/games/{appid}/report` endpoint. After the Part 1 fix, its
  `game_meta` returns `{name, slug, header_image, ...}` for any
  appid in the catalog. In the rehydrate effect, fetch in parallel
  per unknown appid (`Promise.allSettled(unknown.map(id =>
  getGameReport(id)))`), pull `name`/`header_image` out of the
  response's `game` field. Drop the `getGames({ q })` hack.
- **Option B (larger, not this PR):** add
  `GET /api/games/by-appid?ids=570,440` returning a
  minimal projection for multiple appids in one query. Cleaner
  long-term but adds a new endpoint + matview/repo plumbing; out of
  scope here.

Go with Option A in this PR. Keep the `pillCache` — it still
de-duplicates repeated effect runs.

### 2.3 Top-level `review_count` on the report response is dead + inconsistent

**File:** `src/lambda-functions/lambda_functions/api/handler.py:261-270`
**File:** `frontend/app/games/[appid]/[slug]/page.tsx:121-123`

After the Part 1 fix (1.1 + 1.3), the only field left on the
response envelope next to `status`, `report`, `game`, `temporal`
is a top-level `review_count` (only set in the `not_available`
branch). Its defined semantics are:

```python
review_count = (game.review_count_english or game.review_count)
```

— English-aligned with all-language fallback.

The frontend originally read this. Post-Part-1, the frontend now
reads `g.review_count_english` from `game_meta` instead (strict
English-aligned). So the top-level field is:
- dead (nothing consumes it);
- semantically different from what the page uses (fallback vs strict);
- asymmetric with the `available` branch (which has no top-level
  count).

**Change:**
1. Remove the top-level `review_count` key from the `not_available`
   return in `handler.py` (lines 266-270). The `game_meta` dict
   already carries both `review_count` (all-language) and
   `review_count_english` (strict English) post-Part-1.
2. Remove the now-unused field from the frontend type in
   `frontend/lib/api.ts:64` (`review_count?: number;` on the
   top-level response shape).
3. Delete lines 121-123 in `page.tsx` that read it.
4. Update any test in `tests/test_api.py` or
   `tests/smoke/test_game_endpoints.py` that asserts on the
   top-level `review_count` field.

**Don't add a new field** to compensate — `game_meta.review_count` +
`game_meta.review_count_english` give callers both numbers
explicitly, which is what we want.

---

## Verification

### 2.1
- Load `/developer/<some-slug>` for a developer whose canonical
  casing differs from the title-cased slug (Valve, Hello Games,
  4A Games, or find one via
  `SELECT developer, developer_slug FROM games WHERE developer !=
  INITCAP(REPLACE(developer_slug, '-', ' ')) LIMIT 5`).
- Verify the `<h1>` and `<title>` show the canonical casing.
- View source, confirm OpenGraph + Twitter + breadcrumb match.
- Repeat for `/publisher/<slug>`.
- Run the relevant Playwright smoke tests in `frontend/tests/`.

### 2.2
- Start the dev server, add Dota 2 + Team Fortress 2 to the compare
  pane, copy the URL from the address bar.
- Open the copied URL in a fresh incognito tab.
- Pills should render with the real game names + header images on
  first paint (or within one React effect tick), not `"App 570"`.
- Network tab: confirm two parallel `GET /api/games/<id>/report`
  calls, no `GET /api/games?q=570` calls.

### 2.3
- `curl -s http://localhost:3001/api/games/440/report | jq` for a game
  with no report (pick one from
  `SELECT appid FROM games WHERE last_analyzed IS NULL LIMIT 1`).
- Confirm the top-level JSON has exactly `status` + `game`; no
  top-level `review_count` key.
- Confirm `game.review_count` (all-language) and
  `game.review_count_english` (English) are both present.
- Load the corresponding game page; Steam Facts zone should still
  display the English-aligned count matching `positive_pct`.
- Run `poetry run python -m pytest tests/test_api.py -x -q` — 37
  tests pass after any assertion updates.

---

## Out of scope (separate PRs)

These surfaced in the audit but are deliberately not in this PR:

- **MEDIUM — `GameReport.store_page_alignment` silently null when
  `about_the_game` is NULL upstream.** Needs either a UI empty-state or
  an upstream crawl fix; pick the direction in a separate discussion.
- **MEDIUM — developer/publisher `totalReviews` summed with
  all-language counts on the frontend.** Same English-vs-all-language
  flavor as 2.3; either switch to `review_count_english` or move the
  reduce into the analytics endpoint.
- **SPECULATIVE — benchmarks query mixes sentiment percentile (English)
  with popularity percentile (all-language).** Needs product decision
  before any code change.
- **SPECULATIVE — analyzer's `total_reviews = len(reviews)` passed
  into the synthesis prompt.** Verify the reviews list is
  English-filtered upstream before deciding.

## Style notes for the implementing agent

- Match the codebase conventions from `CLAUDE.md` —
  `pydantic.BaseModel` everywhere, no dataclasses; no `| None`
  defaults where the value is always set; `*_crawled_at` columns for
  any externally-sourced timestamp; integration tests hit a real
  `steampulse_test` DB.
- Do not deploy. Do not `git add` / `git commit` / `git push` —
  leave that for the user.
- Keep the commit message single-line.
