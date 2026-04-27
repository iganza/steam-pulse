# Inline review-dispatch from meta ingest

## Context

After 0055 shipped delta-gated review refresh, the apparent architecture was:

```
RefreshMetaRule (hourly @ :00)    → CrawlerFn → meta ingest → writes games.review_count_english
RefreshReviewsRule (hourly @ :30) → CrawlerFn → find_due_reviews() reads it → delta gate → enqueue
```

But there's a **third path** the original framing missed. `_publish_crawl_app_events` (`crawl_service.py:486-496`) publishes `GameMetadataReadyEvent` with `is_eligible="true"` after every meta-ingest where `review_count_english >= REVIEW_ELIGIBILITY_THRESHOLD`. An SNS subscription `ReviewCrawlSub` (`messaging_stack.py:214-226`) routes those — plus `game-released` / `game-updated` — directly to `review_crawl_queue`:

```python
filter_policy={
    "$or": [
        {"event_type": ["game-metadata-ready"], "is_eligible": ["true"]},
        {"event_type": ["game-released", "game-updated"]},
    ],
}
```

So **two** producers feed `review_crawl_queue` today: the cron dispatcher and the SNS subscription. Disabling the cron leaves the SNS path firing every hour for every eligible game, ungated by delta. That's where the leftover review traffic is coming from.

This also means review tier intervals (S=1d / A=3d / B=14d) never govern steady-state cadence in practice — the SNS path bypasses them entirely, firing at meta-ingest cadence (S=2d / A=7d / B=21d) for every eligible row.

Operationally:
- The hourly cron dispatcher (`RefreshReviewsRule`) skips most rows because the upstream signal hasn't moved
- The SNS path fires aggressively (every meta-ingest of any eligible game) with no delta gate
- Two scheduled jobs and one event-driven path all maintain the same logical pipeline
- Review tier-window config is misleading — declares a cadence that's never reached

The cleaner design: dispatch the review crawl inline from meta ingest in Python, gated on the same delta logic `find_due_reviews()` uses. Single source of truth. No second scheduler, no SNS bridge. The meta cron becomes the only steady-state signal source.

## Goal

Replace **both** the `RefreshReviewsRule` cron AND the `ReviewCrawlSub` SNS subscription with inline Python dispatch from meta ingest, gated on a new `REFRESH_REVIEWS_ENABLED` config kill-switch so the whole review-fetch pipeline can be turned off via a single env var flip without code changes.

**Estimated impact:**
- Eliminates ~720 cron dispatcher invocations/month (negligible $ but cleaner)
- Eliminates the ungated SNS path (the one that's been quietly fetching reviews on every eligible meta-ingest)
- Removes the 1-hour meta→review lag from the cron path — review crawl enqueues at the exact moment meta observes the delta
- Adds delta gating to what was previously the SNS-driven always-on path
- Removes misleading review tier-window config from the dispatch path
- Provides operator kill-switch for cost containment: flip `REFRESH_REVIEWS_ENABLED=false` on the `CrawlerFn` Lambda env, no review fetches enqueue at all

The architectural cleanup is the primary motivation; the kill-switch closes the cost-blast-radius concern.

### Why drop the `game-released` and `game-updated` triggers

- **`GameUpdatedEvent`**: defined in `events.py:82` but **never published** from any active code path. It's dead routing.
- **`GameReleasedEvent`**: published from `crawl_service.py:507` when `coming_soon` flips True→False. Redundant with delta-driven first-fetch logic — a freshly-released game's first review fetch will fire the moment meta-ingest observes `review_count_english >= REFRESH_TIER_B_REVIEW_COUNT` (since `review_crawled_at IS NULL` ⇒ `is_first_fetch=True` ⇒ dispatch). The only edge case is a released game that never accumulates ≥ tier-B reviews, but that's identical to today's SNS-path behavior (which gates on the same `REVIEW_ELIGIBILITY_THRESHOLD`), so no regression.

The `GameReleasedEvent` publish site stays intact — it's still useful as a domain signal for any other consumers; we're only removing the review-crawl routing of it.

## Approach

### 1. Add `REFRESH_REVIEWS_ENABLED` to config — `src/library-layer/library_layer/config.py` `[code]`

New required field, no default per `feedback_no_field_defaults`:

```python
REFRESH_REVIEWS_ENABLED: bool  # gate inline review dispatch from meta ingest
```

When `False`: meta ingest never enqueues review crawls. The operator-triggered path (`sp.py refresh-reviews` → `CatalogService.enqueue_refresh_reviews(limit=...)`) is intentionally NOT gated — operator override bypasses the kill-switch (e.g. wedge backfills must still work).

### 2. Wire in every env file `[code]`

- `.env.example`: `REFRESH_REVIEWS_ENABLED=true`
- `.env`: `REFRESH_REVIEWS_ENABLED=false` (local dev — never enqueue from local meta runs)
- `.env.staging`: `REFRESH_REVIEWS_ENABLED=false` (no staging deploy, but field is required)
- `.env.production`: `REFRESH_REVIEWS_ENABLED=true`

Per `feedback_no_staging_schedules`, prod is the only deployed env. `.env.staging` exists only to satisfy config validation in CI.

### 3. Extend `find_event_snapshot` — `src/library-layer/library_layer/repositories/game_repo.py:144-153` `[code]`

Currently selects only `coming_soon, price_usd, review_count` from `games`. The inline dispatch helper needs `review_count_english` (already on `games`) plus `review_crawled_at` and `review_count_at_last_fetch` (both on `app_catalog`, not `games`). Extend with a `LEFT JOIN app_catalog`:

```python
def find_event_snapshot(self, appid: int) -> dict | None:
    row = self._fetchone(
        "SELECT g.coming_soon, g.price_usd, g.review_count, g.review_count_english, "
        "       c.review_crawled_at, c.review_count_at_last_fetch "
        "FROM games g LEFT JOIN app_catalog c USING (appid) "
        "WHERE g.appid = %s",
        (appid,),
    )
    return dict(row) if row else None
```

The wider snapshot is still much narrower than `find_by_appid`'s TOAST-heavy projection, so the perf rationale in the docstring stays valid. The `LEFT JOIN` (vs `INNER`) preserves the existing semantics that a row in `games` without an `app_catalog` row still returns a snapshot — `review_crawled_at` and `review_count_at_last_fetch` will simply come back as `None`.

### 4. Inline SQS dispatch in `CrawlService` (no new `CatalogService` method) `[code]`

`CrawlService` already has `self._sqs` and `self._review_queue_url` from its existing constructor — no cross-service dependency needed. Putting the dispatch on `CatalogService` would require injecting `CatalogService` into `CrawlService` and updating three construction sites (`crawler/handler.py`, `crawler/ingest_handler.py`, and `scripts/sp.py` — the last of which never builds a `CatalogService`). Simpler to keep the inline dispatch local to `CrawlService`:

```python
# Inside _maybe_dispatch_review_crawl, when the gate decides "yes":
msg = ReviewCrawlMessage(appid=appid, source="refresh").model_dump()
send_sqs_batch(self._sqs, self._review_queue_url, [msg])
logger.info("inline_review_dispatch enqueued", extra={"appid": appid})
```

The dispatcher-vs-inline distinction is preserved by the log key (`inline_review_dispatch` vs `refresh_reviews`). `CatalogService.enqueue_refresh_reviews(limit=)` stays exactly as-is for the operator drain path.

### 5. Inline dispatch from meta ingest — `src/library-layer/library_layer/services/crawl_service.py` `[code]`

`_publish_crawl_app_events` is called from **two** places — `crawl_app` (line 172, direct crawl path) and `ingest_spoke_metadata` (line 269, spoke result ingest path). Both produce `GameMetadataReadyEvent` and so both used to fan out to review-crawl via the SNS subscription. The inline helper must be wired at both call sites so we don't lose dispatch coverage.

Right after `_publish_crawl_app_events`:

```python
self._publish_crawl_app_events(appid, game_data, existing)
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
    if not self._config.REFRESH_REVIEWS_ENABLED:
        return

    new_rce = game_data.get("review_count_english", 0) or 0

    # Tier eligibility (matches find_due_reviews WHERE clause)
    if new_rce < self._config.REFRESH_TIER_B_REVIEW_COUNT:
        return  # tier C or below — no review refresh
    if game_data.get("coming_soon"):
        return  # no reviews to refresh until launch

    review_crawled_at = existing.get("review_crawled_at") if existing else None
    is_first_fetch = review_crawled_at is None
    if is_first_fetch:
        self._dispatch_review_crawl(appid)
        return

    last_fetch_rce = (existing.get("review_count_at_last_fetch") or 0)
    delta = new_rce - last_fetch_rce
    delta_met = delta >= self._config.REFRESH_REVIEWS_MIN_DELTA
    is_stale = (datetime.now(tz=timezone.utc) - review_crawled_at).days >= 30

    if delta_met or is_stale:
        self._dispatch_review_crawl(appid)

def _dispatch_review_crawl(self, appid: int) -> None:
    msg = ReviewCrawlMessage(appid=appid, source="refresh").model_dump()
    send_sqs_batch(self._sqs, self._review_queue_url, [msg])
    logger.info("inline_review_dispatch enqueued", extra={"appid": appid})
```

Notes:
- Reuses `existing` already loaded by `find_event_snapshot` — no extra DB call once #3 lands
- The delta is computed against `review_count_at_last_fetch` (the value at last review crawl, on `app_catalog`), **not** the pre-upsert `games.review_count_english`. This matches `find_due_reviews()` semantics — cumulative growth since last fetch, not per-ingest growth. Per-ingest delta would essentially never cross `REFRESH_REVIEWS_MIN_DELTA=1000`, leaving the gate effectively closed.
- Wired at both `crawl_app:172` and `ingest_spoke_metadata:269`

### 6. Delete `RefreshReviewsRule` — `infra/stacks/compute_stack.py:1089-1108` `[code]`

Remove `refresh_reviews_rule` and its `add_target` call entirely. Drop matching assertion in `tests/infra/test_compute_stack.py`.

The `refresh_reviews` action handler in the crawler Lambda stays intact — `sp.py refresh-reviews` operator path still routes through it.

### 7. Delete `ReviewCrawlSub` — `infra/stacks/messaging_stack.py:214-228` `[code]`

Remove the `CfnSubscription` (the SNS→SQS bridge for review crawls) AND the `self.review_crawl_queue.grant_send_messages(iam.ServicePrincipal("sns.amazonaws.com"))` line that supports it.

The `review_crawl_queue` itself stays — it's still fed by inline Python dispatch (CrawlerFn already has `grant_send_messages(crawler_role)`) and operator-triggered drains.

`_publish_crawl_app_events` continues to publish `GameMetadataReadyEvent`, `GameReleasedEvent`, `GamePriceChangedEvent` to `GameEventsTopic`. We're only removing the review-crawl routing of those events; the topic and any other subscribers keep working.

`GameUpdatedEvent`: leave the model definition for now (low cost, could be revived). Confirmed not published from any active code path.

Drop matching filter assertions in `tests/infra/test_messaging_stack.py:99-100` (the `game-released` / `game-updated` checks).

### 8. Tests — `tests/services/test_crawl_service.py` `[code]`

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

### 9. Update tiered-refresh docs — `tiered-refresh-schedule.org` and `ARCHITECTURE.org` `[doc]`

`tiered-refresh-schedule.org`:
- Remove the `RefreshReviewsRule` row from the cron table
- Note that review dispatch is inline from meta ingest, gated on `REFRESH_REVIEWS_ENABLED`
- Review tier intervals (`REFRESH_REVIEWS_TIER_*_DAYS`) only affect the operator-triggered `sp.py refresh-reviews` path now; not the steady-state pipeline

`ARCHITECTURE.org`:
- Update line 199 (review-crawl-queue subscription description) — remove the `["game-released","game-updated"]` filter mention
- Update meta-ingest sequence diagram to show inline dispatch instead of SNS routing

## Critical files

- `src/library-layer/library_layer/config.py` — add `REFRESH_REVIEWS_ENABLED`
- `.env`, `.env.example`, `.env.staging`, `.env.production` — wire the new field
- `src/library-layer/library_layer/repositories/game_repo.py:144-153` — extend `find_event_snapshot` SELECT
- `src/library-layer/library_layer/services/catalog_service.py` — add `enqueue_review_crawl_for_appids`
- `src/library-layer/library_layer/services/crawl_service.py:172,269` — call `_maybe_dispatch_review_crawl` from both `crawl_app` and `ingest_spoke_metadata`; add the helper
- `infra/stacks/compute_stack.py:1089-1108` — delete `RefreshReviewsRule`
- `infra/stacks/messaging_stack.py:214-228` — delete `ReviewCrawlSub` and the SNS service-principal grant
- `tests/services/test_crawl_service.py` — gate behavior tests
- `tests/infra/test_compute_stack.py` — drop `RefreshReviewsRule` assertion
- `tests/infra/test_messaging_stack.py:99-100` — drop `game-released`/`game-updated` filter assertions
- `tests/conftest.py`, `tests/test_config.py` — env wiring
- `tiered-refresh-schedule.org`, `ARCHITECTURE.org` — doc update

## Out of scope

- **Review tier-window config retirement** — `REFRESH_REVIEWS_TIER_S/A/B_DAYS` and the dispatcher-path `enqueue_refresh_reviews(limit=)` stay intact. Operator-triggered drain (`sp.py refresh-reviews`) still uses them. Revisit only if the operator path also gets eliminated.
- **Touching the metadata cron** — `RefreshMetaRule` cadence and `find_due_meta()` semantics unchanged.
- **Deleting `GameUpdatedEvent` model or the `GameReleasedEvent` publish site** — those still exist / publish to `GameEventsTopic`; we're only removing the review-crawl routing of them.
- **Backfill** — no migration needed. The 0055 migration already initialized `review_count_at_last_fetch` to current `review_count_english` for previously-fetched rows. Cold deploy: first meta pass per game observes delta=0 → no dispatch unless real growth has accrued.
- **Auto-redeploy on env-var flip** — operator flips `REFRESH_REVIEWS_ENABLED` via `aws lambda update-function-configuration` (or a `cdk deploy` with edited env file). Lambda re-inits within ~1 minute.

## Verification

### Local

```bash
poetry run pytest tests/services/test_crawl_service.py -k "maybe_dispatch_review_crawl" -v
poetry run pytest tests/  # full suite, --no-mock policy applies (feedback_test_db)
```

### Pre-deploy sanity

`cdk diff` should show exactly two infra changes:
1. `RefreshReviewsRule` removed
2. `ReviewCrawlSub` removed (and its SNS service-principal grant)

If anything else changed, investigate before deploying.

### Post-deploy (24–48h after enabling, with `REFRESH_REVIEWS_ENABLED=true`)

```bash
# 1. Confirm RefreshReviewsRule is gone
aws events list-rules --name-prefix Refresh --region us-west-2 --output table
# Expect: only RefreshMetaRule (and CatalogRefresh)

# 2. Confirm ReviewCrawlSub is gone
aws sns list-subscriptions-by-topic \
  --topic-arn $(aws ssm get-parameter --name /steampulse/production/messaging/game-events-topic-arn --query Parameter.Value --output text --region us-west-2) \
  --region us-west-2 --output table
# Expect: no subscription pointing at review_crawl_queue

# 3. Confirm review-crawl queue is being fed by inline dispatch
aws cloudwatch get-metric-statistics --namespace AWS/SQS --metric-name NumberOfMessagesSent \
  --dimensions Name=QueueName,Value=steampulse-review-crawl-production \
  --start-time $(date -v-2d -u +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 3600 --statistics Sum --region us-west-2
# Pattern should track meta-ingest hour, with delta gating ⇒ much lower volume than the prior ungated SNS path

# 4. Grep CrawlerFn logs for the new event
poetry run python scripts/logs.py crawler --env production --grep inline_review_dispatch
```

### Kill-switch validation

In a quiet hour, flip the var off and confirm dispatches stop:

```bash
aws lambda update-function-configuration \
  --function-name SteamPulse-Production-Compute-CrawlerFn518AFFDE-bOATzXaXrnJG \
  --environment "Variables={...,REFRESH_REVIEWS_ENABLED=false}" \
  --region us-west-2

# Wait one meta cycle (1 hour). Confirm no new inline_review_dispatch log lines:
poetry run python scripts/logs.py crawler --env production --grep inline_review_dispatch --since 1h
# Expect: zero matches
```

Then flip it back on (or `cdk deploy` to restore from `.env.production`).
