# Plan: DB performance optimizations, round 1 (queries & round-trips)

## Context

Prod Postgres is on `db.t4g.small` (2 vCPU / 2 GB RAM, gp3 100 GB at 3000 IOPS / 125 MB/s default). During crawl refresh windows the instance pegs — CPUCreditBalance sits at 0 for hours, DBLoad exceeds 18 AAS on a 2-vCPU box, DiskQueueDepth averages 30+, ReadLatency hits 84 ms, and `spoke-results-production` backs up with successful crawl results that fail to ingest before the SQS visibility timeout expires and land in the DLQ.

Root cause is **I/O + memory pressure, not CPU saturation** — 2 GB RAM can't hold the hot working set (`reviews` table + its GIN/trigram index from migration 0051), so inserts and point-lookups miss the buffer cache and go to disk. Stepping up the instance (`db.m6g.large` with 8 GB RAM) is the real structural fix, but before committing to that we can materially reduce the load by removing silly queries and collapsing N+1 patterns in the hot ingest paths.

Performance Insights top 25 SQL (24h window, captured 2026-04-21) showed three categories of wasted work:

1. **Observability queries** that exist only to populate log fields — the biggest was `SELECT COUNT(*) AS cnt FROM reviews WHERE appid = ?` at 0.65 AAS, already removed in a previous commit. The TUI admin dashboard is the other offender.
2. **N+1 upsert loops** in metadata ingest — `TagRepository.upsert_genres` and `upsert_categories` issue one `INSERT ... ON CONFLICT` per genre/category per game.
3. **Wide SELECTs** that pull TOAST-heavy text columns just to diff a handful of fields for event detection.

A prior commit already removed `SELECT COUNT(*) FROM reviews WHERE appid = ?` from `ingest_handler.py` (the #1 offender). This prompt covers the remaining Tier 1 / Tier 2 items.

---

## Goal

Reduce DB round-trips and bytes-on-the-wire in the three hot ingest paths (metadata, tags, reviews) and the admin TUI, so that when crawl schedules are re-enabled the `t4g.small` can sustain the workload without credit exhaustion. This is a pure code-quality pass — same behavior, fewer queries, no schema changes.

Each change must be independently testable and shippable. Keep changes minimal — no speculative refactors.

---

## Tier 1 — ship together

### T1-A. TUI dashboard: replace full-table `COUNT(*)` with `pg_class.reltuples`

**Evidence:** `scripts/tui/queries.py:7-10` runs four full-table COUNTs every dashboard refresh. PI shows this at **0.50 AAS** — 25% of one vCPU when the TUI is open.

**Files:**
- `scripts/tui/queries.py:7-10` (`DASHBOARD_TOTALS`)
- `scripts/tui/queries.py:146` (correlated subquery `(SELECT COUNT(*) FROM reviews rv WHERE rv.appid = g.appid) AS reviews_in_db`)

**Change:**

1. For `DASHBOARD_TOTALS`, switch to `pg_class.reltuples` estimates. Pattern already used at `src/lambda-functions/lambda_functions/api/handler.py:748` (comment there confirms: "`total_games` is a pg_class.reltuples estimate, not a COUNT(*) — instant"). Example:

   ```sql
   SELECT
     COALESCE((SELECT reltuples::bigint FROM pg_class WHERE relname = 'games'),       0) AS games,
     COALESCE((SELECT reltuples::bigint FROM pg_class WHERE relname = 'reviews'),     0) AS reviews,
     COALESCE((SELECT reltuples::bigint FROM pg_class WHERE relname = 'reports'),     0) AS reports,
     COALESCE((SELECT reltuples::bigint FROM pg_class WHERE relname = 'app_catalog'), 0) AS catalog
   ```

2. For the per-game `reviews_in_db` column at line 146, replace the correlated subquery with `g.review_count` (already denormalized on the games table). If that column is unreliable, use `mv_review_counts.count` via a LEFT JOIN — the matview already exists and PI shows it refreshing on schedule.

**Caveat:** `reltuples` is an *estimate* maintained by autovacuum/ANALYZE — it can drift a few percent from the true count. For operator dashboard totals this is fine; the previous COUNT(*) values were also stale the moment they rendered.

**Expected impact:** -0.50 AAS baseline when TUI is open. Dashboard refresh becomes sub-millisecond instead of multi-second.

---

### T1-B. `upsert_genres`: collapse N+1 INSERTs into 2 `execute_values`

**File:** `src/library-layer/library_layer/repositories/tag_repo.py:119-158`

**Current:** The method runs one `INSERT INTO genres ... ON CONFLICT` and one `INSERT INTO game_genres ... ON CONFLICT DO NOTHING` inside a per-genre `for` loop. A typical Steam game has 2–4 genres, so this is 4–8 round-trips per metadata ingest, plus the leading DELETE.

**Change:**

1. Build `genre_rows: list[tuple[int, str, str]]` of `(genre_id, genre_name, genre_slug)` from the incoming `genres` list, filtering out invalid rows (same logic as current inline filter).
2. Replace the per-genre `cur.execute(...)` for `genres` with one `psycopg2.extras.execute_values` call using `ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, slug = EXCLUDED.slug`.
3. Replace the per-genre `cur.execute(...)` for `game_genres` with one `execute_values` call using `ON CONFLICT (appid, genre_id) DO NOTHING`.
4. Leave the DELETE logic at the top untouched.

Keep the method signature identical — tests should not need updating beyond any assertions that counted `cur.execute` calls (if any exist).

**Expected impact:** 4–8× fewer round-trips per metadata ingest. Runs 486+ times/hr when metadata refresh is enabled.

---

### T1-C. `upsert_categories`: collapse N+1 INSERTs into 1 `execute_values`

**File:** `src/library-layer/library_layer/repositories/tag_repo.py:160-193`

**Current:** Same shape as `upsert_genres` — one `INSERT INTO game_categories ... ON CONFLICT DO UPDATE` per category in a loop. A typical Steam game has 5–15 categories (Single-player, Multi-player, Achievements, Cloud Saves, Controller Support, etc.) → 5–15 round-trips.

**Change:** Replace the per-category `cur.execute(...)` with a single `execute_values` using `ON CONFLICT (appid, category_id) DO UPDATE SET category_name = EXCLUDED.category_name`. Preserve the leading DELETE.

**Expected impact:** 5–15× fewer round-trips per metadata ingest.

---

### T1-D. `ingest_spoke_metadata`: narrow the pre-upsert SELECT

**Files:**
- `src/library-layer/library_layer/services/crawl_service.py:262` (callsite)
- `src/library-layer/library_layer/repositories/game_repo.py:135` (`find_by_appid`)

**Current:** `ingest_spoke_metadata` calls `self._game_repo.find_by_appid(appid)` to get the "before" state for event detection (`coming_soon` flip, price change, review milestone crossings). `find_by_appid` uses `_GAME_SELECT_WITH_FRESHNESS` which returns `g.*` plus four columns from `app_catalog` via LEFT JOIN — ~30 columns including the TOAST-heavy `detailed_description` (often 10 KB+) and `about_the_game`. PI shows this at 0.006 AAS, but it runs on every metadata ingest (486+ /hr at full tilt).

**Change:**

1. Add a new narrow method to `GameRepository`:
   ```python
   def find_event_snapshot(self, appid: int) -> dict | None:
       """Minimal pre-upsert snapshot for event detection. Returns None if game doesn't exist."""
       row = self._fetchone(
           "SELECT coming_soon, price_usd, review_count, has_early_access_reviews "
           "FROM games WHERE appid = %s",
           (appid,),
       )
       return dict(row) if row else None
   ```
2. In `crawl_service.py`, change `ingest_spoke_metadata` to call `self._game_repo.find_event_snapshot(appid)` and pass the dict (or None) into `_publish_crawl_app_events`.
3. Update `_publish_crawl_app_events` to accept `existing: dict | None` (not `object | None`) and use dict indexing. This is localized to that one function.
4. **Leave `find_by_appid` untouched** — it's used by API handlers that do need the full row.
5. **Do not** change `crawl_app()` in `crawl_service.py:124` — it's the direct-invoke path and already pulls `find_by_appid` once; that's fine.

**Expected impact:** Eliminates TOAST detoast on every metadata refresh. Row payload drops ~100× (4 scalar columns vs. ~30 columns + large TEXT fields).

---

## Tier 2 — ship when Tier 1 is in

### T2-A. Merge `mark_reviews_complete` + `mark_reviews_crawled` into one UPDATE

**Files:**
- `src/library-layer/library_layer/repositories/catalog_repo.py:231-273`
- `src/lambda-functions/lambda_functions/crawler/ingest_handler.py` (three callsite pairs in `_handle_reviews`)

**Current:** In the three review-termination branches (`exhausted`, `early_stop`, `target_hit`) the handler calls two separate repo methods, each doing an `UPDATE app_catalog SET … WHERE appid = %s` + its own `commit()`.

**Change:**

1. Add `CatalogRepository.mark_reviews_complete_and_crawled(appid: int, completed_at: datetime | None = None) -> None` that performs one UPDATE setting both `reviews_completed_at = GREATEST(...)` and `review_crawled_at = NOW()`.
2. Replace the pairs in `ingest_handler.py` with single calls (3 sites).
3. Keep the existing `mark_reviews_complete` and `mark_reviews_crawled` single-column methods — they're used by tests and possibly scripts.

**Expected impact:** Halves UPDATEs + commits on every review-termination message. Small individual win but persistent.

---

## Out of scope (explicitly deferred)

These showed up in the investigation but are deferred — do **not** bundle into this prompt:

- **Commit-per-batch refactor** in ingest handler. Bigger change touching `BaseRepository`; revisit after Tier 1+2 lands and we can measure.
- **`set_has_early_access_reviews` unconditional call** at `crawl_service.py:287-288`. Already idempotent via WHERE clause — no write happens when already TRUE. Leave alone.
- **Autovacuum tuning on reviews.** Postgres parameter change, not code. Track separately.
- **`upsert_tags` 5-round-trip pattern.** Could fold the two SELECTs into the INSERT via RETURNING, but the two `= ANY(...)` lookups are cheap compared to the genres/categories N+1 loops. Not worth touching yet.

---

## Testing

For each change:

1. Run the relevant test file(s):
   - T1-A: `poetry run pytest tests/` for any TUI-related tests (may be none; this is operator-only code).
   - T1-B / T1-C: `poetry run pytest tests/repositories/test_tag_repo.py` (and any service-level tests that exercise metadata ingest).
   - T1-D: `poetry run pytest tests/services/test_crawl_service.py tests/handlers/test_ingest_handler.py tests/repositories/test_game_repo.py`.
   - T2-A: `poetry run pytest tests/handlers/test_ingest_handler.py tests/repositories/test_catalog_repo.py`.
2. Tests must use the `steampulse_test` DB per the repo convention, not the live dev DB.
3. If any test mocks the now-unused method variant, leave the mock in place — harmless.

## Verification (post-deploy)

1. Re-enable the disabled EventBridge schedules.
2. Watch CloudWatch / Performance Insights for a 24h window:
   - `SELECT COUNT(*) AS cnt FROM reviews WHERE appid = ?` should be gone (already shipped).
   - `SELECT (SELECT COUNT(*) FROM games), …` should drop out of top-25.
   - Per-game `INSERT INTO genres/game_genres/game_categories` should no longer appear as repeated point-inserts.
   - Wide `SELECT g.*, ac.meta_crawled_at, …` against `games` should drop materially.
3. Track `DBLoad`, `DiskQueueDepth`, `ReadLatency`, `WriteLatency`, `CPUCreditBalance` for before/after comparison. Success = credit balance no longer floors at 0 under steady refresh load.
4. Watch `spoke-results-production` queue depth and DLQ arrival rate — steady drain instead of backlog growth.

## Execution order

1. **T1-A (TUI dashboard)** — operator script only, no Lambda redeploy. Fastest win, lowest risk.
2. **T1-B + T1-C (genres/categories N+1)** — single-file changes in `tag_repo.py`. Ship as one commit; they share shape.
3. **T1-D (narrow event-snapshot SELECT)** — new repo method + one callsite + one function signature tweak.
4. **T2-A (merge two UPDATEs)** — quick follow-up once already in `catalog_repo.py` and `ingest_handler.py`.

Land 1-4 before considering the deferred items or the instance-size step-up.
