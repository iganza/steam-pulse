# Accelerated review re-crawl for just-released post-EA games

## Context

When a game transitions from Early Access to full release (`coming_soon` flips
`true → false`), `CrawlService._publish_crawl_app_events` publishes a single
`GameReleasedEvent` (`src/library-layer/library_layer/services/crawl_service.py:473-486`).
The SNS `$or` filter on the review-crawl-queue
(`infra/stacks/messaging_stack.py:179-191`) routes it to the review crawler unconditionally,
triggering **one** full review crawl.

After that single crawl:
- The row is stamped `reviews_completed_at = NOW()` (`ingest_handler.py:257-290`).
- No further review crawl fires until either (a) the English review count crosses
  `REVIEW_ELIGIBILITY_THRESHOLD=50` on a metadata re-crawl, or (b) another
  `GameReleasedEvent` fires (it won't — `coming_soon` has already flipped).
- Metadata re-crawls run on the daily stale-refresh rule at 30-day cadence for Tier 3
  games (< 1000 reviews).

**The gap**: a post-EA game that leaves Early Access with, say, 8 reviews (all EA) may
accumulate its next 20–50 post-release reviews over the following weeks, but SteamPulse
won't re-pull them until the 30-day metadata window expires AND the English count
crosses 50. The post-release sentiment number
(`positive_pct_post_release` / `review_count_post_release` added in
`split-ea-post-release-reviews.md`) stays pinned at whatever was captured in the first
crawl — often `NULL` or `0` — for weeks, which undermines the entire point of that
change.

This prompt adds a short-lived **accelerated re-crawl window** for recently-released
post-EA games so post-release review data materialises promptly.

## Scope

Add a daily EventBridge rule that enqueues a review crawl for every game meeting:

```
coming_soon = FALSE
AND has_early_access_reviews = TRUE
AND release_date IS NOT NULL
AND release_date >= CURRENT_DATE - INTERVAL '30 days'
```

Bounds: 30-day window. After that, normal stale-refresh cadence resumes. Cap the batch
at 500 appids per run (the typical post-EA release cadence is small — most days will
enqueue a handful).

No changes to the EA→release detection (`GameReleasedEvent` stays single-fire). This
layer sits **alongside** it.

## Approach

### 1. New repository method

In `src/library-layer/library_layer/repositories/catalog_repo.py` add:

```python
def find_recently_released_post_ea(self, *, window_days: int, limit: int) -> list[CatalogEntry]:
    """Games that released within the last `window_days` after an EA phase.

    Used by the accelerated-review-recrawl daily rule: these are the games whose
    post-release review sentiment is still materialising and that stale-refresh
    won't touch for weeks.
    """
    rows = self._fetchall(
        """
        SELECT c.appid, c.name, c.meta_status, c.meta_crawled_at, c.tags_crawled_at,
               c.reviews_completed_at, c.review_count
          FROM app_catalog c
          JOIN games g ON g.appid = c.appid
         WHERE g.coming_soon = FALSE
           AND g.has_early_access_reviews = TRUE
           AND g.release_date IS NOT NULL
           AND g.release_date >= CURRENT_DATE - make_interval(days => %s)
         ORDER BY g.release_date DESC
         LIMIT %s
        """,
        (window_days, limit),
    )
    return [CatalogEntry(**r) for r in rows]
```

Supporting index migration (optional but recommended — a partial index on the
qualifying rows keeps this query cheap as the catalog grows):

```sql
-- depends: <latest>
-- transactional: false
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_games_recent_post_ea
    ON games (release_date DESC)
    WHERE coming_soon = FALSE AND has_early_access_reviews = TRUE;
```

### 2. New service method

In `src/library-layer/library_layer/services/catalog_service.py` add (mirroring
`enqueue_stale`):

```python
def enqueue_post_ea_refresh(self, *, window_days: int, limit: int) -> int:
    games = self._catalog_repo.find_recently_released_post_ea(
        window_days=window_days, limit=limit,
    )
    if not games:
        logger.info("No recently-released post-EA games to re-crawl")
        return 0
    messages = [{"appid": g.appid, "task": "reviews"} for g in games]
    send_sqs_batch(self._sqs, self._review_crawl_queue_url, messages)
    logger.info(
        "Post-EA accelerated re-crawl enqueued",
        extra={"appids": len(games), "window_days": window_days},
    )
    return len(games)
```

Note — queue URL: the review-crawl-queue URL. `CatalogService` doesn't currently hold
it; either inject it via constructor (prefer this — same pattern as
`app_crawl_queue_url`) or place this method on `CrawlService` which already has
`_review_queue_url`. Choose whichever keeps service-layer responsibilities clean
(catalog service already owns `enqueue_pending` / `enqueue_stale`, so the natural home
is `CatalogService` with a new constructor dep).

### 3. Handler action

In `src/lambda-functions/lambda_functions/crawler/events.py` add a new Pydantic request
type:

```python
class PostEaRefreshRequest(BaseModel):
    action: Literal["post_ea_refresh"]
    window_days: int = 30
    limit: int = 500
```

Extend `DirectRequest` union. In `crawler/handler.py` add a `case`:

```python
case PostEaRefreshRequest():
    count = _catalog_service.enqueue_post_ea_refresh(
        window_days=req.window_days, limit=req.limit,
    )
    metrics.add_metric(name="PostEaRefreshEnqueued", unit=MetricUnit.Count, value=count)
    return {"post_ea_enqueued": count}
```

### 4. EventBridge rule

In `infra/stacks/compute_stack.py` alongside `CatalogRefreshRule` and
`StaleMetaRefreshRule`:

```python
post_ea_rule = events.Rule(
    self,
    "PostEaAcceleratedRecrawlRule",
    schedule=events.Schedule.rate(cdk.Duration.days(1)),
    enabled=True,
)
post_ea_rule.add_target(
    events_targets.LambdaFunction(
        crawler_fn,
        event=events.RuleTargetInput.from_object(
            {"action": "post_ea_refresh", "window_days": 30, "limit": 500}
        ),
    )
)
```

### 5. Early-stop interaction

The review-crawl path already uses `reviews_completed_at` as a watermark and stops early
once the spoke batch predates the watermark (`ingest_handler.py:239-290`). That means a
daily accelerated re-crawl is cheap — Steam returns reviews newest-first, and we only
ingest truly-new reviews. No new logic needed for this.

### 6. Metrics & observability

Add `PostEaRefreshEnqueued` to the monitoring stack's existing "crawler counters"
dashboard panel (see `infra/stacks/monitoring_stack.py`). No alarm — this is
low-throughput.

## Files to modify / create

- `src/library-layer/library_layer/repositories/catalog_repo.py` — new finder
- `src/library-layer/library_layer/services/catalog_service.py` — new service method
  + constructor dep (review-crawl-queue URL)
- `src/lambda-functions/lambda_functions/crawler/events.py` — `PostEaRefreshRequest`
- `src/lambda-functions/lambda_functions/crawler/handler.py` — dispatcher case + wire
  the new constructor dep
- `infra/stacks/compute_stack.py` — new EventBridge rule
- `infra/stacks/monitoring_stack.py` — new metric in the crawler panel
- `src/lambda-functions/migrations/00NN_post_ea_recrawl_index.sql` — partial index
- `tests/repositories/test_catalog_repo.py` — test the new finder on
  `steampulse_test`
- `tests/services/test_catalog_service.py` — test `enqueue_post_ea_refresh`
  (mock SQS, assert messages)
- `tests/handlers/test_crawler_handler.py` — test the new action
- `tests/infra/test_compute_stack.py` — assert the new rule exists

## Verification

- Local: run the catalog-repo test with a seeded game
  (`release_date=CURRENT_DATE - 5 days`, `has_early_access_reviews=TRUE`,
  `coming_soon=FALSE`) and verify it's returned.
- Staging: after deploy, direct-invoke the handler with
  `{"action": "post_ea_refresh", "window_days": 30, "limit": 10}` and confirm SQS
  messages land on the review-crawl queue (`aws sqs receive-message ...`).
- Observe `PostEaRefreshEnqueued` metric rise daily in CloudWatch.
- After 1–2 days on staging, confirm a post-EA game gains new
  `review_count_post_release` / `positive_pct_post_release` values without waiting
  for the 30-day stale-refresh cycle.
