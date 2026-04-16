# Split EA vs post-release review counts & sentiment on the read path

## Context

Steam's review summary API returns **all-time aggregate** counts (`total_positive`,
`total_negative`, `review_score_desc`) with **no server-side filter** that excludes Early
Access reviews after a game has launched. SteamPulse currently trusts that summary and
writes it straight to the `games` row (`review_count`, `review_count_english`,
`total_positive`, `total_negative`, `positive_pct`, `review_score_desc`), then surfaces
those numbers everywhere — cards, listings, detail pages, matviews.

For games that have transitioned **out of Early Access into full release**, this produces
a visible mismatch with Steam's store UI. Example: "Project Scrapper" has 9 EA-era
reviews and 0 post-release reviews; Steam's store UI defaults to post-release counts
("No user reviews yet") while SteamPulse shows "9 reviews".

The data needed to fix this already exists:

- `reviews.written_during_early_access` (boolean, per-review) — populated since migration
  `0003_add_review_language_and_votes.sql`. Every row from Steam's `appreviews` API
  includes this flag and our `_normalize_reviews` preserves it
  (`src/library-layer/library_layer/services/crawl_service.py:76`).
- `games.has_early_access_reviews` — denormalized latch added in migration
  `0046_denormalize_has_ea_reviews.sql`.
- `ReviewRepository.find_early_access_impact()`
  (`src/library-layer/library_layer/repositories/review_repo.py:257-346`) already
  aggregates reviews split by `written_during_early_access` for the
  `/api/games/{appid}/early-access-impact` endpoint.

What's missing is denormalizing **post-release counts + sentiment** onto the `games` row
so the matview/read path can use them without scanning `reviews` at query time (CLAUDE.md
"Read path: UI is fed by materialized views + pre-computed data — mandatory").

## Confirmed scope

1. **Primary count for post-EA games = post-release only** (Steam-consistent).
2. **Reach**: detail page + cards/listings (matview-backed feeds included).
3. **Sentiment split**: compute post-release `positive_pct` and `review_score_desc`
   locally — not just counts.

## Language scope — English-only (matches existing convention)

All crawled reviews in our `reviews` table are English: `SteamDataSource.get_reviews()`
passes `language="english"` to Steam (`src/library-layer/library_layer/steam_source.py:281, 307`).
We never store non-English rows.

This is already the operating convention for every sentiment field on `games`:

- `review_count` — all-languages (Steam's `total_reviews_all` summary call)
- `review_count_english` — English (Steam's English summary call)
- `total_positive`, `total_negative`, `positive_pct`, `review_score_desc` — **implicitly
  English** (from the English summary call, `get_review_summary` at
  `steam_source.py:358-366`)

Therefore **the new post-release columns are implicitly English too**. They are derived
from SQL aggregates over `reviews` (English-only by construction) filtered on
`written_during_early_access=FALSE`, and they sit alongside the existing English-implicit
columns. No "all languages" post-release variant is feasible — we'd have to start
crawling non-English reviews to produce one, and that's out of scope. A comment in the
migration and in `models/game.py` will state this explicitly so future contributors don't
mistake them for all-language counts.

Accuracy caveat: for games at the review-crawl cap (`REVIEW_LIMIT=10000`) the derived
post-release count can lag Steam's English total. For EA-transition games — the ones
this spec exists to fix — review counts are almost always well under the cap, so this is
acceptable.

## Approach

Denormalize four new columns onto `games`, populated at review-ingest time (same pattern
as `positive_pct` and `has_early_access_reviews`). Read path continues to read from
`games` / matviews only — no live aggregate against `reviews`.

### 1. New denormalized columns on `games`

Migration `src/lambda-functions/migrations/00NN_add_post_release_review_metrics.sql`:

```sql
-- depends: <latest migration>

-- All four columns are English-only, mirroring the existing implicit-English
-- convention on positive_pct / total_positive / review_score_desc.
ALTER TABLE games ADD COLUMN IF NOT EXISTS review_count_post_release     INTEGER;
ALTER TABLE games ADD COLUMN IF NOT EXISTS positive_count_post_release   INTEGER;
ALTER TABLE games ADD COLUMN IF NOT EXISTS positive_pct_post_release     INTEGER;
ALTER TABLE games ADD COLUMN IF NOT EXISTS review_score_desc_post_release TEXT;
```

Naming follows the existing pattern: `review_count_english` is the only field that
spells "english" explicitly; `positive_pct` / `review_score_desc` / `total_positive` /
`total_negative` are already English-implicit. We keep that convention — these new
fields are English-only because every row in `reviews` is English-only.

Nullable on purpose: NULL means "no split computed yet" (code falls back to Steam's
all-time values). Values are ints/pct/label — all derived from our **local English**
`reviews` rows. For EA-transition games the derived counts line up with Steam's English
summary count (`review_count_english`); for games at the review-crawl cap they can lag,
which is acceptable.

No EA-specific columns added. EA presence is already covered by
`has_early_access_reviews`; an exact EA-era count can be derived from
`find_early_access_impact()` when the detail page needs it.

Update `src/library-layer/library_layer/schema.py` `CREATE TABLE games` block to mirror.

### 2. Compute the values on review ingest

- **Add** `ReviewRepository.aggregate_post_release(appid) -> (count, positive_count)`
  — pure SQL `COUNT(*) / COUNT(CASE WHEN voted_up)` filtered by
  `written_during_early_access = FALSE`. No `language` predicate needed — the
  `reviews` table is English-only by construction.
- **Add** a Steam-compatible score-label formula in
  `src/library-layer/library_layer/utils/scores.py` (file already exists):
  `steam_review_label(positive_pct: int | None, total: int) -> str | None`. Use
  Steam's published breakpoints ("Overwhelmingly Positive" ≥95% & ≥500 reviews,
  "Very Positive" ≥80% & ≥50, "Mostly Positive" ≥80% & <50, "Positive" ≥80% & <10, etc.).
  Returns `None` when `total == 0` so the frontend can render "No post-release reviews".
- **Add** `GameRepository.update_post_release_metrics(appid, count, positive, pct, desc)`.
- **Wire** into the review-ingest path: in
  `CrawlService.ingest_spoke_reviews` (`crawl_service.py:262-280`), after the upsert,
  call the aggregate + update. Same place that currently sets
  `has_early_access_reviews`. Do it inside each review-batch ingest — idempotent.
- Do **not** also wire this to `crawl_app` (that path writes summary counts from the
  Steam summary API, not from our review rows; the reviews-ingest path is the right
  single home).

### 3. Backfill

Second migration section (or a follow-up migration) that runs a single bulk UPDATE
against the existing `reviews` table to populate the four new columns for all games
with any reviews. Guarded by `WHERE review_count_post_release IS NULL`. Score label
computed in SQL via `CASE` or left NULL and backfilled by a one-shot admin invoke that
calls `update_post_release_metrics` for each affected appid (simpler — reuses the
Python label formula).

### 4. Matviews

Update in a migration (drop-and-rebuild per CLAUDE.md matview rules):

- `mv_discovery_feeds` (migration 0047) — add `review_count_post_release` and
  `positive_pct_post_release` to its projection so home/listing components can use
  them. Keep `review_count` / `positive_pct` columns for backwards compat.
- `mv_trend_catalog`, `mv_trend_by_genre`, `mv_trend_by_tag` (migrations 0045/0046) —
  same addition; these drive trend listings.

Each rebuild:
- `DROP MATERIALIZED VIEW IF EXISTS …;` before `CREATE`.
- Preserve existing unique index (mandatory for `REFRESH CONCURRENTLY`).
- Update `schema.py::MATERIALIZED_VIEWS` and the drop-before-rebuild list in
  `create_matviews()`.
- Matview refresh path (`MATVIEW_NAMES` in `matview_repo.py`) needs no change — they
  pick up the new projection automatically.

### 5. API surface

- Extend `Game` model (`src/library-layer/library_layer/models/game.py`) with the four
  new fields as `int | None` / `str | None`.
- Update `GameRepository.find_by_appid` / list selects to include them.
- Extend response shapes in `src/lambda-functions/lambda_functions/api/handler.py`:
  - `/api/games/{appid}/report` → include post-release fields on `game_meta`.
  - `/api/games` list endpoint → include when present.
  - Matview-backed discovery/trend endpoints → expose post-release columns.
- Smoke test updates (`tests/smoke/test_game_endpoints.py`,
  `test_catalog_endpoints.py`) — assert presence of new keys. Per CLAUDE.md:
  "any API change must update the smoke tests in the same PR."

### 6. Frontend

- `frontend/lib/types.ts` — add the four fields to the `Game` type (all `number | null`
  / `string | null`).
- **Display helper** (small utility in `frontend/lib/utils.ts` or
  `frontend/components/game/review-display.ts`):
  ```ts
  export function displayedReviewCount(game: Game): {
    count: number | null;
    label: string | null;
    phase: "post_release" | "early_access" | "all_time";
  }
  ```
  Rules:
  - If `has_early_access_reviews && !coming_soon && review_count_post_release != null`
    → post-release.
  - If `coming_soon || (has_early_access_reviews && review_count_post_release === 0)`
    → early-access (show EA-era count via `review_count`, label "Early Access reviews").
  - Else → all-time (current behavior).
- `frontend/components/game/GameCard.tsx` (lines 72-77) — use the helper instead of
  `review_count_english ?? review_count`. When phase === "post_release" and
  `has_early_access_reviews`, add a small "ex-EA" chip or subtitle.
- Game detail page (`frontend/app/games/[appid]/[slug]/page.tsx`) — same helper in the
  header/hero. `EarlyAccessImpact` component already renders the breakdown; no change
  needed there.
- Update mock data + api-mock fixtures (`frontend/tests/fixtures/mock-data.ts`,
  `fixtures/api-mock.ts`) for the new fields.
- Update / add Playwright tests for a post-EA game showing a post-release headline.

### 7. Tests

- `tests/repositories/test_review_repo.py` — new test for `aggregate_post_release`
  with a mix of EA and non-EA reviews on `steampulse_test` DB.
- `tests/repositories/test_game_repo.py` — test `update_post_release_metrics`.
- `tests/services/test_crawl_service.py` — verify `ingest_spoke_reviews` updates the
  new columns + calls the label formula.
- `tests/utils/test_scores.py` (new or extend existing) — table-driven tests for
  `steam_review_label` against Steam's published breakpoints.
- `tests/repositories/test_matview_repo.py` — assert the new matview columns are
  exposed.
- Frontend: `frontend/tests/game-report.spec.ts` — post-EA assertion.

### 8. Deployment order (backwards-compat)

1. Migration adds new nullable columns + matview rebuild (columns NULL, matviews expose
   them as NULL projection).
2. Code deploy: review-ingest path populates the columns; API returns them (callers
   tolerate NULL).
3. Frontend deploy: helper uses post-release when non-NULL, falls back to current
   behavior when NULL.
4. One-shot admin backfill invoke to populate for all existing games.

Each step is safely deployable without the next.

## Out of scope (intentionally)

- **LLM analyzer changes.** Three-phase analysis continues to process all reviews.
  Splitting EA vs post-release **narrative** signals is a larger re-architecture;
  track as a follow-up.
- **Reconciling Steam's reported `review_count` with our local sum.** Differences
  arise at the review-crawl cap (REVIEW_LIMIT=10000) and are tolerable for this
  change.
- **Changing `positive_pct` / `review_score_desc` semantics for non-EA games.** The
  existing fields continue to mirror Steam's all-time values. New columns are
  *additional*, not replacements.

## Critical files

- Migrations: `src/lambda-functions/migrations/00NN_add_post_release_review_metrics.sql`
  (+ matview rebuild migration)
- `src/library-layer/library_layer/schema.py` — games block + matview DDL
- `src/library-layer/library_layer/repositories/review_repo.py` — add `aggregate_post_release`
- `src/library-layer/library_layer/repositories/game_repo.py` — add updater
- `src/library-layer/library_layer/services/crawl_service.py` — hook into `ingest_spoke_reviews`
- `src/library-layer/library_layer/utils/scores.py` — `steam_review_label`
- `src/library-layer/library_layer/models/game.py` — new fields
- `src/lambda-functions/lambda_functions/api/handler.py` — API surface
- `frontend/lib/types.ts`, `frontend/components/game/GameCard.tsx`,
  `frontend/app/games/[appid]/[slug]/page.tsx`
- Tests as listed in section 7

## Verification

- `poetry run pytest tests/repositories/test_review_repo.py tests/services/test_crawl_service.py tests/utils/test_scores.py -v`
- `poetry run pytest tests/smoke/ --prod -v` after production deploy; expect the new
  fields to appear on `/api/games/{appid}/report`.
- Spot check Project Scrapper (or a similar post-EA game with low post-release count)
  on `steampulse.io` — the card should show the post-release count (0) with an
  EA-history indicator, and the detail page headline should reflect the same.
- `frontend && npm run test:e2e` — new assertion for post-EA hero count.
- Matview shape: `\d mv_discovery_feeds` in psql after migration shows the new
  columns; `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_discovery_feeds` succeeds (proves
  unique index is preserved).
