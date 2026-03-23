# Plan: Chunked Review Fetching with Cursor Persistence

## Context
The spoke handler currently fetches all reviews into memory in one Lambda invocation (`max_reviews=None`).
For large games this times out. The fix is cursor-based chunked fetching with a single unified flow:

- **Initial seed**: fetch first 5000 reviews per game (5 batches of 1000), stop — analysis is a separate phase
- **Full mining**: re-queue same game later with no cap → loads saved cursor → continues from position 5001

Same code, same queues, same spoke, same ingest. `max_reviews` is a stopping point, not a separate path.
`filter=all` throughout (helpfulness-sorted, better for LLM analysis, cursor compatible across both phases).

---

## Files to Modify

| File | Change |
|---|---|
| `src/library-layer/library_layer/schema.py` | Add `review_cursor` + `review_cursor_updated_at` to `app_catalog` |
| `src/library-layer/library_layer/repositories/catalog_repo.py` | Add `get_review_cursor`, `save_review_cursor`, `clear_review_cursor` |
| `src/library-layer/library_layer/steam_source.py` | Add `start_cursor` param to `get_reviews`; return `(reviews, next_cursor)` tuple |
| `src/lambda-functions/lambda_functions/crawler/events.py` | Add `cursor`, `max_reviews` to `SpokeRequest`; add `next_cursor` to `SpokeResult` |
| `src/lambda-functions/lambda_functions/crawler/spoke_handler.py` | Fetch one batch (1000), return next cursor |
| `src/lambda-functions/lambda_functions/crawler/ingest_handler.py` | Save cursor + re-queue via review-crawl SQS if more remain AND max_reviews not yet hit |
| `src/lambda-functions/lambda_functions/crawler/handler.py` | Coordinator: load saved cursor from DB, pass explicit `max_reviews` from SQS body |
| `scripts/sp.py` | Add `--max-reviews` arg to `queue reviews` subcommand |

---

## Plan

### 1. Schema — add cursor state to `app_catalog`

In `schema.py`, add to the `app_catalog` CREATE TABLE:
```sql
review_cursor             TEXT,
review_cursor_updated_at  TIMESTAMPTZ,
reviews_target            INT          -- NULL = fetch all; N = stop after N total
```

`review_cursor = NULL` → not started, use `"*"`.
`review_cursor = ''` → exhausted, all reviews fetched.
`reviews_target` → persisted so the ingest chain knows when to stop and trigger analysis.

### 2. `CatalogRepository` — cursor methods

Add to `catalog_repo.py`:
```python
def get_review_cursor(self, appid: int) -> str | None
    # None = not started

def save_review_cursor(self, appid: int, cursor: str) -> None
    # Saves cursor + timestamp

def clear_review_cursor(self, appid: int) -> None
    # Sets cursor = '' (exhausted)

def get_reviews_target(self, appid: int) -> int | None
    # Returns reviews_target (None = fetch all)

def set_reviews_target(self, appid: int, target: int | None) -> None
```

### 3. `steam_source.get_reviews` — add `start_cursor`, return tuple

```python
def get_reviews(
    self,
    appid: int,
    max_reviews: int | None = None,
    start_cursor: str = "*",
) -> tuple[list[dict], str | None]:
```

- Loop starts from `start_cursor` instead of hardcoded `"*"`
- Returns `(reviews, next_cursor)` — `next_cursor` is `None` when Steam returns no more pages
- `max_reviews` caps this batch only (not the total across all batches)

Update callers:
- `crawl_service.crawl_reviews` — unpack tuple, discard cursor (local dev path, no persistence needed)
- `spoke_handler._process_reviews` — use both values

### 4. `events.py` — typed task enum + task-specific spoke models

```python
CrawlTask = Literal["metadata", "reviews"]  # type alias, unchanged

# ── Spoke request models (Primary → Spoke) ──────────────────────────────────

class MetadataSpokeRequest(BaseModel):
    appid: int
    task: CrawlTask = "metadata"

class ReviewSpokeRequest(BaseModel):
    appid: int
    task: CrawlTask = "reviews"
    cursor: str = "*"
    max_reviews: int | None = None  # None = use BATCH_SIZE

# ── Spoke result models (Spoke → Ingest via SQS) ────────────────────────────

class MetadataSpokeResult(BaseModel):
    appid: int
    task: CrawlTask = "metadata"
    success: bool
    s3_key: str | None = None
    count: int = 0
    spoke_region: str
    error: str | None = None

class ReviewSpokeResult(BaseModel):
    appid: int
    task: CrawlTask = "reviews"
    success: bool
    s3_key: str | None = None
    count: int = 0
    spoke_region: str
    next_cursor: str | None = None  # None = Steam exhausted
    error: str | None = None
```

Ingest handler routes on `msg.task` value (`"metadata"` vs `"reviews"`). Update all references across handler.py, spoke_handler.py, ingest_handler.py.

### 5. `spoke_handler.py` — one batch per invocation

```python
BATCH_SIZE = 1000

def _process_reviews(appid: int, cursor: str, max_reviews: int | None) -> tuple[int, str | None]:
    limit = min(max_reviews, BATCH_SIZE) if max_reviews is not None else BATCH_SIZE
    reviews, next_cursor = _steam.get_reviews(appid, max_reviews=limit, start_cursor=cursor)
    if not reviews:
        _notify(appid, task="reviews", success=False, error="no reviews returned", next_cursor=None)
        return 0, None
    uid = uuid.uuid4().hex[:12]
    s3_key = _write_s3(f"spoke-results/reviews/{appid}-{uid}.json.gz", reviews)
    _notify(appid, task="reviews", success=True, s3_key=s3_key, count=len(reviews), next_cursor=next_cursor)
    return len(reviews), next_cursor
```

`handler` passes `req.cursor` and `req.max_reviews` into `_process_reviews`.

### 6. `ingest_handler.py` — save cursor, re-queue via SQS, stop when target hit

After `ingest_spoke_reviews`:

```python
if msg.task == "reviews":
    upserted = _crawl_service.ingest_spoke_reviews(appid, data)

    total_fetched = _review_repo.count_by_appid(appid)
    target = _catalog_repo.get_reviews_target(appid)
    target_hit = target is not None and total_fetched >= target
    exhausted = msg.next_cursor is None

    if exhausted or target_hit:
        # Done for this run — save cursor state and stop.
        if exhausted:
            _catalog_repo.clear_review_cursor(appid)       # '' = fully done
        else:
            _catalog_repo.save_review_cursor(appid, msg.next_cursor)  # resume later
    else:
        # More to fetch — save cursor and re-queue via review-crawl SQS
        _catalog_repo.save_review_cursor(appid, msg.next_cursor)
        _sqs.send_message(
            QueueUrl=_review_crawl_queue_url,
            MessageBody=json.dumps({"appid": appid}),
        )
        # handler._dispatch_to_spoke will load the cursor from DB on next pickup
```

Ingest handler gains:
- `_catalog_repo = CatalogRepository(_conn)` at module level
- `_review_repo = ReviewRepository(_conn)` at module level
- `_review_crawl_queue_url` resolved via SSM at cold start (same pattern as other params)

### 7. `handler._dispatch_to_spoke` — coordinator loads cursor, passes explicit max_reviews

SQS message body now includes optional `max_reviews`:
```json
{"appid": 1086940, "max_reviews": 5000}
```

Handler reads it and passes straight through:
```python
def _dispatch_to_spoke(record: dict) -> None:
    body = _extract_payload(record["body"])
    appid = int(body["appid"])
    max_reviews = body.get("max_reviews")  # None = fetch all

    if task == "reviews":
        cursor = _catalog_repo.get_review_cursor(appid) or "*"
        # On fresh start, persist the target so ingest chain knows when to stop
        if cursor == "*" and max_reviews is not None:
            _catalog_repo.set_reviews_target(appid, max_reviews)
    else:
        cursor = "*"

    req = SpokeRequest(appid=appid, task=task, cursor=cursor, max_reviews=max_reviews)
    ...
```

`_catalog_repo` added at module level in `handler.py`.

### 8. `sp.py queue reviews` — add `--max-reviews` argument

```bash
poetry run python scripts/sp.py queue --env staging reviews 1086940 --max-reviews 5000
# No flag = fetch all
poetry run python scripts/sp.py queue --env staging reviews 1086940
```

SQS message body includes `max_reviews` only when explicitly passed.

---

## How the two phases work (same code, different `max_reviews`)

**Initial seed (500 games, 5000 reviews each):**
```bash
# sp.py queue reviews sends appid to review-crawl SQS
# handler sets reviews_target=5000 in DB when it sees a fresh cursor ("*")
poetry run python scripts/sp.py queue --env staging reviews 1086940 --max-reviews 5000
```

The chain runs 5 batches → hits target → saves cursor at position 5000 → stops.

**Full mining (later, same game):**
```bash
# Re-queue same appid — handler loads saved cursor from DB (position 5000)
# No target set this time → fetches until Steam exhausted
poetry run python scripts/sp.py queue --env staging reviews 1086940
```

Picks up at position 5001 → runs to completion.

---

## Batch size rationale

- **1000 reviews per batch** = 10 Steam API calls, ~20-30s per spoke invocation
- BG3 (437k reviews): ~437 chained batches total; first 5 batches in ~2-3 min for analysis
- Chain re-queues via SQS (seconds between hops) — no Lambda-to-Lambda coupling

---

## Verification

```bash
# Run schema migration locally
./scripts/dev/start-local.sh

# Queue a game and watch all 3 log streams
poetry run python scripts/sp.py queue --env staging reviews 1086940

aws logs tail SteamPulse-Staging-Compute-CrawlerLogsD758F63D-AGAss5mlw2Zr --follow --format short
aws logs tail SteamPulse-Staging-Spoke-us-west-2-SpokeLogs2BA0131C-fp08B3pXamUB --follow --format short
aws logs tail SteamPulse-Staging-Compute-SpokeIngestLogs0861E40A-Oe1XZQxhwcKr --follow --format short

# After 5 batches: verify cursor saved and reviews in DB
poetry run python scripts/sp.py db query \
  "SELECT appid, review_cursor, reviews_target, review_cursor_updated_at FROM app_catalog WHERE appid=1086940" \
  --env staging

poetry run python scripts/sp.py db query \
  "SELECT COUNT(*) FROM reviews WHERE appid=1086940" \
  --env staging
```
