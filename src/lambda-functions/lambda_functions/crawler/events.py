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
    max_reviews: int = 2000


class CatalogRefreshRequest(BaseModel):
    action: Literal["catalog_refresh"]


DirectRequest = Annotated[
    CrawlAppsRequest | CrawlReviewsRequest | CatalogRefreshRequest,
    Field(discriminator="action"),
]
