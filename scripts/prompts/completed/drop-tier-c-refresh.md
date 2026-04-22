# Reduce RDS write-IOPS from the tiered refresh dispatcher

## Context

The small RDS instance is write-IOPS saturated. The tiered refresh system (commit `f13c8a0`, hourly dispatchers in production) runs steady-state at ~1,374 ingest events/hr:

- **~972/hr metadata + tags** (486 appids × 2 messages — `catalog_service.py:167-168` fans out `task=metadata` and `task=tags` per appid).
- **~402/hr reviews** (tier S/A/B only — C excluded here already).

Current schedule:

```
S (review_count >= 10,000):    reviews 1d   meta 2d    tags 2d
A (coming_soon|EA|rc>=1,000):  reviews 3d   meta 7d    tags 7d
B (review_count >= 50):        reviews 14d  meta 21d   tags 21d
C (long tail):                 reviews --   meta 90d   tags 90d   <-- kill this
```

Tier C contains the entire Steam long-tail catalog (tens of thousands of games whose metadata and tag votes drift slowly if at all) and contributes the bulk of hourly ingest writes. Dropping Tier C refresh entirely is the chosen lever.

Separately, `tag_repo.upsert_tags` (`tag_repo.py:108-116`) issues one DELETE per appid in a Python loop on every tag ingest. In today's ingest flow (`ingest_handler.py` calls `upsert_tags` per-appid) that's effectively 1 DELETE per call, but the loop scales poorly the moment we batch multiple appids per call. Collapsing it into a single set-based DELETE is worth doing alongside the Tier C cut — it cuts SQL round-trips and per-statement overhead when batching, and simplifies the code now.

**Out of scope:** raising review cadence, changing S/A/B meta cadence, dispatcher cron frequency, spoke `max_concurrency`. If Tier C drop + tag-DELETE fix isn't enough, those are next-level levers to revisit.

---

## Change 1 — Drop Tier C meta+tag refresh

### Approach

Filter Tier C out of `find_due_meta` at the CTE level so the dispatcher never returns those appids. Because `enqueue_refresh_meta` emits both `task=metadata` and `task=tags` per returned appid, dropping Tier C here drops both metadata *and* tag ingest for long-tail games — no separate tags change needed.

Reviews are already Tier-C-excluded (`catalog_repo.py:187`: `AND g.review_count >= %(b_threshold)s`) — no change needed there.

### Edits

**`src/library-layer/library_layer/repositories/catalog_repo.py:79-147` (`find_due_meta`)**

Restructure the CTE so Tier C rows are filtered out before the smear/due comparison. Mirror the shape of `find_due_reviews`:

```sql
WITH tiered AS (
  SELECT
    ac.*,
    CASE
      WHEN g.review_count >= %(s_threshold)s THEN %(s_secs)s
      WHEN COALESCE(g.coming_soon, FALSE) = TRUE
        OR gg.genre_id IS NOT NULL
        OR g.review_count >= %(a_threshold)s THEN %(a_secs)s
      ELSE %(b_secs)s                        -- B tier (catch-all for qualifiers)
    END AS window_secs,
    CASE
      WHEN g.review_count >= %(s_threshold)s THEN 0
      WHEN COALESCE(g.coming_soon, FALSE) = TRUE
        OR gg.genre_id IS NOT NULL
        OR g.review_count >= %(a_threshold)s THEN 1
      ELSE 2
    END AS tier_rank
  FROM app_catalog ac
  JOIN games g ON g.appid = ac.appid
  LEFT JOIN game_genres gg ON gg.appid = ac.appid AND gg.genre_id = 70
  WHERE ac.meta_status = 'done'
    AND (
      COALESCE(g.coming_soon, FALSE) = TRUE
      OR gg.genre_id IS NOT NULL
      OR g.review_count >= %(b_threshold)s   -- excludes Tier C
    )
)
SELECT * FROM tiered
WHERE
  meta_crawled_at IS NULL
  OR meta_crawled_at
     + (window_secs * INTERVAL '1 second')
     + ((abs(hashtext(appid::text)::bigint) %% window_secs) * INTERVAL '1 second')
     < NOW()
ORDER BY tier_rank, meta_crawled_at ASC NULLS FIRST
LIMIT %(limit)s
```

Drop the `c_secs` local var and the `"c_secs"` param binding.

**`src/library-layer/library_layer/config.py`**

- Remove `REFRESH_META_TIER_C_DAYS` (line 127).
- Remove its entry from the `day_fields` tuple in `_validate_refresh_tier_config` (line 163).
- Update the header comment at line 123: "Metadata covers S/A/B (Tier C long-tail is refresh-exempt — graduation re-entry is operator-driven, see `scripts/trigger_crawl.py`)".

**`src/library-layer/library_layer/models/catalog.py`**

Check `CatalogEntry.tier_rank` docstring/comment — `tier_rank = 3` is now unreachable. Either remove the rank-3 case from comments or leave a note that it no longer appears in dispatcher output.

### Graduation gap — known and acceptable

A Tier C game whose review_count later crosses 50 cannot auto-graduate to Tier B, because `g.review_count` is only updated via metadata refresh (`catalog_repo.set_meta_status` at `catalog_repo.py:222-228` writes it from the ingest payload). With Tier C refresh disabled, the review_count in `games` freezes at whatever it held at its last successful meta crawl.

**Escape hatch already exists**: `scripts/trigger_crawl.py` lets an operator force a metadata crawl for any appid. Post-crawl, the next dispatcher run sees the updated review_count and the game enters the appropriate tier naturally.

**If auto-graduation becomes a real problem later:** the cheapest follow-up is a quarterly job that bulk-updates `games.review_count` from Steam's `appreviews?json=1&filter=summary` endpoint (one JSON call per appid, no full appdetails refresh) for Tier C appids. Not in this plan.

### Tests to update

- `tests/repositories/test_catalog_repo.py` — add / update assertions that `find_due_meta` never returns a game with `review_count < 50` and `coming_soon = FALSE` and no EA genre. Existing Tier C test cases need to flip from "eventually returned" to "never returned."
- Any test that relies on `REFRESH_META_TIER_C_DAYS` being set — grep for it before editing.

---

## Change 2 — Single bulk DELETE in `upsert_tags`

### Approach

Replace the per-appid DELETE loop in `tag_repo.py:108-116` with a single set-based DELETE using the `(appid, tag_id)` tuples of *kept* associations for this batch.

### Edit

**`src/library-layer/library_layer/repositories/tag_repo.py:108-116`**

Current:
```python
appid_tag_ids: dict[int, list[int]] = defaultdict(list)
for aid, tid, _ in game_tag_rows:
    appid_tag_ids[aid].append(tid)
for aid, tids in appid_tag_ids.items():
    cur.execute(
        "DELETE FROM game_tags WHERE appid = %s AND tag_id != ALL(%s)",
        (aid, tids),
    )
```

Replace with a single statement covering the whole batch — delete any `game_tags` row for a touched appid whose `(appid, tag_id)` pair is not in the batch's keep-set. Expected shape:

```python
batch_appids = list({aid for aid, _, _ in game_tag_rows})
if batch_appids:
    kept_pairs = [(aid, tid) for aid, tid, _ in game_tag_rows]
    # One DELETE for the entire batch; stale pairs removed, current kept.
    execute_values(
        cur,
        """
        DELETE FROM game_tags gt
        USING (VALUES %s) AS kept(appid, tag_id)
        WHERE gt.appid = ANY(%s)
          AND NOT EXISTS (
              SELECT 1 FROM (VALUES %s) AS k(appid, tag_id)
              WHERE k.appid = gt.appid AND k.tag_id = gt.tag_id
          )
        """,
        kept_pairs,
        ...  # final param binding pattern to be confirmed during implementation
    )
```

Final SQL/param-binding shape to be pinned down when coding — the structural change is: **one DELETE statement per batch instead of one per appid**. Covered by existing unit tests + new test for multi-appid batch semantics.

### Tests to update

- `tests/repositories/test_tag_repo.py` (add file if missing): cover the stale-deletion case with a batch spanning multiple appids, asserting (a) stale associations disappear for touched appids, (b) non-batch appids' tags are untouched.

---

## Verification

1. **Unit tests:**
   - `poetry run pytest tests/repositories/test_catalog_repo.py -k find_due_meta -v` — confirm Tier C never appears.
   - `poetry run pytest tests/repositories/test_tag_repo.py -k upsert -v` — confirm bulk-DELETE preserves correct rows across multi-appid batches.
2. **Integration (staging):** `poetry run python scripts/sp.py catalog refresh_meta --limit 50` and inspect the structured log at `catalog_service.py:170-181` — `dispatched_by_tier` is logged with tier labels (`S`/`A`/`B`/`C`/`unknown`), so verify `C` stays `0` and no `unknown` bucket appears.
3. **Prod cutover:** deploy, then watch CloudWatch RDS `WriteIOPS` and `WriteThroughput` for 24 hours. Expected drop is proportional to Tier C's share of prior volume plus the tag-DELETE statement reduction. Also watch spoke SQS queue depth — should *decrease* since fewer messages enqueued per hour.
4. **Safety check:** after cutover, verify `sp.py catalog status` still shows `meta_status = 'done'` counts holding steady (no flood of new pending rows, which would signal the catalog discovery path is misbehaving).

## Critical files

- `src/library-layer/library_layer/repositories/catalog_repo.py:79-147` — `find_due_meta` SQL
- `src/library-layer/library_layer/config.py:118-189` — tier config + validator
- `src/library-layer/library_layer/repositories/tag_repo.py:27-117` — tag upsert
- `src/library-layer/library_layer/models/catalog.py` — CatalogEntry docstring cleanup
