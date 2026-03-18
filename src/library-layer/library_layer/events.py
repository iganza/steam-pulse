"""SteamPulse domain event models for SNS pub/sub pipeline.

All event types are defined here as Pydantic models inheriting from BaseEvent.
The event_type field doubles as the SNS MessageAttribute for filter-based routing.
"""

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
