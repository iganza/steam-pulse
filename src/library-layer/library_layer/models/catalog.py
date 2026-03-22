"""Catalog domain models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CatalogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    appid: int
    name: str
    meta_status: str = "pending"
    meta_crawled_at: datetime | None = None
    review_count: int | None = None
    review_status: str = "pending"
    review_crawled_at: datetime | None = None
    discovered_at: datetime | None = None
