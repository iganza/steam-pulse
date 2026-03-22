# Spoke Pydantic Models — Type-Safe Crawler Payloads

## Problem

The spoke dispatcher, spoke handler, and ingest handler all pass payloads as
raw dicts with bare string task values (`"metadata"`, `"reviews"`). This means:

- No validation at boundaries — a typo like `"review"` silently passes through
- Task type scattered as magic strings across 3 files
- No model reuse — each handler re-parses keys manually

The **direct invocation** path already uses proper Pydantic models in `events.py`
(`CrawlAppsRequest`, `CrawlReviewsRequest`, etc.). The spoke path should follow
the same pattern.

## Goal

Add Pydantic models for the three spoke contracts and a shared `CrawlTask` type
to `events.py`. Then wire them into the three handlers so payloads are validated
at every boundary. Follow the existing patterns in `events.py` exactly.

## Changes

### 1. `src/lambda-functions/lambda_functions/crawler/events.py`

Add the following **below** the existing `DirectRequest` union, keeping all
existing code untouched:

```python
# ── Spoke payload contracts ─────────────────────────────────────────────────

CrawlTask = Literal["metadata", "reviews"]


class SpokeRequest(BaseModel):
    """Primary → Spoke: async Lambda invoke payload."""
    appid: int
    task: CrawlTask


class SpokeResult(BaseModel):
    """Spoke → Primary: SQS message body in spoke-results queue."""
    appid: int
    task: CrawlTask
    s3_key: str | None
    count: int
    spoke_region: str


class SpokeResponse(BaseModel):
    """Spoke Lambda return value (logged by Lambda, useful for debugging)."""
    appid: int
    task: CrawlTask
    success: bool
    count: int
```

### 2. `src/lambda-functions/lambda_functions/crawler/handler.py`

In `_dispatch_to_spoke()`:

**Before (raw dict):**
```python
source_arn = record.get("eventSourceARN", "")
if "review-crawl" in source_arn:
    task = "reviews"
else:
    task = "metadata"
...
Payload=json.dumps({"appid": appid, "task": task}).encode(),
```

**After (model):**
```python
from .events import SpokeRequest

source_arn = record.get("eventSourceARN", "")
task: CrawlTask = "reviews" if "review-crawl" in source_arn else "metadata"

req = SpokeRequest(appid=appid, task=task)
...
Payload=req.model_dump_json().encode(),
```

Import `CrawlTask` and `SpokeRequest` from `.events` at the top of the file
(add to the existing `from .events import ...` statement).

### 3. `src/lambda-functions/lambda_functions/crawler/spoke_handler.py`

**Entry point — validate incoming payload:**

**Before:**
```python
def handler(event: dict, context: LambdaContext) -> dict:
    appid = int(event["appid"])
    task = event["task"]
```

**After:**
```python
from lambda_functions.crawler.events import SpokeRequest, SpokeResponse, SpokeResult

def handler(event: dict, context: LambdaContext) -> dict:
    req = SpokeRequest.model_validate(event)
    appid = req.appid
    task = req.task
```

**Return values — use SpokeResponse:**

Replace the two return dicts:
```python
return {"appid": appid, "task": task, "success": ok, "count": 1 if ok else 0}
```
with:
```python
return SpokeResponse(appid=appid, task=task, success=ok, count=1 if ok else 0).model_dump()
```
Same for the reviews return.

**`_notify()` — use SpokeResult:**

**Before:**
```python
def _notify(appid: int, task: str, s3_key: str | None, count: int) -> None:
    _sqs.send_message(
        QueueUrl=_SPOKE_RESULTS_QUEUE_URL,
        MessageBody=json.dumps({
            "appid": appid,
            "task": task,
            "s3_key": s3_key,
            "count": count,
            "spoke_region": os.environ.get("AWS_REGION", "unknown"),
        }),
    )
```

**After:**
```python
def _notify(appid: int, task: CrawlTask, s3_key: str | None, count: int) -> None:
    msg = SpokeResult(
        appid=appid,
        task=task,
        s3_key=s3_key,
        count=count,
        spoke_region=os.environ.get("AWS_REGION", "unknown"),
    )
    _sqs.send_message(
        QueueUrl=_SPOKE_RESULTS_QUEUE_URL,
        MessageBody=msg.model_dump_json(),
    )
```

Import `CrawlTask`, `SpokeRequest`, `SpokeResponse`, `SpokeResult` from
`lambda_functions.crawler.events`. Update the type annotation on `task`
parameters throughout the file from `str` to `CrawlTask`.

### 4. `src/lambda-functions/lambda_functions/crawler/ingest_handler.py`

**`_ingest_record()` — validate with SpokeResult:**

**Before:**
```python
def _ingest_record(record: dict) -> None:
    body = json.loads(record["body"])
    appid = int(body["appid"])
    task: str = body["task"]
    s3_key: str | None = body.get("s3_key")
    count = int(body.get("count", 0))
```

**After:**
```python
from lambda_functions.crawler.events import SpokeResult

def _ingest_record(record: dict) -> None:
    msg = SpokeResult.model_validate_json(record["body"])
    appid = msg.appid
    task = msg.task
    s3_key = msg.s3_key
    count = msg.count
```

The rest of `_ingest_record` stays the same — it already branches on
`task == "metadata"` / `task == "reviews"`.

### 5. Tests — update to use models

**`tests/handlers/test_spoke_handler.py`:**
- Import `SpokeRequest` and use `SpokeRequest(appid=440, task="metadata").model_dump()`
  instead of raw `{"appid": 440, "task": "metadata"}` dicts in test event construction.
- Assertions on return values can validate against `SpokeResponse`.

**`tests/handlers/test_crawler_handler.py`:**
- In tests that verify `_dispatch_to_spoke`, assert the `Payload` kwarg
  deserializes to a valid `SpokeRequest`.

**`tests/handlers/test_ingest_handler.py`:**
- Use `SpokeResult(...).model_dump_json()` to construct the SQS record body
  instead of raw `json.dumps({"appid": ...})`.

## Rules

- Do NOT modify any existing model in `events.py` — only add new ones below.
- `CrawlTask` is a module-level type alias, not a class. Place it above the
  spoke models so they can reference it.
- Use `model_dump_json()` for JSON serialization (not `json.dumps(model.model_dump())`).
- Use `model_validate()` for dict input, `model_validate_json()` for string input.
- All function signatures that accept `task` should be typed as `CrawlTask`, not `str`.
- Run `poetry run pytest -v` — all tests must pass.
- Run `poetry run ruff check . && poetry run ruff format .` — no lint errors.
