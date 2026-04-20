# Plan: Tiered Refresh Scheduling with Deterministic Smearing

## Context

Today's refresh story is uneven:

- **Metadata** has a daily `stale_refresh` EventBridge rule (`compute_stack.py`)
  that calls `catalog_repo.find_stale_meta(limit=2000)` — a simple two-tier
  scheme (EA / `review_count>=1000` → 7d; everything else → 30d). It runs as
  one daily batch, all games lumped together.
- **Reviews** have **no refresh path at all**. The only time reviews get
  re-crawled is when a human (or `sp.py`) explicitly asks for it. Review
  counts in `games` drift from reality the moment metadata crawl updates the
  aggregate while the review rows themselves stay frozen.
- **Tags** ride along with metadata and share its cadence.

Two specific problems with today's setup:

1. **Thundering-herd batch**: the daily stale run enqueues up to 2000 appids
   at once — a burst on the Steam API, SQS, spokes, and DB. If that burst
   fails partway, recovery is ad-hoc.
2. **No review freshness**: popular games accumulate hundreds of reviews a
   week. Our `reviews` table and any sentiment/velocity metrics derived from
   it go stale and nobody notices.

**Goal**: replace the single undifferentiated stale refresh with a tiered
schedule (cadence scales with popularity/EA status) and spread the work
deterministically over the refresh window so load is smooth and recoverable.
Cover both **metadata** and **reviews**, with separate cadences.

### Hard constraints (non-negotiable)

1. **No automatic LLM analysis from refresh.** The existing
   `_trigger_analysis()` call at `crawl_service.py:214` fires Step Functions
   (~$1/game) every time reviews are ingested. Refresh-driven review crawls
   MUST NOT trigger this. LLM re-analysis policy is a separate design —
   deferred, not in scope.
2. **Ship the code, leave the schedule OFF.** Define the EventBridge rule
   with `enabled=False` (same pattern `GenreSynthesisWeeklyRule` uses at
   `compute_stack.py:824`). The user flips it on manually after review.
3. **No new feature flags or dual paths at runtime.** The disabled rule is a
   deployment switch, not a runtime shim. Code paths are single-path.

---

## Design

### 1. Tier definitions

Tiers are computed from what's already in the DB (`games.review_count`,
`games.coming_soon`, `game_genres.genre_id=70` for Early Access). No new
columns, no maintenance cascades when `review_count` changes.

| Tier | Membership (first match wins)                           | Metadata | Reviews |
| ---- | ------------------------------------------------------- | -------- | ------- |
| S    | `review_count >= 10_000`                                | 2 days   | 1 day   |
| A    | `coming_soon = TRUE` OR on EA genre OR `review_count >= 1_000` | 7 days   | 3 days  |
| B    | `review_count >= 50` (the existing analysis eligibility threshold) | 21 days  | 14 days |
| C    | everything else (low-signal long tail)                  | 90 days  | never   |

Why these numbers:

- **S** matches roughly the top ~2–3k games on Steam. 1-day reviews catches
  real momentum; 2-day metadata catches price changes and tag drift quickly.
- **A** is the existing EA + popular bucket, kept at 7d metadata for
  continuity. 3-day reviews because these games also grow reviews fast.
- **B** = any game with enough reviews to be analysis-eligible. Metadata
  drifts slowly here; reviews grow slowly but still meaningfully over 2
  weeks.
- **C** tail: metadata every 90 days is basically "catch DLCs and renames";
  no review refresh at all — the signal-to-cost ratio isn't there. `C`
  games that later cross the 50-review bar naturally promote to `B` on
  their next metadata crawl.

Tier constants live in `config.py` (not hard-coded in SQL) so tuning doesn't
need a migration.

### 2. Deterministic smearing (the "spread over the window" part)

Canonical Jenkins-`H` pattern: a game's refresh slot is `hash(appid) mod
window`, computed in Postgres with `hashtext(appid::text)`. Hourly
dispatcher picks up anything whose due time has passed. The effect: games
in the same tier are smeared evenly across their refresh window instead of
all firing on the same boundary.

SQL (metadata example — reviews are identical with a different interval
expression):

```sql
-- tier_interval is a SQL CASE; smear_seconds scales with the tier window
WITH tiered AS (
  SELECT
    ac.appid,
    ac.meta_crawled_at,
    CASE
      WHEN g.review_count >= 10000 THEN INTERVAL '2 days'
      WHEN g.coming_soon OR gg_ea.genre_id IS NOT NULL
           OR g.review_count >= 1000 THEN INTERVAL '7 days'
      WHEN g.review_count >= 50 THEN INTERVAL '21 days'
      ELSE INTERVAL '90 days'
    END AS tier_interval,
    CASE
      WHEN g.review_count >= 10000 THEN 0  -- priority sort key
      WHEN g.coming_soon OR gg_ea.genre_id IS NOT NULL
           OR g.review_count >= 1000 THEN 1
      WHEN g.review_count >= 50 THEN 2
      ELSE 3
    END AS tier_rank
  FROM app_catalog ac
  JOIN games g ON g.appid = ac.appid
  LEFT JOIN game_genres gg_ea
         ON gg_ea.appid = ac.appid AND gg_ea.genre_id = 70
  WHERE ac.meta_status = 'done'
)
SELECT appid
FROM tiered
WHERE
  meta_crawled_at IS NULL
  OR meta_crawled_at
     + tier_interval
     + (abs(hashtext(appid::text)) % EXTRACT(EPOCH FROM tier_interval)::int)
       * INTERVAL '1 second'
     < NOW()
ORDER BY tier_rank, meta_crawled_at ASC NULLS FIRST
LIMIT %s;
```

The smear term `(hash(appid) % window_seconds) * INTERVAL '1 second'`
pushes each game's due time into a deterministic slot within its tier's
window. Two properties worth naming:

- **Deterministic**: same appid always lands in the same slot, so we don't
  oscillate between "due / not due" as the dispatcher polls.
- **Rebalances naturally**: when a game crosses a tier boundary (e.g. its
  `review_count` grows past 1000), its tier_interval changes and its slot
  re-derives from the same hash — no state to migrate.

For reviews, substitute `ac.review_crawled_at` and the review-tier
intervals. Tier C is excluded from the review query entirely (no
`NOT NULL OR <due>` clause — just a `WHERE review_count >= 50`).

### 3. Hourly dispatcher

Replace the existing daily `stale_refresh` EventBridge rule with two hourly
rules (one per kind). Each fires a new action on `CrawlerFn` that picks up
the top-K due candidates and enqueues them.

| Rule (new)              | Cadence | Action                     | Limit (initial) |
| ----------------------- | ------- | -------------------------- | --------------- |
| `RefreshMetaRule`       | hourly  | `{"action":"refresh_meta"}`     | 200             |
| `RefreshReviewsRule`    | hourly  | `{"action":"refresh_reviews"}`  | 100             |

Both **`enabled=False`** initially (see hard constraint #2).

Hourly × 200 = 4800 metadata crawls/day ceiling; hourly × 100 = 2400 review
crawls/day ceiling. Comfortably under Steam API ceilings (community-reported
~57k appdetails/day per IP). Limits live in `config.py`.

The old `StaleMetaRefreshRule` (daily, limit=2000) and the `stale_refresh`
action it invokes are **removed** — the new tiered path supersedes them.
Anything still on `meta_crawled_at IS NULL` gets picked up by the new query
immediately (it sorts `NULLS FIRST`), so no data is orphaned.

### 4. No-LLM-from-refresh safeguard

Add an explicit parameter to `CrawlService.crawl_reviews()`:

```python
def crawl_reviews(
    self,
    appid: int,
    game_name: str,
    *,
    trigger_analysis: bool = True,  # preserves existing first-crawl behavior
) -> None:
    ...
    if trigger_analysis:
        self._trigger_analysis(appid, game_name)
```

Refresh-driven review crawls call with `trigger_analysis=False`. The SNS
event-driven first-crawl path (new games) keeps the default `True` so
nothing about new-game onboarding changes. This is a function parameter,
not a runtime feature flag — consistent with the "no flags" rule.

The refresh enqueue goes to the **same** `ReviewCrawlQ`, so we need a way
for the ingest handler to know to pass `trigger_analysis=False` when the
message is refresh-sourced. Simplest: extend `ReviewCrawlMessage` (already
exists in `library_layer/utils/events.py` per `review-crawl-backfill.md`)
with a `source` discriminator:

```python
class ReviewCrawlMessage(BaseModel):
    appid: int
    source: Literal["new_game", "refresh"] = "new_game"
```

Per `feedback_subclass_typing.md` — this is a simple flag on a single
model, not a subclass discriminator, so `Literal` + default is the right
shape.

### 5. Observability

Three things to log/emit so we can tell the scheduler is working without
sitting on the dashboard:

- Per dispatch: `logger.info("refresh_meta dispatched", enqueued=N, limit=L, oldest_due_age_hours=H)` where `H` is `now() - min(meta_crawled_at)` of the batch. When `H` starts drifting upward over days, we're falling behind and need to raise the limit.
- Per tier: `dispatched_by_tier={S: n, A: n, B: n, C: n}` — validates the smearing is working (tiers should be roughly proportional to their populations scaled by refresh rate).
- CloudWatch metric dimension `tier` on the existing crawl metrics, so the dashboard can break out spoke latency by tier later without a second pass.

Dashboard wiring is out of scope — metrics just need to be emitted so a
future `monitor-refresh-scheduler.md` follow-up has them to hang alarms on.

---

## Out of scope (explicitly deferred)

- **Automatic LLM re-analysis on review refresh**. The whole point of
  `trigger_analysis=False` is to keep this deferred. The follow-up will add
  change-detection (content hash over reviews, delta thresholds like
  "re-analyze when reviews grew ≥ max(20, 5%)") and a separate
  `analysis_refresh` path. Don't back-door that in here.
- **Turning the schedule on**. Rules ship disabled.
- **Wedge-based priority overrides** (e.g. "elevate roguelike-deckbuilder
  games to S regardless of review count"). The tier signals today are pure
  review-count + EA; that's enough for v1.
- **Review-cursor continuation for large re-crawls**. Reviews use the same
  cursor-based pagination as the existing crawl; if a game has 50k+ reviews
  and we can't finish in one Lambda invocation, the cursor is already
  persisted and the next scheduled refresh resumes. No new code.
- **Per-tier queue partitioning**. One metadata queue, one review queue
  (the ones we already have). Tier information is used only for dispatch
  prioritization, not queue routing.

---

## Files to Change

### 1. `config.py` — tier + dispatcher constants

`src/library-layer/library_layer/config.py`

```python
# Refresh tier intervals (metadata)
REFRESH_META_TIER_S_DAYS: int = 2
REFRESH_META_TIER_A_DAYS: int = 7
REFRESH_META_TIER_B_DAYS: int = 21
REFRESH_META_TIER_C_DAYS: int = 90

# Refresh tier intervals (reviews); tier C is excluded
REFRESH_REVIEWS_TIER_S_DAYS: int = 1
REFRESH_REVIEWS_TIER_A_DAYS: int = 3
REFRESH_REVIEWS_TIER_B_DAYS: int = 14

# Tier membership thresholds
REFRESH_TIER_S_REVIEW_COUNT: int = 10_000
REFRESH_TIER_A_REVIEW_COUNT: int = 1_000
REFRESH_TIER_B_REVIEW_COUNT: int = 50  # mirrors REVIEW_ELIGIBILITY_THRESHOLD

# Hourly dispatcher batch sizes
REFRESH_META_BATCH_LIMIT: int = 200
REFRESH_REVIEWS_BATCH_LIMIT: int = 100
```

### 2. `catalog_repo.py` — replace `find_stale_meta`, add review finder

`src/library-layer/library_layer/repositories/catalog_repo.py`

- **Replace** `find_stale_meta()` with `find_due_meta(limit, config)` using
  the smeared-slot query from §2 above. Config gives it the tier intervals
  and thresholds; no magic numbers in SQL.
- **Add** `find_due_reviews(limit, config)` — same shape, `review_crawled_at`
  instead of `meta_crawled_at`, tier C excluded (`WHERE review_count >= %s`).
- Both return `list[CatalogEntry]` (reuse the existing pydantic model).
- Delete the docstring's old tier numbers — they're wrong once this lands.

### 3. `utils/events.py` — add `source` to `ReviewCrawlMessage`

`src/library-layer/library_layer/utils/events.py`

```python
class ReviewCrawlMessage(BaseModel):
    appid: int
    source: Literal["new_game", "refresh"] = "new_game"
```

Defaults to `"new_game"` so every existing producer stays correct without a
change. Only the new refresh enqueue sets `source="refresh"`.

### 4. `crawl_service.py` — `trigger_analysis` param + refresh enqueue

`src/library-layer/library_layer/services/crawl_service.py`

- Add `trigger_analysis: bool = True` (kw-only) to `crawl_reviews()`. Gate
  the `self._trigger_analysis(appid, game_name)` call on it.
- No other change in `CrawlService`. It doesn't need to know about tiers —
  that's `CatalogService`'s job.

### 5. `catalog_service.py` — `enqueue_refresh_meta` + `enqueue_refresh_reviews`

`src/library-layer/library_layer/services/catalog_service.py`

```python
def enqueue_refresh_meta(self, limit: int) -> int:
    """Enqueue the next batch of tier-due metadata refreshes."""
    entries = self._catalog_repo.find_due_meta(limit, self._config)
    if not entries:
        return 0
    # Existing app-crawl fan-out path — same message shape as pending crawl
    send_sqs_batch(self._sqs, self._app_queue_url,
                   [{"appid": e.appid} for e in entries])
    return len(entries)

def enqueue_refresh_reviews(self, limit: int) -> int:
    """Enqueue the next batch of tier-due review refreshes."""
    entries = self._catalog_repo.find_due_reviews(limit, self._config)
    if not entries:
        return 0
    send_sqs_batch(self._sqs, self._review_queue_url,
                   [ReviewCrawlMessage(appid=e.appid,
                                       source="refresh").model_dump()
                    for e in entries])
    return len(entries)
```

### 6. `crawler/events.py` — two new direct-action request models

`src/lambda-functions/lambda_functions/crawler/events.py`

```python
class RefreshMetaRequest(BaseModel):
    action: Literal["refresh_meta"]
    limit: int = 200

class RefreshReviewsRequest(BaseModel):
    action: Literal["refresh_reviews"]
    limit: int = 100
```

Extend the `DirectRequest` discriminated union.

**Remove** `StaleRefreshRequest` and any `stale_refresh` handling — it's
superseded.

### 7. `crawler/handler.py` — dispatch + consume `source`

`src/lambda-functions/lambda_functions/crawler/handler.py`

- Add dispatcher cases:
  ```python
  case RefreshMetaRequest():
      n = _catalog_service.enqueue_refresh_meta(req.limit)
      logger.info("refresh_meta complete", extra={"enqueued": n, "limit": req.limit})
      return {"enqueued": n, "limit": req.limit}
  case RefreshReviewsRequest():
      n = _catalog_service.enqueue_refresh_reviews(req.limit)
      logger.info("refresh_reviews complete", extra={"enqueued": n, "limit": req.limit})
      return {"enqueued": n, "limit": req.limit}
  ```
- Delete the old `stale_refresh` case.

### 8. `crawler/ingest_handler.py` — thread `source` → `trigger_analysis`

`src/lambda-functions/lambda_functions/crawler/ingest_handler.py`

Where reviews get ingested from the `ReviewCrawlQ`, parse the message with
`ReviewCrawlMessage.model_validate_json()`, then:

```python
_crawl_service.crawl_reviews(
    appid=msg.appid,
    game_name=game_name,
    trigger_analysis=(msg.source == "new_game"),
)
```

### 9. `compute_stack.py` — swap rules

`infra/stacks/compute_stack.py`

- **Remove** the existing `StaleMetaRefreshRule` block (and its payload).
- **Add** two new rules, both disabled:

```python
refresh_meta_rule = events.Rule(
    self, "RefreshMetaRule",
    schedule=events.Schedule.rate(cdk.Duration.hours(1)),
    enabled=False,  # user flips on manually after review
)
refresh_meta_rule.add_target(events_targets.LambdaFunction(
    crawler_fn,
    event=events.RuleTargetInput.from_object(
        {"action": "refresh_meta", "limit": 200}
    ),
))

refresh_reviews_rule = events.Rule(
    self, "RefreshReviewsRule",
    schedule=events.Schedule.rate(cdk.Duration.hours(1)),
    enabled=False,
)
refresh_reviews_rule.add_target(events_targets.LambdaFunction(
    crawler_fn,
    event=events.RuleTargetInput.from_object(
        {"action": "refresh_reviews", "limit": 100}
    ),
))
```

### 10. `scripts/sp.py` — operator shortcuts

`scripts/sp.py` — add two helpers so the user can dry-run the dispatcher
without enabling the rule:

```python
def refresh_meta_once(limit: int = 200) -> int: ...
def refresh_reviews_once(limit: int = 100) -> int: ...
```

Both instantiate the services and call `enqueue_refresh_*`. Useful for the
bake-in period after deploy and before flipping the EventBridge switch on.

### 11. Tests

`src/library-layer/tests/repositories/test_catalog_repo.py`

- `test_find_due_meta_smears_by_hash`: insert 10 games with the same
  `review_count` and `meta_crawled_at`, assert that not all are returned
  for a single `NOW()` (their hash offsets spread them out).
- `test_find_due_meta_respects_tier`: S-tier game with `meta_crawled_at =
  now() - 3 days` is due; A-tier with same timestamp is also due; C-tier
  with `now() - 30 days` is not due (90-day interval).
- `test_find_due_meta_null_first`: a row with `meta_crawled_at IS NULL`
  comes back in the first slot regardless of hash.
- `test_find_due_reviews_excludes_tier_c`: a game with `review_count=10`
  never appears in the review query even with old `review_crawled_at`.

`src/library-layer/tests/services/test_crawl_service.py`

- `test_crawl_reviews_refresh_source_skips_analysis`: with
  `trigger_analysis=False`, the Step Functions mock is not called.
- `test_crawl_reviews_default_triggers_analysis`: default path still calls
  it (regression guard).

`src/library-layer/tests/services/test_catalog_service.py`

- `test_enqueue_refresh_reviews_tags_source`: the enqueued SQS message body
  parses as `ReviewCrawlMessage(source="refresh")`.

Per `feedback_test_db.md`, all DB tests run against `steampulse_test`.

### 12. `schema.py` — no change needed

No new indexes. The existing index on `app_catalog(meta_status,
meta_crawled_at)` is sufficient; the hash computation is per-row and fast.
`hashtext()` is immutable so Postgres can inline it in the plan.

---

## Implementation Order

1. `config.py` constants
2. `utils/events.py` — `source` field on `ReviewCrawlMessage`
3. `catalog_repo.py` — `find_due_meta`, `find_due_reviews` (delete
   `find_stale_meta`)
4. `crawl_service.py` — `trigger_analysis` parameter
5. `catalog_service.py` — `enqueue_refresh_meta`, `enqueue_refresh_reviews`
6. `crawler/events.py` — new request models, drop `stale_refresh`
7. `crawler/handler.py` — new dispatcher cases, drop old
8. `crawler/ingest_handler.py` — thread `source` through
9. Tests (all new + regression on `crawl_reviews`)
10. `scripts/sp.py` — operator shortcuts
11. `compute_stack.py` — swap EventBridge rules, rules disabled

Per `feedback_update_tests_on_import_changes.md`: after step 3, grep for
any remaining `find_stale_meta` references and update callers before
running tests.

Per `feedback_lock_files.md`: no new deps, so no `poetry lock` refresh.

---

## Verification

```bash
# Migrations — none needed (no schema change)

# Unit tests (library layer)
poetry run pytest \
  src/library-layer/tests/repositories/test_catalog_repo.py \
  src/library-layer/tests/services/test_crawl_service.py \
  src/library-layer/tests/services/test_catalog_service.py -v

# Handler tests
poetry run pytest src/lambda-functions/tests/crawler/ -v

# CDK diff (confirms old rule removed + new rules created, both disabled)
poetry run cdk diff SteamPulsePipeline/Staging/Compute

# Operator dry-run (after deploy, before enabling rules)
poetry run python -c "from scripts.sp import refresh_meta_once; \
  print(refresh_meta_once(limit=5))"
poetry run python -c "from scripts.sp import refresh_reviews_once; \
  print(refresh_reviews_once(limit=5))"
```

Expected CDK diff shape:

```
[-] EventBridge Rule StaleMetaRefreshRule
[+] EventBridge Rule RefreshMetaRule      (Enabled: false)
[+] EventBridge Rule RefreshReviewsRule   (Enabled: false)
```

## Enablement (deferred — user-driven)

After deploy and a clean dry-run, the user enables the rules manually via
console or by flipping `enabled=True` in `compute_stack.py` and
redeploying. The first hour after enablement will re-crawl anything with
`NULL` timestamps (there shouldn't be many — the existing daily
stale-refresh has been populating `meta_crawled_at` for a while). Watch
the `oldest_due_age_hours` log line for a few days; if it keeps climbing,
raise the batch limits.
