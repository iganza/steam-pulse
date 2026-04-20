"""SteamPulse domain event and message models.

SNS events: typed models inheriting from BaseEvent, routed via MessageAttribute filters.
SQS messages: typed models inheriting from BaseSqsMessage, routed by message_type in consumers.

All event/message types are defined here — single source of truth for everything
that flows on queues or topics.
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
    "batch-analysis-complete",
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
    review_score_desc: str | None = None


# --- System Events (published to system-events topic) ---


class BatchAnalysisCompleteEvent(BaseEvent):
    event_type: EventType = "batch-analysis-complete"
    execution_id: str
    appids_total: int = 0


class CatalogRefreshCompleteEvent(BaseEvent):
    event_type: EventType = "catalog-refresh-complete"
    new_games: int
    total_games: int


# ---------------------------------------------------------------------------
# SQS message models
# ---------------------------------------------------------------------------

SqsMessageType = Literal[
    # Email queue
    "waitlist_confirmation",
    # Analysis pipeline (realtime or batch — three-phase analyzer entry point)
    "analysis_request",
    # Phase-4 cross-genre synthesizer (one message = one genre to re-synthesize)
    "genre_synthesis_job",
]

AnalysisMode = Literal["realtime", "batch"]


class BaseSqsMessage(BaseModel):
    """Base class for all SteamPulse SQS messages.

    message_type: discriminator for routing in the consumer Lambda.
                  Typed as SqsMessageType — unknown values fail validation immediately.
    version: schema version — new fields on existing messages MUST have defaults
             so old messages already in the queue don't break consumers.
    """

    message_type: SqsMessageType
    version: int = 1


# --- Email queue messages ---


class WaitlistConfirmationMessage(BaseSqsMessage):
    message_type: SqsMessageType = "waitlist_confirmation"
    email: str


# --- Analysis pipeline messages ---


class AnalysisRequest(BaseSqsMessage):
    """Request to analyze a game through the three-phase LLM pipeline.

    The dispatcher selects backend based on `mode`:
    - "realtime": ConverseBackend, runs all three phases inline
    - "batch": BatchBackend, Step Functions drives phases across multiple invocations

    Both modes execute the same phases, share the same prompts, and write
    to the same chunk_summaries / merged_summaries / reports tables.
    """

    message_type: SqsMessageType = "analysis_request"
    appid: int
    mode: AnalysisMode = "realtime"
    reason: str | None = None  # "bulk_seed" | "admin_reanalyze" | ...


# --- Review crawl dispatch messages ---


class ReviewCrawlMessage(BaseModel):
    """Body sent to ReviewCrawlQ to kick off a review crawl for one appid.

    `source` is informational — the primary crawler's `_dispatch_to_spoke`
    logs it so dashboards can attribute queue volume to new-game onboarding
    vs tier-driven refresh. It does NOT gate analysis: the SQS → spoke →
    `ingest_spoke_reviews` path never calls `_trigger_analysis` regardless
    of source. Analysis is only reachable via the direct-invoke `crawl_reviews`
    path, which takes its own `trigger_analysis` kwarg.
    """

    appid: int
    source: Literal["new_game", "refresh"] = "new_game"


# --- Phase-4 genre synthesis messages ---


class GenreSynthesisJobMessage(BaseSqsMessage):
    """One genre to (re-)synthesize via the Phase-4 LLM pass.

    Published by the weekly EventBridge scan (when a slug's synthesis has
    aged out) and by admins forcing a refresh (e.g. after bumping
    prompt_version).
    """

    message_type: SqsMessageType = "genre_synthesis_job"
    slug: str
    prompt_version: str
