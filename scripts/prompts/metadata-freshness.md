# Fix Metadata Freshness: Stale Associations + Re-crawl Scheduling

## Problem

Two interrelated bugs prevent game metadata from staying current:

### Bug 1: Stale genre/category/tag associations

`upsert_genres()`, `upsert_categories()`, and `upsert_tags()` in `tag_repo.py` use
`INSERT ... ON CONFLICT DO NOTHING` — they only add associations, never remove ones that
Steam has dropped. When a game leaves Early Access, Steam removes genre 70 from its API
response, but our DB keeps the stale association forever.

**Verified:** Steam's `appdetails` API correctly removes genre 70 when games leave EA
(confirmed with Hades appid=1145360, BG3 appid=1086940). Games still in EA keep genre 70
(confirmed with Valheim appid=892970). Our DB would never reflect the removal.

Same problem affects all genres, categories, and player tags — any removal on Steam's
side is invisible to us.

### Bug 2: No metadata re-crawl scheduling

Games are only crawled when `meta_status = 'pending'` in `app_catalog`. Once set to
`'done'`, metadata is permanent. There's no mechanism to refresh genres, categories,
price, release date, or any other metadata for existing games.

The `meta_crawled_at` timestamp exists (migration 0012) but nothing checks it for
staleness or re-queues games.

---

## Current State

**`tag_repo.py` (lines 90-142):**
```python
def upsert_genres(self, appid, genres):
    for genre in genres:
        cur.execute("INSERT INTO genres ... ON CONFLICT (id) DO UPDATE SET ...")
        cur.execute("INSERT INTO game_genres ... ON CONFLICT (appid, genre_id) DO NOTHING")  # ← BUG

def upsert_categories(self, appid, categories):
    cur.execute("INSERT INTO game_categories ... ON CONFLICT (appid, category_id) DO UPDATE SET ...")  # ← only updates name, never deletes
```

**`catalog_repo.py`:** `find_pending_meta()` only returns `meta_status = 'pending'`.

**`catalog_service.py`:** `enqueue_pending()` calls `find_pending_meta()` — no stale check.

**`app_catalog` table:** Has `meta_crawled_at`, `tags_crawled_at`, `review_crawled_at`
columns but no code uses them for re-crawl scheduling.

**Crawl pipeline:** SQS `app-crawl-queue` → spoke handler → Steam API → S3 → ingest handler
→ `CrawlService._ingest_app_data()` → `tag_repo.upsert_genres()`. The pipeline already
handles re-crawls — the data just flows through the same path. Only the trigger is missing.

---

## What to Build

### Part 1: Fix Delete-and-Replace for Associations

#### 1a. Fix `upsert_genres()` in `tag_repo.py`

Before the insert loop, delete genre associations for this appid that are NOT in the
incoming set:

```python
def upsert_genres(self, appid: int, genres: list[dict]) -> None:
    with self.conn.cursor() as cur:
        # Delete genres no longer present on Steam
        valid_genre_ids = [int(g.get("id") or 0) for g in genres if int(g.get("id") or 0)]
        if valid_genre_ids:
            cur.execute(
                "DELETE FROM game_genres WHERE appid = %s AND genre_id != ALL(%s)",
                (appid, valid_genre_ids),
            )
        else:
            cur.execute("DELETE FROM game_genres WHERE appid = %s", (appid,))

        # Then insert/update as before
        for genre in genres:
            ...
    self.conn.commit()
```

#### 1b. Fix `upsert_categories()` in `tag_repo.py`

Same pattern:

```python
valid_cat_ids = [int(c.get("id") or 0) for c in categories if int(c.get("id") or 0)]
if valid_cat_ids:
    cur.execute(
        "DELETE FROM game_categories WHERE appid = %s AND category_id != ALL(%s)",
        (appid, valid_cat_ids),
    )
else:
    cur.execute("DELETE FROM game_categories WHERE appid = %s", (appid,))
```

#### 1c. Fix `upsert_tags()` in `tag_repo.py`

Tags are bulk (multiple appids per call). After the bulk `execute_values` for `game_tags`,
clean up stale tag associations per appid:

```python
from collections import defaultdict
appid_tag_ids: dict[int, list[int]] = defaultdict(list)
for aid, tid, _ in game_tag_rows:
    appid_tag_ids[aid].append(tid)

for aid, tids in appid_tag_ids.items():
    cur.execute(
        "DELETE FROM game_tags WHERE appid = %s AND tag_id != ALL(%s)",
        (aid, tids),
    )
```

### Part 2: Metadata Re-crawl Scheduling

#### 2a. New query: `CatalogRepository.find_stale_meta()`

**File:** `src/library-layer/library_layer/repositories/catalog_repo.py`

Priority-tiered staleness query:

| Tier | Criteria | Re-crawl after |
|------|----------|----------------|
| 1 | `coming_soon = TRUE` or has genre 70 (Early Access) | 7 days |
| 2 | `review_count >= 1000` (popular games) | 14 days |
| 3 | Everything else with `meta_status = 'done'` | 30 days |

```sql
SELECT ac.* FROM app_catalog ac
LEFT JOIN games g ON g.appid = ac.appid
LEFT JOIN game_genres gg ON gg.appid = ac.appid AND gg.genre_id = 70
WHERE ac.meta_status = 'done'
  AND (
    -- Tier 1: EA / coming soon, stale > 7 days
    ((g.coming_soon = TRUE OR gg.genre_id IS NOT NULL)
      AND ac.meta_crawled_at < NOW() - INTERVAL '7 days')
    OR
    -- Tier 2: popular games, stale > 14 days
    (ac.review_count >= 1000
      AND ac.meta_crawled_at < NOW() - INTERVAL '14 days')
    OR
    -- Tier 3: everything else, stale > 30 days
    (ac.meta_crawled_at < NOW() - INTERVAL '30 days')
  )
ORDER BY
  CASE
    WHEN g.coming_soon = TRUE OR gg.genre_id IS NOT NULL THEN 0
    WHEN ac.review_count >= 1000 THEN 1
    ELSE 2
  END,
  ac.meta_crawled_at ASC NULLS FIRST
LIMIT %s
```

Default limit: 2,000 games per run. At ~3,500 crawls/hour throughput, this completes
in under an hour. Full catalog refresh (~160k) takes ~80 days for the long tail.

`NULLS FIRST` ensures legacy games (pre-migration 0012, no `meta_crawled_at` value)
get refreshed first.

#### 2b. New method: `CatalogService.enqueue_stale()`

**File:** `src/library-layer/library_layer/services/catalog_service.py`

```python
def enqueue_stale(self, limit: int = 2000) -> int:
    """Find games with stale metadata and enqueue for re-crawl."""
    stale = self._catalog_repo.find_stale_meta(limit=limit)
    if not stale:
        logger.info("No stale games to re-crawl")
        return 0
    messages = [{"appid": e.appid, "task": "metadata"} for e in stale]
    send_sqs_batch(self._sqs, self._app_crawl_queue_url, messages)
    logger.info("Stale metadata enqueued", extra={"count": len(messages)})
    return len(messages)
```

Uses the same `app-crawl-queue` and `task: "metadata"` as initial crawls. The existing
ingest pipeline handles re-crawls identically — with the Part 1 fix, associations are
properly replaced.

#### 2c. Wire into crawler handler

**File:** `src/lambda-functions/lambda_functions/crawler/events.py`

Add new request model:
```python
class StaleRefreshRequest(BaseModel):
    action: Literal["stale_refresh"] = "stale_refresh"
    limit: int = 2000
```

**File:** `src/lambda-functions/lambda_functions/crawler/handler.py`

Add dispatch branch. The handler already checks `"action" in event` for direct
invocations — add the `stale_refresh` case alongside `catalog_refresh`:

```python
case StaleRefreshRequest():
    count = _catalog_service.enqueue_stale(limit=req.limit)
    return {"stale_enqueued": count}
```

#### 2d. EventBridge rule (daily)

**File:** `infra/stacks/compute_stack.py`

Add a second EventBridge rule on the crawler Lambda:

```python
stale_refresh_rule = events.Rule(
    self, "StaleMetaRefreshRule",
    schedule=events.Schedule.rate(cdk.Duration.days(1)),
    enabled=True,
)
stale_refresh_rule.add_target(
    events_targets.LambdaFunction(
        crawler_fn,
        event=events.RuleTargetInput.from_object({"action": "stale_refresh"}),
    ),
)
```

`RuleTargetInput.from_object` replaces the entire event payload with the custom
object, so the handler's `"action" in event` branch catches it.

#### 2e. CLI support in `sp.py`

Add command:
```bash
poetry run python scripts/sp.py queue stale [--limit N]
```

Invokes the crawler Lambda with `{"action": "stale_refresh", "limit": N}` or calls
`CatalogService.enqueue_stale()` locally.

### Part 3: Migration — Partial Index

**File:** `src/lambda-functions/migrations/0014_add_stale_meta_index.sql`

```sql
-- depends: 0013_add_steam_tag_id
-- transactional: false

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_catalog_stale_meta
    ON app_catalog (meta_crawled_at)
    WHERE meta_status = 'done';
```

Partial index — only `done` rows. Makes the staleness query efficient on 160k+ rows.
`CONCURRENTLY` avoids write-blocking. `transactional: false` required for CONCURRENTLY.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `src/library-layer/library_layer/repositories/tag_repo.py` | Fix delete-and-replace for genres, categories, tags |
| `src/library-layer/library_layer/repositories/catalog_repo.py` | Add `find_stale_meta()` |
| `src/library-layer/library_layer/services/catalog_service.py` | Add `enqueue_stale()` |
| `src/lambda-functions/lambda_functions/crawler/events.py` | Add `StaleRefreshRequest` model |
| `src/lambda-functions/lambda_functions/crawler/handler.py` | Add `stale_refresh` dispatch |
| `infra/stacks/compute_stack.py` | Add daily EventBridge rule |
| `scripts/sp.py` | Add `queue stale` command |
| `src/lambda-functions/migrations/0014_add_stale_meta_index.sql` | Create partial index |
| `src/library-layer/library_layer/schema.py` | Add ALTER TABLE stub + index for test suite |

## Testing

- **Association replacement:**
  - Upsert genres `[A, B]` for appid, then upsert `[B, C]` → verify A removed, B+C present
  - Upsert categories `[X, Y]`, then upsert `[]` → verify all removed
  - Upsert tags for appid, then upsert smaller set → verify removed tags gone

- **Stale query:**
  - Insert games with various `meta_crawled_at` values → verify priority ordering
  - Verify `LIMIT` respected
  - Verify `NULLS FIRST` handles legacy rows

- **End-to-end:**
  - `poetry run pytest -v` passes
  - `poetry run ruff check . && poetry run ruff format .` clean
  - Deploy, invoke `{"action": "stale_refresh", "limit": 10}` → verify 10 games re-crawled
  - After re-crawl, verify genre associations reflect current Steam data

## Constraints

- No new tables — uses existing columns and tables
- Backwards-compatible migration (index only, no schema changes)
- Same SQS queue and spoke pipeline — no new infrastructure beyond the EventBridge rule
- `upsert_tags` cleanup must handle the bulk (multi-appid) case correctly
- First run will have most games eligible — LIMIT prevents queue flooding

## Notes

- **First run catch-up:** On first stale refresh, most of the 160k+ games will qualify.
  At 2,000/day it takes ~80 days to cycle through. For an initial catch-up, run
  `sp.py queue stale --limit 10000` manually a few times.
- **Tag freshness:** Tags (from Steam store page) could also go stale. Consider adding
  `tags_crawled_at` to the staleness query in a follow-up. For now, metadata (genres,
  categories, price, release date) is the priority.
- **Review re-crawl:** Already handled by the review crawl pipeline with cursor-based
  continuation. Not in scope here.
