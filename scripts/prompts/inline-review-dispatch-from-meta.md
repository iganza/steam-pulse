# Inline review-dispatch from meta ingest

## Context

After 0055 shipped delta-gated review refresh, the architecture became:

```
RefreshMetaRule (hourly @ :00)    → CrawlerFn → meta ingest → writes games.review_count_english
RefreshReviewsRule (hourly @ :30) → CrawlerFn → find_due_reviews() reads it → delta gate → enqueue
```

The two scheduled rules are now logically coupled but architecturally independent. The review dispatcher can only see new deltas *after* meta has refreshed `review_count_english` for that game — so review tier intervals (S=1d/A=3d/B=14d) are bounded above by meta tier intervals (S=2d/A=7d/B=21d) and the faster review windows are unreachable in practice.

Operationally this means:
- The hourly review dispatcher fires ~720×/month and skips most rows because the upstream signal hasn't moved
- Two scheduled jobs maintain one logical pipeline
- 1-hour worst-case lag between meta-write and review-dispatch
- Review tier-window config is misleading — declares a cadence that can't be achieved

The cleaner design: dispatch the review crawl inline from meta ingest, at the moment the `review_count_english` delta crosses threshold. The meta cron becomes the only signal source. No second scheduler.

## Goal

Replace the second EventBridge rule with inline dispatch from `_ingest_app_data`, gated on a new `REFRESH_REVIEWS_ENABLED` config kill-switch so the whole review-fetch pipeline can be turned off via a single env var flip without code changes.

**Estimated impact:**
- Eliminates ~720 dispatcher invocations/month (negligible $ but cleaner)
- Removes the 1-hour meta→review lag — review crawl enqueues at the exact moment meta observes the delta
- Removes misleading review tier-window config from the dispatch path
- Provides operator kill-switch for cost containment: flip `REFRESH_REVIEWS_ENABLED=false` on the `CrawlerFn` Lambda env, no review fetches enqueue at all

The architectural cleanup is the primary motivation; the kill-switch closes the cost-blast-radius concern.

## Approach

### 1. Add `REFRESH_REVIEWS_ENABLED` to config — `src/library-layer/library_layer/config.py` `[code]`

New field, no default per `feedback_no_field_defaults`:

```python
REFRESH_REVIEWS_ENABLED: bool  # gate inline review dispatch from meta ingest
```

When `False`: meta ingest never enqueues review crawls. The operator-triggered path (`sp.py refresh-reviews` → `CatalogService.enqueue_refresh_reviews(limit=...)`) is intentionally NOT gated — operator override bypasses the kill-switch (e.g. wedge backfills must still work).

### 2. Wire in every env file `[code]`

- `.env.example`: `REFRESH_REVIEWS_ENABLED=true`
- `.env`: `REFRESH_REVIEWS_ENABLED=false` (local dev — never enqueue from local meta runs)
- `.env.staging`: `REFRESH_REVIEWS_ENABLED=false` (no staging deploy, but field is required)
- `.env.production`: `REFRESH_REVIEWS_ENABLED=true`

Note: per `feedback_no_staging_schedules`, prod is the only deployed env. `.env.staging` exists only to satisfy config validation in CI.

### 3. Add a single-appid enqueue method — `src/library-layer/library_layer/services/catalog_service.py` `[code]`

Current `enqueue_refresh_reviews(limit: int)` walks `find_due_reviews()`. Add a sibling method that enqueues an explicit list — used by the inline dispatch path:

```python
def enqueue_review_crawl_for_appids(self, appids: list[int]) -> int:
    """Enqueue review crawl for explicit appids. Used by inline dispatch from
    meta ingest; bypasses tier-window/delta SQL gate (caller has already
    decided). Returns count enqueued."""
    if not appids:
        return 0
    messages = [
        ReviewCrawlMessage(appid=a, source="refresh").model_dump()
        for a in appids
    ]
    send_sqs_batch(self._sqs, self._review_crawl_queue_url, messages)
    logger.info(
        "inline_review_dispatch enqueued",
        extra={"appids": appids, "count": len(appids)},
    )
    return len(appids)
```

Distinct method (not an overload on `enqueue_refresh_reviews`) so the dispatcher-vs-inline call sites stay clearly separable in logs and tests.

### 4. Inline dispatch from meta ingest — `src/library-layer/library_layer/services/crawl_service.py` `[code]`

In `_ingest_app_data` (line 297), after the games-row upsert returns the new row, observe the delta and dispatch:

```python
# Inline review-crawl dispatch (replaces RefreshReviewsRule scheduler).
# Gated on REFRESH_REVIEWS_ENABLED kill-switch.
if self._config.REFRESH_REVIEWS_ENABLED:
    self._maybe_dispatch_review_crawl(appid, existing, game_data)
```

New helper on `CrawlService`:

```python
def _maybe_dispatch_review_crawl(
    self,
    appid: int,
    existing: dict | None,
    game_data: dict,
) -> None:
    """If the meta ingest observed a review-count delta worth refetching,
    enqueue a review crawl. Mirrors find_due_reviews() gate logic but in
    Python on the just-ingested row, so dispatch happens at the moment the
    signal changes — no second scheduler, no SQL re-poll."""
    new_rce = game_data.get("review_count_english", 0) or 0

    # Tier eligibility (matches find_due_reviews WHERE clause)
    if new_rce < self._config.REFRESH_TIER_B_REVIEW_COUNT:
        return  # tier C or below — no review refresh
    if game_data.get("coming_soon"):
        return  # no reviews to refresh until launch

    old_rce = (existing.get("review_count_english") if existing else 0) or 0
    delta = new_rce - old_rce

    # Mirror find_due_reviews() final WHERE: NULL OR delta>=min OR 30d-stale
    review_crawled_at = existing.get("review_crawled_at") if existing else None
    is_first_fetch = review_crawled_at is None
    delta_met = delta >= self._config.REFRESH_REVIEWS_MIN_DELTA
    is_stale = (
        review_crawled_at is not None
        and (datetime.now(tz=timezone.utc) - review_crawled_at).days >= 30
    )

    if is_first_fetch or delta_met or is_stale:
        self._catalog_service.enqueue_review_crawl_for_appids([appid])
```

Notes:
- Reuses `existing` (already loaded by `find_event_snapshot` upstream — no extra DB call)
- `find_event_snapshot` currently returns `dict | None`; verify it includes `review_count_english`, `review_crawled_at`, `coming_soon`. If not, extend the SELECT in `game_repo.py:144` (this is the only repo change).
- The Python condition mirrors `find_due_reviews()`'s final WHERE clause exactly — same semantics, just evaluated inline instead of via SQL.

### 5. Delete `RefreshReviewsRule` — `infra/stacks/compute_stack.py` `[code]`

Lines ~1089–1108: remove `refresh_reviews_rule` and its `add_target` call entirely. Remove any matching assertion in `tests/infra/test_compute_stack.py`.

The `refresh_reviews` action handler in the crawler Lambda stays intact — `sp.py refresh-reviews` operator path still routes through it.

### 6. Tests — `tests/services/test_crawl_service.py` `[code]`

Add cases for `_maybe_dispatch_review_crawl`:
- `REFRESH_REVIEWS_ENABLED=False` → never dispatches (test the kill-switch)
- `new_rce < TIER_B_THRESHOLD` → no dispatch
- `coming_soon=True` → no dispatch
- `existing is None` (first fetch) → dispatches
- `delta >= MIN_DELTA` → dispatches
- `delta < MIN_DELTA AND not stale` → no dispatch
- `review_crawled_at < 30d ago AND delta < MIN_DELTA` → no dispatch
- `review_crawled_at >= 30d ago` → dispatches (safety net)

Update `tests/conftest.py` to add `REFRESH_REVIEWS_ENABLED=true` to the test env dict.
Update `tests/test_config.py` — no default to assert; assert env var is required.

Per `feedback_test_db.md`, repository tests must hit `steampulse_test`.

### 7. Update tiered-refresh docs — `tiered-refresh-schedule.org` `[doc]`

Update the doc to reflect the new architecture:
- Remove the `RefreshReviewsRule` row from the cron table
- Note that review dispatch is inline from meta ingest, gated on `REFRESH_REVIEWS_ENABLED`
- Review tier intervals (`REFRESH_REVIEWS_TIER_*_DAYS`) only affect the operator-triggered `sp.py refresh-reviews` path now; not the steady-state pipeline

## Critical files

- `src/library-layer/library_layer/config.py` — add `REFRESH_REVIEWS_ENABLED`
- `.env`, `.env.example`, `.env.staging`, `.env.production` — wire the new field
- `src/library-layer/library_layer/services/catalog_service.py` — add `enqueue_review_crawl_for_appids`
- `src/library-layer/library_layer/services/crawl_service.py:297` — inline dispatch in `_ingest_app_data`, plus `_maybe_dispatch_review_crawl` helper
- `src/library-layer/library_layer/repositories/game_repo.py:144` — verify `find_event_snapshot` returns the fields the helper needs (extend SELECT if not)
- `infra/stacks/compute_stack.py:1089-1108` — delete `RefreshReviewsRule`
- `tests/services/test_crawl_service.py` — gate behavior tests
- `tests/infra/test_compute_stack.py` — drop matching assertion
- `tests/conftest.py`, `tests/test_config.py` — env wiring
- `tiered-refresh-schedule.org` — doc update

## Out of scope

- **Review tier-window config retirement** — `REFRESH_REVIEWS_TIER_S/A/B_DAYS` and the dispatcher-path `enqueue_refresh_reviews(limit=)` stay intact. Operator-triggered drain (`sp.py refresh-reviews`) still uses them. Revisit only if the operator path also gets eliminated.
- **Touching the metadata cron** — `RefreshMetaRule` cadence and `find_due_meta()` semantics unchanged.
- **Backfill** — no migration needed. The 0055 migration already initialized `review_count_at_last_fetch` to current `review_count_english` for previously-fetched rows. Cold deploy: first meta pass per game observes delta=0 → no dispatch unless real growth has accrued.
- **Auto-redeploy on env-var flip** — operator flips `REFRESH_REVIEWS_ENABLED` via `aws lambda update-function-configuration` (or a `cdk deploy` with edited env file). Lambda re-inits within ~1 minute.

## Verification

### Local

```bash
poetry run pytest tests/services/test_crawl_service.py -k "maybe_dispatch_review_crawl" -v
poetry run pytest tests/  # full suite, --no-mock policy applies (feedback_test_db)
```

### Pre-deploy sanity

Re-confirm `find_event_snapshot` returns `review_count_english`, `review_crawled_at`, and `coming_soon`. If not, extend before deploying or `_maybe_dispatch_review_crawl` will silently skip dispatches.

### Post-deploy (24–48h after enabling, with `REFRESH_REVIEWS_ENABLED=true`)

```bash
# 1. Confirm RefreshReviewsRule is gone
aws events list-rules --name-prefix Refresh --region us-west-2 --output table
# Expect: only RefreshMetaRule (and CatalogRefresh)

# 2. Confirm review-crawl queue is being fed by inline dispatch (not cron)
aws cloudwatch get-metric-statistics --namespace AWS/SQS --metric-name NumberOfMessagesSent \
  --dimensions Name=QueueName,Value=steampulse-review-crawl-production \
  --start-time $(date -v-2d -u +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 3600 --statistics Sum --region us-west-2
# Pattern should track meta-ingest hour-by-hour, not the prior :30-spike pattern

# 3. Grep dispatcher logs for the new event
poetry run python scripts/logs.py crawler --env production --grep inline_review_dispatch
```

### Kill-switch validation

In a quiet hour, flip the var off and confirm dispatches stop:

```bash
aws lambda update-function-configuration \
  --function-name SteamPulse-Production-Compute-CrawlerFn518AFFDE-bOATzXaXrnJG \
  --environment "Variables={...,REFRESH_REVIEWS_ENABLED=false}" \
  --region us-west-2

# Wait one meta cycle (1 hour). Check queue:
aws sqs get-queue-attributes \
  --queue-url $(aws sqs get-queue-url --queue-name steampulse-review-crawl-production --region us-west-2 --query QueueUrl --output text) \
  --attribute-names ApproximateNumberOfMessagesSent \
  --region us-west-2
# NumberOfMessagesSent over the last hour should be ~0
```

Then flip it back on (or `cdk deploy` to restore from `.env.production`).
