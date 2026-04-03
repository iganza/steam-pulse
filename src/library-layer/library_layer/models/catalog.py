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
    reviews_completed_at: datetime | None = None
    discovered_at: datetime | None = None

    @property
    def review_not_started(self) -> bool:
        """Reviews have never been fully crawled for this game."""
        return self.reviews_completed_at is None

    @property
    def review_complete(self) -> bool:
        """All reviews fetched at least once (completion timestamp set)."""
        return self.reviews_completed_at is not None
