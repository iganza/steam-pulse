# Steam API Request Metrics — Per-Region Observability

## Problem

We have no visibility into the rate at which we hit Steam's API, broken down by
region. With the spoke architecture dispatching work across multiple AWS regions,
we need to:

- See how many Steam API requests each region is making per minute/hour
- Detect when a region is getting throttled (429s)
- Spot imbalanced load distribution across spokes
- Have data to tune jitter/concurrency settings before we get rate-limited

Currently `_get_with_retry` logs warnings on 429s, but there are no structured
CloudWatch metrics for request volume, latency, or error rates by region/endpoint.

## Goal

Add CloudWatch metrics to `DirectSteamSource` so every Steam API call emits a
metric with the region dimension. Use the existing Powertools `Metrics` pattern
already established in the handlers.

## Design

### Metric location: `DirectSteamSource._get_with_retry()`

This is the single chokepoint — every Steam API call flows through here.
Instrument it once, all endpoints are covered.

### Metrics to emit

| Metric Name | Unit | When | Dimensions |
|---|---|---|---|
| `SteamApiRequests` | Count(1) | Every HTTP request attempt (including retries) | `region`, `endpoint` |
| `SteamApiErrors` | Count(1) | Every non-2xx response (429, 503, 4xx, 5xx) | `region`, `endpoint`, `status_code` |
| `SteamApiLatency` | Milliseconds | Every request attempt | `region`, `endpoint` |
| `SteamApiRetries` | Count(1) | Every retry (429/503 backoff) | `region`, `endpoint` |

### Dimension values

- **`region`**: `os.environ.get("AWS_REGION", "local")` — automatically set by
  Lambda runtime. Spokes in `us-west-2` will emit `region=us-west-2`, primary in
  `us-east-1` will emit `region=us-east-1`. Local dev shows `region=local`.

- **`endpoint`**: Derived from the URL, not the full URL (avoid high-cardinality).
  Map to one of: `app_details`, `reviews`, `review_summary`, `deck_compat`,
  `app_list`. Use a helper:

```python
def _endpoint_name(url: str) -> str:
    if "appreviews" in url:
        return "reviews"
    if "appdetails" in url:
        return "app_details"
    if "deckappcompatibility" in url:
        return "deck_compat"
    if "GetAppList" in url:
        return "app_list"
    return "unknown"
```

### Implementation approach: metrics callback

`DirectSteamSource` lives in `steam_source.py` (library layer) and is shared by
all Lambdas. It should NOT import Powertools `Metrics` directly — that would
couple the shared library to a specific metrics backend. Instead, use a callback.

**Constructor change:**

```python
from typing import Callable

MetricsCallback = Callable[[str, str, int, float], None]
# (endpoint, region, status_code, latency_ms) -> None

class DirectSteamSource(SteamDataSource):
    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str | None = None,
        on_request: MetricsCallback | None = None,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._on_request = on_request
        self._region = os.environ.get("AWS_REGION", "local")
        ...
```

**In `_get_with_retry()`:**

```python
import time

async def _get_with_retry(self, url: str, **params: object) -> httpx.Response:
    endpoint = _endpoint_name(url)
    for attempt in range(6):
        t0 = time.monotonic()
        try:
            resp = await self._client.get(url, params=params or None)
            latency_ms = (time.monotonic() - t0) * 1000

            if self._on_request:
                self._on_request(endpoint, self._region, resp.status_code, latency_ms)

            if resp.status_code in _RETRY_STATUSES:
                # existing retry logic...
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            if self._on_request:
                self._on_request(endpoint, self._region, exc.response.status_code, latency_ms)
            # existing retry/raise logic...
    raise SteamAPIError(f"Max retries exceeded for {url}")
```

**Handler wiring (e.g., `spoke_handler.py`):**

```python
from aws_lambda_powertools import Metrics
from aws_lambda_powertools.metrics import MetricUnit

metrics = Metrics(namespace="SteamPulse", service="crawler-spoke")

def _steam_metrics_callback(endpoint: str, region: str, status_code: int, latency_ms: float) -> None:
    metrics.add_dimension(name="region", value=region)
    metrics.add_dimension(name="endpoint", value=endpoint)
    metrics.add_metric(name="SteamApiRequests", unit=MetricUnit.Count, value=1)
    metrics.add_metric(name="SteamApiLatency", unit=MetricUnit.Milliseconds, value=latency_ms)
    if status_code >= 400:
        metrics.add_dimension(name="status_code", value=str(status_code))
        metrics.add_metric(name="SteamApiErrors", unit=MetricUnit.Count, value=1)
    if status_code in (429, 503):
        metrics.add_metric(name="SteamApiRetries", unit=MetricUnit.Count, value=1)

_steam = DirectSteamSource(_http, api_key=_steam_api_key, on_request=_steam_metrics_callback)
```

Wire the same callback in `handler.py` (primary crawler) and `spoke_handler.py`.
The `CatalogService` also uses `DirectSteamSource` indirectly — check if it
constructs its own client and wire there too.

## Changes

### 1. `src/library-layer/library_layer/steam_source.py`

- Add `MetricsCallback` type alias
- Add `_endpoint_name(url)` module-level helper
- Add `on_request` param to `DirectSteamSource.__init__`
- Add `self._region = os.environ.get("AWS_REGION", "local")`
- Instrument `_get_with_retry()` with timing + callback invocation on every
  request attempt (success and failure)

### 2. `src/lambda-functions/lambda_functions/crawler/spoke_handler.py`

- Define `_steam_metrics_callback` function
- Pass `on_request=_steam_metrics_callback` when constructing `DirectSteamSource`

### 3. `src/lambda-functions/lambda_functions/crawler/handler.py`

- Same as spoke_handler — define callback, wire into `DirectSteamSource`

### 4. `src/lambda-functions/lambda_functions/crawler/ingest_handler.py`

- The ingest handler constructs a `DirectSteamSource` but never calls Steam
  (it only ingests pre-fetched data). Wire the callback anyway for consistency,
  but it won't fire in practice.

### 5. Tests

**`tests/test_steam_source.py`** (or equivalent):
- Test that `on_request` callback is called with correct args on success
- Test that callback is called with error status on 429
- Test that callback is called on each retry attempt (not just final)
- Test that `_endpoint_name()` maps URLs correctly
- Test that `on_request=None` (default) doesn't break anything

**`tests/handlers/test_spoke_handler.py`:**
- No changes needed — mock `_steam` already bypasses `DirectSteamSource`

## CloudWatch usage

Once deployed, query metrics in CloudWatch:

```
# Requests per minute by region
SELECT AVG(SteamApiRequests) FROM SteamPulse
WHERE endpoint = 'reviews'
GROUP BY region
PERIOD 60

# 429 rate by region
SELECT SUM(SteamApiRetries) FROM SteamPulse
GROUP BY region
PERIOD 300

# Latency p99 by endpoint
SELECT p99(SteamApiLatency) FROM SteamPulse
GROUP BY endpoint
PERIOD 300
```

## Rules

- Do NOT import Powertools in `steam_source.py` — use the callback pattern.
- `_endpoint_name()` must be deterministic and low-cardinality (5 values max).
- Callback must be called on EVERY request attempt, including retries.
- Timing must use `time.monotonic()`, not `time.time()`.
- The callback must not raise — wrap in try/except if needed so metrics failures
  never break Steam API calls.
- Run `poetry run pytest -v` — all tests must pass.
- Run `poetry run ruff check . && poetry run ruff format .` — no lint errors.
