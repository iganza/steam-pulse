"""Pydantic models for all crawler Lambda event payloads.

CDK / boto3 callers construct these and call .model_dump() as the payload.
The dispatcher validates the raw event dict using TypeAdapter.
"""
from __future__ import annotations

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


DirectRequest = Annotated[
    CrawlAppsRequest | CrawlReviewsRequest | CatalogRefreshRequest,
    Field(discriminator="action"),
]


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
    success: bool
    s3_key: str | None = None
    count: int = 0
    spoke_region: str
    error: str | None = None


class SpokeResponse(BaseModel):
    """Spoke Lambda return value (logged by Lambda, useful for debugging)."""
    appid: int
    task: CrawlTask
    success: bool
    count: int
