# Task: Implement Test Suite with moto + Steam API Fixtures

Read `CLAUDE.md` before starting.

## Goal

Build a proper test suite for the three Lambda handlers using:
- **`moto`** — mock AWS services (SQS, Secrets Manager, Step Functions)
- **`pytest-httpx`** — mock HTTP calls to Steam/SteamSpy APIs
- **Real captured API responses** as JSON fixtures (no live HTTP in tests)
- **`pytest-asyncio`** — already in dev deps, for async handlers
- **Local in-memory Postgres** via `pytest-postgresql` or a simple SQLite shim — see note below on DB approach

## Install New Dev Dependencies

```bash
poetry add --group dev moto[sqs,secretsmanager,stepfunctions] pytest-httpx
```

## Fixture Files

Create `tests/fixtures/` with real captured JSON responses:

### `tests/fixtures/steam_appdetails_440.json`
Steam Store API response for TF2 (appid 440). Truncate `detailed_description` and
`about_the_game` to 200 chars to keep the file small. Must have these fields intact:
`name`, `steam_appid`, `is_free`, `developers`, `publishers`, `release_date`,
`price_overview`, `short_description`, `genres`, `categories`, `header_image`.

Real URL: `https://store.steampowered.com/api/appdetails?appids=440&cc=us&l=en`
The response is wrapped: `{"440": {"success": true, "data": {...}}}`
The handler calls `steam.get_app_details(appid)` which returns just the `data` dict —
check `src/library-layer/library_layer/steam_source.py` to confirm what the method returns.

### `tests/fixtures/steamspy_appinfo_440.json`
SteamSpy response for TF2. Real URL: `https://steamspy.com/api.php?request=appinfo&appid=440`
Must have: `appid`, `name`, `positive`, `negative`, `average_forever`, `median_forever`,
`owners`, `tags` (dict of tag→count).

### `tests/fixtures/steam_reviews_440.json`
Steam reviews API response. Real URL:
`https://store.steampowered.com/appreviews/440?json=1&num_per_page=5&language=english&review_type=all&purchase_type=all`
Must have: `success`, `query_summary` (with `total_positive`, `total_negative`,
`total_reviews`), `reviews` array with at least 3 review objects each having:
`recommendationid`, `author.steamid`, `review`, `timestamp_created`, `voted_up`,
`playtime_at_review`.

## DB Approach for Tests

The handlers use `psycopg2` to write to Postgres. For tests, **do not use a real DB**.
Instead, mock the DB at the connection level using `unittest.mock.patch` on
`psycopg2.connect` — return a `MagicMock` cursor that records calls.

This lets us test:
1. The handler processes SQS messages without crashing
2. The correct SQL upsert is attempted (assert `cursor.execute` was called with expected args)
3. AWS service calls (SQS send, SFN start) are made correctly

We do NOT need to test actual SQL correctness here — that's integration testing.

## Test Files to Create

### `tests/test_app_crawler.py`

Test the `app_crawler` Lambda handler end-to-end:

```python
"""Tests for app_crawler Lambda handler."""
import json
import pytest
import boto3
from moto import mock_aws
from unittest.mock import patch, MagicMock
from pytest_httpx import HTTPXMock

# SQS event shape the Lambda receives
def make_sqs_event(appids: list[int]) -> dict:
    return {
        "Records": [
            {
                "messageId": f"msg-{appid}",
                "body": json.dumps({"appid": appid}),
                "receiptHandle": "receipt",
            }
            for appid in appids
        ]
    }
```

**Test cases:**

1. `test_handler_processes_single_appid` — mock SQS + httpx, mock psycopg2.connect,
   invoke `handler(make_sqs_event([440]), {})`, assert:
   - Steam Store API was called for appid 440
   - SteamSpy API was called for appid 440
   - `psycopg2.connect` was called (DB write attempted)
   - Review queue `send_message` was called (appid queued for review crawl)

2. `test_handler_skips_on_steam_api_failure` — mock httpx to return 500 for Steam Store,
   assert handler does NOT crash (logs error, continues), DB write NOT called.

3. `test_handler_processes_batch` — SQS event with 3 appids, all succeed,
   assert DB write called 3 times.

### `tests/test_review_crawler.py`

Test the `review_crawler` Lambda handler:

```python
def make_sqs_event(appids: list[int]) -> dict:
    return {
        "Records": [
            {"messageId": f"msg-{appid}", "body": json.dumps({"appid": appid}), "receiptHandle": "r"}
            for appid in appids
        ]
    }
```

**Test cases:**

1. `test_handler_fetches_and_stores_reviews` — mock httpx with `steam_reviews_440.json`,
   mock psycopg2.connect, mock SFN (`moto mock_aws`), invoke handler, assert:
   - Reviews API called for appid 440
   - DB write attempted (cursor.execute called)
   - Step Functions `start_execution` called with correct appid in input

2. `test_handler_starts_sfn_after_reviews` — focus on SFN being triggered,
   assert the SFN ARN and input JSON are correct.

3. `test_handler_tolerates_empty_reviews` — mock reviews API returning 0 reviews,
   assert handler completes without error, SFN NOT triggered (no reviews = no analysis).

### `tests/test_api.py`

Test the FastAPI app in `src/lambda-functions/lambda_functions/api/handler.py`:

```python
from fastapi.testclient import TestClient
# import the FastAPI app object from the handler
```

**Test cases:**

1. `test_health_endpoint` — `GET /health` returns 200 with `storage_backend` key.

2. `test_preview_requires_appid` — `POST /preview` with empty body returns 422.

3. `test_preview_returns_partial_report` — mock the Step Functions call and storage,
   `POST /preview {"appid": 440}` returns only `game_name`, `overall_sentiment`,
   `sentiment_score`, `one_liner` (not full report fields).

4. `test_rate_limiter_blocks_second_request` — call `/preview` twice from same IP,
   second call returns 402 `{"error": "free_limit_reached"}`.

5. `test_validate_key_rejects_invalid_key` — `POST /validate-key {"key": "fake"}`,
   mock Lemon Squeezy API to return 404, assert 402 response.

## Test Configuration

Update `pyproject.toml` `[tool.pytest.ini_options]`:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

Add `tests/conftest.py` with shared fixtures:

```python
"""Shared pytest fixtures."""
import json
import os
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture
def steam_appdetails_440():
    return json.loads((FIXTURES_DIR / "steam_appdetails_440.json").read_text())

@pytest.fixture
def steamspy_appinfo_440():
    return json.loads((FIXTURES_DIR / "steamspy_appinfo_440.json").read_text())

@pytest.fixture
def steam_reviews_440():
    return json.loads((FIXTURES_DIR / "steam_reviews_440.json").read_text())

@pytest.fixture(autouse=True)
def aws_credentials():
    """Prevent any real AWS calls during tests."""
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
    os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
```

## Key Implementation Notes

**Import paths:** The handlers import from `library_layer.*` (e.g. `from library_layer.steam_source import ...`).
In tests, you need `src/library-layer` on the Python path. Add to `conftest.py`:
```python
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "library-layer"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "lambda-functions"))
```

**moto usage:** Use the `@mock_aws` decorator (moto 5.x unified decorator) not the
old per-service decorators. Create real moto SQS queues in the test so the handler's
boto3 calls succeed:
```python
@mock_aws
def test_something():
    sqs = boto3.client("sqs", region_name="us-west-2")
    queue = sqs.create_queue(QueueName="test-review-queue")
    os.environ["REVIEW_CRAWL_QUEUE_URL"] = queue["QueueUrl"]
    ...
```

**pytest-httpx:** Register expected HTTP responses before calling the handler:
```python
def test_something(httpx_mock: HTTPXMock, steam_appdetails_440):
    httpx_mock.add_response(
        url="https://store.steampowered.com/api/appdetails?appids=440&cc=us&l=en",
        json=steam_appdetails_440,
    )
    ...
```

**Async handlers:** The crawler handlers are `async def handler(event, context)`.
Use `pytest.mark.asyncio` or `asyncio_mode = "auto"` in pytest config.

## Acceptance Criteria

- [ ] `poetry add --group dev moto[sqs,secretsmanager,stepfunctions] pytest-httpx` succeeds
- [ ] `tests/fixtures/steam_appdetails_440.json` exists with real TF2 data
- [ ] `tests/fixtures/steamspy_appinfo_440.json` exists with real TF2 data
- [ ] `tests/fixtures/steam_reviews_440.json` exists with real TF2 data (3+ reviews)
- [ ] `tests/conftest.py` exists with path setup + shared fixtures
- [ ] `tests/test_app_crawler.py` — all 3 test cases pass
- [ ] `tests/test_review_crawler.py` — all 3 test cases pass
- [ ] `tests/test_api.py` — all 5 test cases pass
- [ ] `poetry run pytest` runs and all tests pass (or clearly explains any skipped tests)
- [ ] No test makes a real HTTP call or real AWS call

## Do NOT Change

- Any handler business logic
- CDK infrastructure files
- `src/library-layer/` or `src/lambda-functions/` structure
