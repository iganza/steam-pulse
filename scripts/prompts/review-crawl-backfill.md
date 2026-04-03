# Plan: Review Crawl Backfill Scheduling

## Context

The current review crawl is purely event-driven: `game-metadata-ready` → SNS filter → `ReviewCrawlQ`. This fires once per game, at metadata-ingest time. Problems:

1. Games that are newly released or have few reviews at ingest time get `is_eligible=false` and are **never re-evaluated**
2. No ordering — games are processed in discovery order, not by relevance/recency
3. `sp.py` has two dead functions referencing dropped columns: `_eligible_reviews()` uses `find_pending_reviews()` (gone), and `_ready_for_analysis()` uses `review_status = 'done'` (dropped in migration 0007)

**Goal:** Add a periodic "backfill" that finds all eligible uncrawled games ordered by `release_date DESC` (recent games first, going backwards in time) and enqueues them. Keep the SNS immediate trigger — the two paths are complementary.

---

## Design

**Don't change:** SNS-driven immediate trigger (`game-metadata-ready → reviews`). Correct for established games.

**Add:** A `review_backfill` action on `CrawlerFn` + daily EventBridge rule. No new Lambda, queue, topic, or IAM role needed.

**Backfill query:** Eligible (`meta_status='done'`, `coming_soon=false`, `review_count_english >= threshold`, `release_date IS NOT NULL`) + uncrawled (`review_cursor IS NULL AND reviews_completed_at IS NULL`), ordered by `release_date DESC LIMIT N`.

**Re-crawl scheduling** (games already crawled that need refresh): out of scope — separate design.

---

## Files to Change

### 1. Migration `0008_add_backfill_index.sql` (NEW)
`src/lambda-functions/migrations/0008_add_backfill_index.sql`

```sql
-- depends: 0007_review_catalog_refactor
-- transactional: false

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_app_catalog_backfill
    ON app_catalog (meta_status, review_cursor, reviews_completed_at)
    WHERE meta_status = 'done'
      AND review_cursor IS NULL
      AND reviews_completed_at IS NULL;
```

Partial index — after the full initial backfill completes it shrinks toward zero rows.

---

### 2. `library_layer/utils/events.py` (NEW FILE)
`src/library-layer/library_layer/utils/events.py`

Shared Pydantic models for queue message payloads — usable from both library-layer services and lambda handlers.

```python
"""Pydantic models for shared SQS queue message payloads."""

from pydantic import BaseModel


class ReviewCrawlMessage(BaseModel):
    """Message body for ReviewCrawlQ: instructs CrawlerFn to dispatch a review crawl."""
    appid: int
```

---

### 3. `catalog_repo.py` — add `find_uncrawled_eligible()`
`src/library-layer/library_layer/repositories/catalog_repo.py`

`_fetchall` uses positional `%s` params (tuple). JOIN to `games` for eligibility + release-date ordering.

```python
def find_uncrawled_eligible(self, threshold: int, limit: int) -> list[int]:
    """Appids ready for first review crawl, ordered newest-released first."""
    rows = self._fetchall(
        """
        SELECT ac.appid
        FROM app_catalog ac
        JOIN games g ON g.appid = ac.appid
        WHERE ac.meta_status = 'done'
          AND ac.review_cursor IS NULL
          AND ac.reviews_completed_at IS NULL
          AND g.coming_soon = false
          AND g.review_count_english >= %s
          AND g.release_date IS NOT NULL
        ORDER BY g.release_date DESC
        LIMIT %s
        """,
        (threshold, limit),
    )
    return [row["appid"] for row in rows]
```

---

### 4. `catalog_service.py` — add `review_queue_url` param + `enqueue_review_backfill()`
`src/library-layer/library_layer/services/catalog_service.py`

Add `review_queue_url: str` to `__init__` (store as `self._review_queue_url`). Import `ReviewCrawlMessage`.

```python
def enqueue_review_backfill(self, limit: int) -> int:
    """Find uncrawled eligible games (newest first) and enqueue for review crawl."""
    threshold = self._config.REVIEW_ELIGIBILITY_THRESHOLD
    appids = self._catalog_repo.find_uncrawled_eligible(threshold, limit)
    if not appids:
        logger.info("No uncrawled eligible games for review backfill")
        return 0
    # model_dump() → dict: send_sqs_batch calls json.dumps() on each dict internally
    send_sqs_batch(
        self._sqs,
        self._review_queue_url,
        [ReviewCrawlMessage(appid=a).model_dump() for a in appids],
    )
    logger.info("Review backfill enqueued", extra={"count": len(appids), "limit": limit})
    return len(appids)
```

---

### 5. `crawler/ingest_handler.py` — use `ReviewCrawlMessage` for re-queue
`src/lambda-functions/lambda_functions/crawler/ingest_handler.py`

Replace raw `json.dumps({"appid": appid})` with the model:

```python
from library_layer.utils.events import ReviewCrawlMessage
# ...
# model_dump_json() → str: send_message(MessageBody=) expects a string directly
_sqs.send_message(
    QueueUrl=_review_crawl_queue_url,
    MessageBody=ReviewCrawlMessage(appid=appid).model_dump_json(),
)
```

---

### 6. `crawler/events.py` — add `ReviewBackfillRequest`
`src/lambda-functions/lambda_functions/crawler/events.py`

```python
class ReviewBackfillRequest(BaseModel):
    action: Literal["review_backfill"]
    limit: int = 1000
```

Extend the `DirectRequest` discriminated union to include `ReviewBackfillRequest`.

---

### 7. `crawler/handler.py` — wire backfill
`src/lambda-functions/lambda_functions/crawler/handler.py`

- Pass `review_queue_url=_review_queue_url` to `CatalogService(...)` (already resolved at cold start)
- Import `ReviewBackfillRequest` from events
- Add match case in the action dispatcher:

```python
case ReviewBackfillRequest():
    n = _catalog_service.enqueue_review_backfill(req.limit)
    logger.info("review_backfill complete", extra={"enqueued": n, "limit": req.limit})
    return {"enqueued": n, "limit": req.limit}
```

---

### 8. `infra/stacks/compute_stack.py` — add EventBridge rule

After the existing `catalog_rule` block:

```python
review_backfill_rule = events.Rule(
    self, "ReviewBackfillRule",
    schedule=events.Schedule.rate(cdk.Duration.days(1)),
    enabled=True,
)
review_backfill_rule.add_target(
    events_targets.LambdaFunction(
        crawler_fn,
        event=events.RuleTargetInput.from_object(
            {"action": "review_backfill", "limit": 1000}
        ),
    )
)
```

`RuleTargetInput.from_object` replaces the entire payload — no `source: "aws.events"` field so `handler.py`'s `"action" in event` branch handles it. CDK auto-grants EventBridge invoke permission.

---

### 9. `scripts/sp.py` — fix two dead functions

**Fix `_eligible_reviews()`** (line ~406):

```python
def _eligible_reviews(n: int) -> list[int]:
    conn, _, catalog_repo, _, _ = _get_repos()
    try:
        return catalog_repo.find_uncrawled_eligible(threshold=50, limit=n)
    finally:
        conn.close()
```

**Fix `_ready_for_analysis()`** (line ~415) — replaces dead `review_status = 'done'`:

```python
def _ready_for_analysis(n: int = 1000) -> list[int]:
    with psycopg2.connect(DB_URL) as c, c.cursor() as cur:
        cur.execute(
            """SELECT g.appid FROM games g
               JOIN app_catalog ac ON ac.appid = g.appid
               WHERE ac.reviews_completed_at IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM reports r WHERE r.appid = g.appid)
               ORDER BY g.review_count DESC NULLS LAST LIMIT %s""",
            (n,),
        )
        return [row[0] for row in cur.fetchall()]
```

---

### 10. `schema.py` — add index to INDEXES tuple
`src/library-layer/library_layer/schema.py`

Add `"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_app_catalog_backfill ..."` to the `INDEXES` tuple for test-suite awareness.

---

## Implementation Order

1. Migration `0008`
2. `library_layer/utils/events.py` — `ReviewCrawlMessage`
3. `catalog_repo.py` — `find_uncrawled_eligible()`
4. `catalog_service.py` — `review_queue_url` param + `enqueue_review_backfill()`
5. `ingest_handler.py` — use `ReviewCrawlMessage` for re-queue
6. `crawler/events.py` — `ReviewBackfillRequest`
7. `handler.py` — wire it in
8. `compute_stack.py` — EventBridge rule
9. `sp.py` — fix dead functions
10. `schema.py` — index tuple

---

## Verification

```bash
# Apply migration to test DB
poetry run yoyo apply \
  --database "postgresql://steampulse:dev@127.0.0.1:5432/steampulse_test" \
  --no-config-file --batch src/lambda-functions/migrations

# Unit tests
poetry run pytest tests/repositories/test_catalog_repo.py tests/services/ tests/handlers/ -v

# CDK diff (infra only)
poetry run cdk diff SteamPulsePipeline/Staging/Compute
```
