"""Pydantic models for all crawler Lambda event payloads.

CDK / boto3 callers construct these and call .model_dump() as the payload.
The dispatcher validates the raw event dict using TypeAdapter.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class CrawlAppsRequest(BaseModel):
    action: Literal["crawl_apps"]
    appid: int


class CrawlReviewsRequest(BaseModel):
    action: Literal["crawl_reviews"]
    appid: int
    max_reviews: int | None = None  # None = fetch all reviews


class CatalogRefreshRequest(BaseModel):
    action: Literal["catalog_refresh"]


class ReviewBackfillRequest(BaseModel):
    action: Literal["review_backfill"]
    limit: int = 1000


DirectRequest = Annotated[
    CrawlAppsRequest | CrawlReviewsRequest | CatalogRefreshRequest | ReviewBackfillRequest,
    Field(discriminator="action"),
]


# ── Spoke payload contracts ─────────────────────────────────────────────────

CrawlTask = Literal["metadata", "reviews"]


# ── Spoke request models (Primary → Spoke) ──────────────────────────────────

class MetadataSpokeRequest(BaseModel):
    """Primary → Spoke: async Lambda invoke payload for metadata crawl."""
    appid: int
    task: CrawlTask = "metadata"


class ReviewSpokeRequest(BaseModel):
    """Primary → Spoke: async Lambda invoke payload for review crawl."""
    appid: int
    task: CrawlTask = "reviews"
    cursor: str = "*"
    max_reviews: int | None = None  # None = use BATCH_SIZE


# ── Spoke result models (Spoke → Ingest via SQS) ────────────────────────────

class MetadataSpokeResult(BaseModel):
    """Spoke → Primary: SQS message body for completed metadata fetch."""
    appid: int
    task: CrawlTask = "metadata"
    success: bool
    s3_key: str | None = None
    count: int = 0
    spoke_region: str
    error: str | None = None


class ReviewSpokeResult(BaseModel):
    """Spoke → Primary: SQS message body for completed review batch fetch."""
    appid: int
    task: CrawlTask = "reviews"
    success: bool
    s3_key: str | None = None
    count: int = 0
    spoke_region: str
    next_cursor: str | None = None  # None = Steam exhausted; non-None = more pages remain
    error: str | None = None


class SpokeResponse(BaseModel):
    """Spoke Lambda return value (logged by Lambda, useful for debugging)."""
    appid: int
    task: CrawlTask
    success: bool
    count: int
