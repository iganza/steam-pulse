# Event-Driven Pipeline: SNS Topics + Pub/Sub Refactor

## Goal

Refactor the SteamPulse pipeline from point-to-point SQS to a **pub/sub
architecture using SNS → SQS fan-out**. Every stage transition publishes an
event to an SNS topic. Downstream consumers subscribe independently. This
decouples producers from consumers and lets us add new subscribers (email,
cache invalidation, batch processing) without touching existing code.

Also define all events the system will eventually need — even if they have zero
subscribers today — so the topic names and message schemas are established from
day one.

---

## Current State

**Existing infrastructure** (in `infra/stacks/messaging_stack.py` +
`compute_stack.py`):
- `AppCrawlQueue` + DLQ (SQS, batch=10, triggers `crawler_fn`)
- `ReviewCrawlQueue` + DLQ (SQS, batch=1, triggers `crawler_fn`)
- `AnalysisMachine` (Step Functions EXPRESS, triggered by `crawl_service._trigger_analysis()`)
- `CatalogRefreshRule` (EventBridge, 7-day rate, disabled, invokes `crawler_fn`)
- `NightlyRecrawl` (EventBridge, cron 2AM UTC, disabled, sends to `AppCrawlQueue`)

**Existing handlers** (in `src/lambda-functions/lambda_functions/`):
- `crawler/handler.py` — processes SQS records, dispatches to CrawlService
- `analysis/handler.py` — triggered by Step Functions, runs two-pass LLM
- `api/handler.py` — FastAPI, serves frontend + REST endpoints

**Existing services** (in `src/library-layer/library_layer/services/`):
- `CrawlService` — crawl_app(), crawl_reviews(), _trigger_analysis()
- `CatalogService` — refresh() (GetAppList → bulk upsert → enqueue)
- `AnalysisService` — wraps analyzer for Lambda handler

---

## Architecture After This Refactor

### Domain Topics

Instead of one SNS topic per event type (11 topics), use **3 domain-level
topics** with `event_type` message attributes for routing. Consumers subscribe
with filter policies on `event_type` to receive only the events they care about.

| Domain Topic | Event Types |
|---|---|
| `game-events` | `game-discovered`, `game-metadata-ready`, `game-released`, `game-delisted` (model only, no infra), `game-price-changed`, `game-updated`, `review-milestone` |
| `content-events` | `reviews-ready`, `report-ready` |
| `system-events` | `batch-complete`, `catalog-refresh-complete` |

### Event Flow Diagram

```
EventBridge (daily)
  └─▶ CatalogDiscovery Lambda
       └─▶ publishes to game-events: event_type=game-discovered (per new appid)
       └─▶ publishes to system-events: event_type=catalog-refresh-complete

game-events [event_type=game-discovered]
  └─▶ SQS: metadata-enrichment-queue
       └─▶ MetadataEnrichment (crawler_fn, batch=10)
            └─▶ publishes to game-events: event_type=game-metadata-ready
            └─▶ (conditional) game-released, game-price-changed, review-milestone

game-events [event_type=game-metadata-ready, is_eligible=true]
  ├─▶ SQS: review-crawl-queue (filter: is_eligible=true)
  │    └─▶ ReviewCrawl (crawler_fn, batch=1)
  │         └─▶ publishes to content-events: event_type=reviews-ready
  └─▶ (future: game-index-queue for sitemap rebuild)

game-events [event_type=game-released]
  └─▶ SQS: review-crawl-queue (newly released → start crawling reviews)

content-events [event_type=reviews-ready]
  ├─▶ SQS: batch-staging-queue (collects appids for nightly Bedrock batch)
  └─▶ (future: real-time-analysis-queue for on-demand analysis)

content-events [event_type=report-ready]
  ├─▶ SQS: cache-invalidation-queue (ISR revalidation)
  └─▶ (future: email-notification-queue, index-rebuild-queue)

game-events [event_type=game-updated]
  ├─▶ SQS: review-crawl-queue (if stale reviews)
  └─▶ (future: staleness-check-queue)

system-events [event_type=batch-complete]
  ├─▶ SQS: batch-results-queue (process batch output)
  └─▶ (future: notify-admin-queue)
```

### Bedrock Batch Processing Note

The primary analysis path uses **Bedrock Batch Inference** (not real-time
Lambda). The pipeline is:

1. `reviews-ready` events accumulate appids in the `batch-staging-queue`
2. A **scheduled Lambda** (daily or when threshold met) reads staged appids,
   builds JSONL input, uploads to S3, and calls `CreateModelInvocationJob`
3. A **polling Step Function** (STANDARD, not EXPRESS) checks batch status
   every 15 minutes via Wait states
4. On completion, processes output from S3, upserts reports, publishes
   `report-ready` events

The batch path is **out of scope for this prompt** — it has its own prompt at
`scripts/prompts/bedrock-batch-analysis.md`. This refactor establishes the
`reviews-ready` and `report-ready` SNS topics that the batch system will
publish/subscribe to. The real-time Step Functions analysis path (`AnalysisMachine`)
remains as a fallback for on-demand single-game analysis from the API.

---

## SteamPulseConfig Integration

All topic ARNs must be added to
`src/library-layer/library_layer/config.py` (`SteamPulseConfig` Pydantic
Settings class). Do NOT use raw `os.environ` in service constructors.

Add these fields (**required `str`**, not optional — deployment must provide them):

```python
# SNS Domain Topic ARNs (required — publish_event will fail if missing)
game_events_topic_arn: str = Field(alias="GAME_EVENTS_TOPIC_ARN")
content_events_topic_arn: str = Field(alias="CONTENT_EVENTS_TOPIC_ARN")
system_events_topic_arn: str = Field(alias="SYSTEM_EVENTS_TOPIC_ARN")

# Eligibility threshold — default 500, overridable via SSM at runtime
review_eligibility_threshold: int = Field(default=500, alias="REVIEW_ELIGIBILITY_THRESHOLD")
```

**Topic ARNs are NOT optional.** If any ARN is missing, `SteamPulseConfig()`
raises a Pydantic `ValidationError` at Lambda cold start — loud, immediate
failure instead of silent data loss at runtime.

**`review_eligibility_threshold`** has a sensible default (500) but can be
overridden via env var or SSM param at runtime. For dynamic runtime changes
(without redeployment), add a cached SSM reader:

```python
import time
import boto3
from functools import lru_cache

_ssm_cache: dict[str, tuple[int, float]] = {}  # key → (value, expiry)
_SSM_TTL = 300  # 5 minutes

def get_eligibility_threshold(config: SteamPulseConfig, env: str = "staging") -> int:
    """Read threshold from SSM with 5-min cache. Falls back to config default."""
    cache_key = "review_eligibility_threshold"
    now = time.time()
    if cache_key in _ssm_cache and _ssm_cache[cache_key][1] > now:
        return _ssm_cache[cache_key][0]
    try:
        ssm = boto3.client("ssm")
        param = ssm.get_parameter(
            Name=f"/steampulse/{env}/config/review-eligibility-threshold"
        )
        value = int(param["Parameter"]["Value"])
        _ssm_cache[cache_key] = (value, now + _SSM_TTL)
        return value
    except Exception:
        return config.review_eligibility_threshold
```

Add the SSM param in CDK (`messaging_stack.py` or a new `config_stack.py`):
```
/steampulse/{env}/config/review-eligibility-threshold  →  "500"
```

For **local dev/testing**, set dummy values in `.env` or override in test
fixtures:
```
GAME_EVENTS_TOPIC_ARN=arn:aws:sns:us-east-1:000000000000:local-game-events
CONTENT_EVENTS_TOPIC_ARN=arn:aws:sns:us-east-1:000000000000:local-content-events
SYSTEM_EVENTS_TOPIC_ARN=arn:aws:sns:us-east-1:000000000000:local-system-events
```

In tests, mock the SNS client so no real publishes happen. The point is:
**the code never silently skips a publish. Either it publishes or it raises.**

Services receive `config: SteamPulseConfig` and read topic ARNs from it.

---

## Complete Event Catalog

Define ALL of these SNS topics. Some will have zero subscribers initially.
That's intentional — the topics establish the contract.

### Game Lifecycle Events

| SNS Topic             | Message Schema                                                            | Published By                                                       | Current Subscribers           | Future Subscribers                  |
|-----------------------|---------------------------------------------------------------------------|--------------------------------------------------------------------|-------------------------------|-------------------------------------|
| `game-discovered`     | `{"appid": int}`                                                          | CatalogService.refresh()                                           | metadata-enrichment-queue     | —                                   |
| `game-metadata-ready` | `{"appid": int, "review_count": int, "is_eligible": bool}`                | CrawlService.crawl_app()                                           | review-crawl-queue (filtered) | game-index-queue                    |
| `game-released`       | `{"appid": int, "game_name": str, "release_date": str}`                   | CrawlService.crawl_app() (when `coming_soon` flips false)          | review-crawl-queue            | notify-pro-users, priority-analysis |
| `game-delisted`       | `{"appid": int, "game_name": str}`                                        | (not wired — Pydantic model only, no detection logic or infra yet) | (none)                        | sitemap-rebuild, index-cleanup      |
| `game-price-changed`  | `{"appid": int, "old_price": float, "new_price": float, "is_free": bool}` | CrawlService.crawl_app() (price differs from DB)                   | (none yet)                    | notify-pro-users, benchmark-recalc  |
| `game-updated`        | `{"appid": int, "review_count": int, "reviews_since_last": int}`          | Re-check Lambda                                                    | review-crawl-queue            | staleness-check                     |
| `review-milestone`    | `{"appid": int, "milestone": int, "review_count": int}`                   | CrawlService.crawl_app() (review_count crosses 500, 1k, 5k, 10k)   | (none yet)                    | re-analysis-trigger, notify-pro     |

### Content Pipeline Events

| SNS Topic | Message Schema | Published By | Current Subscribers | Future Subscribers |
|---|---|---|---|---|
| `reviews-ready` | `{"appid": int, "game_name": str, "reviews_crawled": int}` | CrawlService.crawl_reviews() | batch-staging-queue | real-time-analysis |
| `report-ready` | `{"appid": int, "game_name": str, "sentiment": str}` | AnalysisHandler / BatchResults | cache-invalidation-queue | email-queue, index-rebuild |

### System Events

| SNS Topic | Message Schema | Published By | Current Subscribers | Future Subscribers |
|---|---|---|---|---|
| `batch-complete` | `{"batch_job_id": str, "games_processed": int, "status": str}` | BatchStatusChecker | batch-results-queue | notify-admin |
| `catalog-refresh-complete` | `{"new_games": int, "total_games": int}` | CatalogService.refresh() | (none yet) | admin-dashboard |

### Detection Logic for New Events

**`game-released`** — In `crawl_app()`, before upserting, load the existing
game row. If `existing.coming_soon == True` and `new_data.coming_soon == False`,
publish `game-released`. This also means the review-crawl-queue should
subscribe to `game-released` (same as `game-metadata-ready` with filter).

**`game-price-changed`** — In `crawl_app()`, compare `existing.price_usd` with
`new_data.price_usd` or `existing.is_free` with `new_data.is_free`. If
different, publish `game-price-changed`.

**`review-milestone`** — In `crawl_app()`, check if `review_count` crossed a
milestone boundary since last crawl. Milestones: `[500, 1000, 5000, 10000]`.
If `old_count < milestone <= new_count`, publish `review-milestone`.

### SNS Message Filtering (event_type + custom attributes)

All subscriptions use **filter policies on MessageAttributes**. Every publish
includes `event_type` as a MessageAttribute. Some events add extra attributes
for finer filtering.

**Subscription filter examples:**

```python
# metadata-enrichment-queue: only game-discovered events
game_events_topic.add_subscription(
    subs.SqsSubscription(
        metadata_enrichment_queue,
        filter_policy={
            "event_type": sns.SubscriptionFilter.string_filter(
                allowlist=["game-discovered"]
            )
        }
    )
)

# review-crawl-queue: TWO subscriptions to avoid 94k wasted Lambda invocations
# Sub 1: game-metadata-ready (eligible only — filters out ~94k ineligible games)
game_events_topic.add_subscription(
    subs.SqsSubscription(
        review_crawl_queue,
        filter_policy={
            "event_type": sns.SubscriptionFilter.string_filter(
                allowlist=["game-metadata-ready"]
            ),
            "is_eligible": sns.SubscriptionFilter.string_filter(
                allowlist=["true"]
            ),
        }
    )
)
# Sub 2: game-released + game-updated (always eligible for review crawl)
game_events_topic.add_subscription(
    subs.SqsSubscription(
        review_crawl_queue,
        filter_policy={
            "event_type": sns.SubscriptionFilter.string_filter(
                allowlist=["game-released", "game-updated"]
            ),
        }
    )
)
# These filter policies are mutually exclusive → no duplicate delivery risk.

# batch-staging-queue: only reviews-ready events
content_events_topic.add_subscription(
    subs.SqsSubscription(
        batch_staging_queue,
        filter_policy={
            "event_type": sns.SubscriptionFilter.string_filter(
                allowlist=["reviews-ready"]
            )
        }
    )
)

# cache-invalidation-queue: only report-ready events
content_events_topic.add_subscription(
    subs.SqsSubscription(
        cache_invalidation_queue,
        filter_policy={
            "event_type": sns.SubscriptionFilter.string_filter(
                allowlist=["report-ready"]
            )
        }
    )
)
```

For this to work, **every publish** must include `event_type` in MessageAttributes:
```python
sns_client.publish(
    TopicArn=game_events_topic_arn,
    Message=event.model_dump_json(),
    MessageAttributes={
        "event_type": {"DataType": "String", "StringValue": event.event_type},
        # Optional extra attributes for finer filtering:
        "is_eligible": {"DataType": "String", "StringValue": "true"},
    }
)
```

---

## CDK Changes

### `infra/stacks/messaging_stack.py`

Add **3 SNS domain topics** + their SQS subscriptions with filter policies.
Keep existing queues. Rename queues for clarity:

**Topics:**

| Topic | Construct ID |
|---|---|
| `game-events` | `GameEventsTopic` |
| `content-events` | `ContentEventsTopic` |
| `system-events` | `SystemEventsTopic` |

**Queues:**

| Old Name | New Name | Subscribed To | Filter |
|---|---|---|---|
| `AppCrawlQueue` | `MetadataEnrichmentQueue` | `game-events` | `event_type=game-discovered` |
| `ReviewCrawlQueue` | `ReviewCrawlQueue` | `game-events` | `event_type IN [game-metadata-ready, game-released, game-updated]` |
| (new) | `BatchStagingQueue` | `content-events` | `event_type=reviews-ready` |
| (new) | `CacheInvalidationQueue` | `content-events` | `event_type=report-ready` |

Add DLQs for all new queues (same pattern: 3 max receives, 14-day retention).

Export topic ARNs via SSM parameters:
```
/steampulse/{env}/messaging/game-events-topic-arn
/steampulse/{env}/messaging/content-events-topic-arn
/steampulse/{env}/messaging/system-events-topic-arn
```

These SSM params are consumed by `SteamPulseConfig` in `config.py` (see above).
Lambda env vars: `GAME_EVENTS_TOPIC_ARN`, `CONTENT_EVENTS_TOPIC_ARN`,
`SYSTEM_EVENTS_TOPIC_ARN`.

### `infra/stacks/compute_stack.py`

- Pass the 3 topic ARNs to Lambdas via environment variables:
  ```
  GAME_EVENTS_TOPIC_ARN
  CONTENT_EVENTS_TOPIC_ARN
  SYSTEM_EVENTS_TOPIC_ARN
  ```
- Grant `sns:Publish` permissions: `crawler_fn` gets `game-events` + `content-events`, `analysis_fn` gets `content-events`
- Update SQS event sources to reference renamed queues
- Keep `AnalysisMachine` as-is (used for on-demand single-game analysis)

---

## Service Layer Changes

### `src/library-layer/library_layer/services/crawl_service.py`

**Constructor changes:**
- Accept `config: SteamPulseConfig` and `sns_client` (boto3 SNS client)
- Read topic ARNs from `config` (only 3: `game_events_topic_arn`, `content_events_topic_arn`, `system_events_topic_arn`)
- Remove direct SQS queue URL for review queue (no longer publishing directly)
- Keep app crawl queue URL if still needed for CatalogService.refresh() bulk enqueue

**`crawl_app()` — after upserting game metadata, detect state changes:**
```python
from library_layer.utils.events import publish_event
from library_layer.events import (
    GameMetadataReadyEvent, GameReleasedEvent,
    GamePriceChangedEvent, ReviewMilestoneEvent,
)

# Load existing row BEFORE upsert (for state comparison)
existing = self._game_repo.find_by_appid(appid)

# ... upsert game metadata ...

# Always publish metadata-ready (to game-events topic)
threshold = get_eligibility_threshold(self._config)
is_eligible = game_data["review_count"] >= threshold
publish_event(
    self._sns_client,
    self._config.game_events_topic_arn,
    GameMetadataReadyEvent(
        appid=appid,
        review_count=game_data["review_count"],
        is_eligible=is_eligible,
    ),
    extra_attributes={"is_eligible": str(is_eligible).lower()},
)

# Detect game release: coming_soon flipped from True to False
if existing and existing.coming_soon and not game_data.get("coming_soon", True):
    publish_event(
        self._sns_client,
        self._config.game_events_topic_arn,
        GameReleasedEvent(
            appid=appid,
            game_name=game_data["name"],
            release_date=game_data.get("release_date", ""),
        ),
    )

# Detect price change
if existing and existing.price_usd != game_data.get("price_usd"):
    publish_event(
        self._sns_client,
        self._config.game_events_topic_arn,
        GamePriceChangedEvent(
            appid=appid,
            old_price=existing.price_usd or 0.0,
            new_price=game_data.get("price_usd", 0.0),
            is_free=game_data.get("is_free", False),
        ),
    )

# Detect review milestone crossing — publish ALL crossed milestones
MILESTONES = [500, 1000, 5000, 10000]
old_count = existing.review_count if existing else 0
new_count = game_data["review_count"]
for milestone in MILESTONES:
    if old_count < milestone <= new_count:
        publish_event(
            self._sns_client,
            self._config.game_events_topic_arn,
            ReviewMilestoneEvent(appid=appid, milestone=milestone, review_count=new_count),
        )
```

**`crawl_reviews()` — after upserting reviews:**
```python
# Instead of directly calling _trigger_analysis():
publish_event(
    self._sns_client,
    self._config.content_events_topic_arn,  # content domain
    ReviewsReadyEvent(appid=appid, game_name=game_name, reviews_crawled=len(reviews)),
)
```

### `src/library-layer/library_layer/services/catalog_service.py`

**Constructor changes:**
- Accept `config: SteamPulseConfig` and `sns_client`
- Read topic ARNs from config

**`refresh()` — after discovering new games:**
```python
# Publish each new appid to game-events topic
for appid in new_appids:
    publish_event(
        self._sns_client,
        self._config.game_events_topic_arn,
        GameDiscoveredEvent(appid=appid),
    )

# Publish completion event (system domain)
publish_event(
    self._sns_client,
    self._config.system_events_topic_arn,
    CatalogRefreshCompleteEvent(
        new_games=len(new_appids),
        total_games=total_count,
    ),
)
```

**Note:** For bulk discovery (thousands of new games), batch the SNS publishes.
SNS `PublishBatch` supports up to 10 messages per call.

### `src/lambda-functions/lambda_functions/analysis/handler.py`

**After upserting report (use config, not raw os.environ):**
```python
config = SteamPulseConfig()
publish_event(
    sns_client,
    config.content_events_topic_arn,  # content domain
    ReportReadyEvent(
        appid=appid,
        game_name=game_name,
        sentiment=result.get("overall_sentiment", "Unknown"),
    ),
)
```

### `src/lambda-functions/lambda_functions/crawler/handler.py`

Update handler to unwrap SNS-wrapped SQS messages. When SNS delivers to SQS,
the SQS message body is an SNS envelope:
```json
{
  "Type": "Notification",
  "Message": "{\"appid\": 440}",
  "MessageAttributes": {...}
}
```

The handler must detect and unwrap this:
```python
def _extract_payload(record_body: str) -> dict:
    body = json.loads(record_body)
    if "Type" in body and body["Type"] == "Notification":
        return json.loads(body["Message"])
    return body
```

Apply this unwrapping in both `_app_crawl_record()` and `_review_crawl_record()`.

---

## Event Schema Pydantic Models

Create `src/library-layer/library_layer/events.py`:

```python
from typing import Literal
from pydantic import BaseModel


# --- All event type literals defined in one place ---

EventType = Literal[
    # Game Lifecycle (game-events topic)
    "game-discovered",
    "game-metadata-ready",
    "game-released",
    "game-delisted",
    "game-price-changed",
    "game-updated",
    "review-milestone",
    # Content Pipeline (content-events topic)
    "reviews-ready",
    "report-ready",
    # System (system-events topic)
    "batch-complete",
    "catalog-refresh-complete",
]


class BaseEvent(BaseModel):
    """Base class for all SteamPulse events.

    - event_type: discriminator for routing (also sent as SNS MessageAttribute)
    - version: schema version for backward compatibility. All new fields
      on existing events MUST have defaults so old consumers don't break.
    """
    event_type: EventType
    version: int = 1


# --- Game Lifecycle Events (published to game-events topic) ---

class GameDiscoveredEvent(BaseEvent):
    event_type: Literal["game-discovered"] = "game-discovered"
    appid: int

class GameMetadataReadyEvent(BaseEvent):
    event_type: Literal["game-metadata-ready"] = "game-metadata-ready"
    appid: int
    review_count: int
    is_eligible: bool

class GameReleasedEvent(BaseEvent):
    event_type: Literal["game-released"] = "game-released"
    appid: int
    game_name: str
    release_date: str

class GameDelistedEvent(BaseEvent):
    event_type: Literal["game-delisted"] = "game-delisted"
    appid: int
    game_name: str

class GamePriceChangedEvent(BaseEvent):
    event_type: Literal["game-price-changed"] = "game-price-changed"
    appid: int
    old_price: float
    new_price: float
    is_free: bool

class GameUpdatedEvent(BaseEvent):
    event_type: Literal["game-updated"] = "game-updated"
    appid: int
    review_count: int
    reviews_since_last: int

class ReviewMilestoneEvent(BaseEvent):
    event_type: Literal["review-milestone"] = "review-milestone"
    appid: int
    milestone: int  # 500, 1000, 5000, 10000
    review_count: int


# --- Content Pipeline Events (published to content-events topic) ---

class ReviewsReadyEvent(BaseEvent):
    event_type: Literal["reviews-ready"] = "reviews-ready"
    appid: int
    game_name: str
    reviews_crawled: int

class ReportReadyEvent(BaseEvent):
    event_type: Literal["report-ready"] = "report-ready"
    appid: int
    game_name: str
    sentiment: str


# --- System Events (published to system-events topic) ---

class BatchCompleteEvent(BaseEvent):
    event_type: Literal["batch-complete"] = "batch-complete"
    batch_job_id: str
    games_processed: int
    status: str

class CatalogRefreshCompleteEvent(BaseEvent):
    event_type: Literal["catalog-refresh-complete"] = "catalog-refresh-complete"
    new_games: int
    total_games: int
```

### Event Schema Rules

1. **`EventType` Literal defined once** — single source of truth for all valid event type strings
2. **`BaseEvent.event_type` is typed as `EventType`** — Pydantic rejects unknown event types
3. **Each subclass narrows with `Literal["specific-type"]`** — enforces exact string at construction
4. **version starts at 1** — increment when adding fields
5. **New fields on existing events MUST have defaults** — backward compatibility
6. **Consumers use `event_type` to dispatch** — parse base, check type, then parse specific model

---

## SNS Publish Helper

Create `src/library-layer/library_layer/utils/events.py`:

```python
import json
import logging
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class EventPublishError(Exception):
    """Raised when event publishing fails."""


def publish_event(
    sns_client,
    topic_arn: str,
    event: "BaseEvent",
    extra_attributes: dict[str, str] | None = None,
) -> str:
    """Publish a BaseEvent to an SNS topic.

    - topic_arn is REQUIRED (not optional). If missing, it's a deployment bug —
      SteamPulseConfig validation catches this at cold start.
    - event_type is automatically added as a MessageAttribute for SNS filtering.
    - extra_attributes (e.g. is_eligible) are merged into MessageAttributes.
    - Raises EventPublishError on SNS client errors for visibility.
    """
    attributes = {
        "event_type": {"DataType": "String", "StringValue": event.event_type},
    }
    if extra_attributes:
        for k, v in extra_attributes.items():
            attributes[k] = {"DataType": "String", "StringValue": v}

    try:
        response = sns_client.publish(
            TopicArn=topic_arn,
            Message=event.model_dump_json(),
            MessageAttributes=attributes,
        )
        logger.info(
            "Published %s to %s (MessageId: %s)",
            event.event_type, topic_arn.split(":")[-1], response["MessageId"],
        )
        return response["MessageId"]
    except Exception as exc:
        logger.error("Failed to publish %s: %s", event.event_type, exc)
        raise EventPublishError(
            f"Failed to publish {event.event_type} to {topic_arn}"
        ) from exc
```

### Design Decisions (publish_event)

1. **No silent skips.** `topic_arn` is `str`, not `str | None`. If an ARN is
   missing, `SteamPulseConfig` raises `ValidationError` at Lambda cold start —
   fail loud, fail early.
2. **`event_type` always in MessageAttributes.** This is how SNS filter policies
   route events to the correct queues.
3. **Explicit error wrapping.** `EventPublishError` gives callers a clean
   exception to catch. In Lambda context, uncaught exceptions → SQS retry →
   DLQ. This is the correct behavior.
4. **INFO-level logging on success.** Enables tracing event flow in CloudWatch
   without enabling DEBUG.
5. **For tests:** mock the `sns_client` — no need for a "skip publish" mode.
   The test fixture provides a mock client that captures calls for assertions.

---

## Tests

### Unit Tests — Event Models (`tests/test_events.py`)

1. `test_game_discovered_event_valid` — `GameDiscoveredEvent(appid=440)` serializes/deserializes, has `event_type="game-discovered"` and `version=1`
2. `test_game_metadata_ready_event_valid` — all fields round-trip, `event_type="game-metadata-ready"`
3. `test_game_released_event_valid` — all fields round-trip
4. `test_game_delisted_event_valid` — all fields round-trip (model only, no infra wired)
5. `test_game_price_changed_event_valid` — all fields round-trip, float prices
6. `test_review_milestone_event_valid` — milestone=500, review_count=523
7. `test_reviews_ready_event_valid` — all fields round-trip
8. `test_report_ready_event_valid` — all fields round-trip
9. `test_batch_complete_event_valid` — all fields round-trip
10. `test_catalog_refresh_complete_event_valid` — includes `new_games` and `total_games`
11. `test_all_events_inherit_base_event` — every event class is subclass of BaseEvent
12. `test_event_type_literal_enforced` — cannot construct `GameDiscoveredEvent(event_type="wrong")`
13. `test_event_rejects_missing_required_field` — `GameDiscoveredEvent()` raises ValidationError
14. `test_event_rejects_wrong_type` — `GameDiscoveredEvent(appid="abc")` raises ValidationError
15. `test_event_version_defaults_to_1` — new event has `version=1` without explicit set
16. `test_event_type_in_serialized_json` — `model_dump_json()` includes `event_type` field

### Unit Tests — SNS Publish Helper (`tests/utils/test_events.py`)

17. `test_publish_event_calls_sns` — mock SNS client, verify `publish()` called with correct TopicArn and Message
18. `test_publish_event_includes_event_type_attribute` — verify MessageAttributes always includes `event_type`
19. `test_publish_event_with_extra_attributes` — extra_attributes merged into MessageAttributes alongside event_type
20. `test_publish_event_serializes_pydantic` — verify Message is valid JSON matching the model
21. `test_publish_event_raises_on_sns_error` — mock SNS raises ClientError → `EventPublishError` raised
22. `test_publish_event_logs_success` — verify INFO-level log with event_type and MessageId

### Unit Tests — SNS Envelope Unwrapping (`tests/handlers/test_crawler_handler.py`)

23. `test_extract_payload_plain_sqs` — plain `{"appid": 440, "event_type": "game-discovered"}` body passes through unchanged
24. `test_extract_payload_sns_wrapped` — SNS envelope `{"Type":"Notification","Message":"{...}"}` unwraps correctly
25. `test_extract_payload_handles_string_attributes` — MessageAttributes present but ignored in payload
26. `test_consumer_dispatches_by_event_type` — handler reads `event_type` from payload and routes to correct processing method

### Integration Tests — Service SNS Publishing (mock SNS)

Add to existing service tests or create `tests/services/test_crawl_service_events.py`:

27. `test_crawl_app_publishes_metadata_ready` — mock SNS client, call `crawl_app()`, verify publish called on `game_events_topic_arn` with `GameMetadataReadyEvent`
28. `test_crawl_app_eligible_sets_is_eligible_true` — game with 1000 reviews, threshold=500 → `is_eligible: true` in extra_attributes
29. `test_crawl_app_ineligible_sets_is_eligible_false` — game with 100 reviews, threshold=500 → `is_eligible: false`
30. `test_crawl_app_uses_configurable_threshold` — set threshold=200 in config, game with 300 reviews → `is_eligible: true` (would be false at 500)
31. `test_get_eligibility_threshold_ssm_override` — mock SSM returns 1000 → `get_eligibility_threshold()` returns 1000 (not config default 500)
32. `test_get_eligibility_threshold_ssm_fallback` — mock SSM raises → falls back to `config.review_eligibility_threshold`
33. `test_get_eligibility_threshold_caches` — two calls within 5min → only one SSM call
34. `test_crawl_app_detects_game_released` — existing row has `coming_soon=True`, new data `coming_soon=False` → publishes `GameReleasedEvent` to `game_events_topic_arn`
35. `test_crawl_app_no_release_if_already_released` — existing `coming_soon=False`, new `coming_soon=False` → no `GameReleasedEvent`
36. `test_crawl_app_detects_price_change` — existing `price_usd=29.99`, new `price_usd=19.99` → publishes `GamePriceChangedEvent`
37. `test_crawl_app_no_price_event_if_same` — same price → no publish
38. `test_crawl_app_detects_review_milestone` — existing 490 reviews, new 520 → publishes `ReviewMilestoneEvent(milestone=500)`
39. `test_crawl_app_publishes_all_crossed_milestones` — existing 400, new 1200 → publishes BOTH milestone=500 and milestone=1000
40. `test_crawl_app_no_milestone_if_already_past` — existing 600, new 700 → no milestone publish (500 already passed, 1000 not reached)
41. `test_crawl_reviews_publishes_reviews_ready` — mock SNS, call `crawl_reviews()`, verify `ReviewsReadyEvent` published to `content_events_topic_arn`
42. `test_catalog_refresh_publishes_discovered_events` — mock SNS + Steam API, verify `GameDiscoveredEvent` published per new appid to `game_events_topic_arn`
43. `test_catalog_refresh_publishes_completion` — verify `CatalogRefreshCompleteEvent` published to `system_events_topic_arn` with counts

### CDK Tests — Snapshot or assertion tests

44. `test_messaging_stack_creates_3_topics` — synthesize stack, assert 3 SNS topics exist (game-events, content-events, system-events)
45. `test_messaging_stack_creates_subscriptions_with_filters` — assert SQS subscriptions have `event_type` filter policies
46. `test_messaging_stack_review_crawl_filter` — assert review-crawl-queue has TWO subscriptions: (1) `event_type=game-metadata-ready AND is_eligible=true`, (2) `event_type IN [game-released, game-updated]`
47. `test_compute_stack_grants_sns_publish` — assert Lambda IAM policy includes `sns:Publish` on the 3 topics
48. `test_config_has_3_topic_arn_fields` — `SteamPulseConfig` accepts `GAME_EVENTS_TOPIC_ARN`, `CONTENT_EVENTS_TOPIC_ARN`, `SYSTEM_EVENTS_TOPIC_ARN` as required fields
49. `test_config_rejects_missing_topic_arn` — `SteamPulseConfig()` with no env vars raises `ValidationError`
50. `test_ssm_param_created_for_threshold` — CDK creates SSM param `/steampulse/{env}/config/review-eligibility-threshold` with value "500"

---

## Constraints

- Do NOT remove or rename the `AnalysisMachine` Step Functions — it stays as the on-demand real-time path
- Do NOT implement the Bedrock batch pipeline — only create the topics/queues it will use
- Do NOT change the API handler (`api/handler.py`) — it doesn't publish events (it uses Step Functions directly)
- All SNS topic ARNs must flow through `SteamPulseConfig` in `config.py` — **required fields, not optional**
- `publish_event()` must NOT silently skip — if ARN is missing, it's a deployment bug caught at cold start
- `publish_event()` must always include `event_type` in MessageAttributes for SNS filter routing
- All events must inherit from `BaseEvent` with `event_type` (Literal) and `version: int = 1`
- New fields added to existing events MUST have defaults (backward-compatible schema evolution)
- Consumers must handle at-least-once delivery — upserts are idempotent; milestone detection should deduplicate
- Keep backward compatibility: the `AppCrawlQueue` can be renamed to `MetadataEnrichmentQueue` in CDK but the Lambda env var `APP_CRAWL_QUEUE_URL` should keep working (or update all references)
- Ensure `cdk synth` succeeds with no errors after changes
- Run `poetry run pytest tests/ -q` — all existing + new tests must pass
- EventBridge schedules remain **disabled** by default (manual enable for production)
