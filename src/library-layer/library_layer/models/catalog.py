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
    review_cursor: str | None = None
    review_cursor_updated_at: datetime | None = None
    reviews_target: int | None = None
    reviews_completed_at: datetime | None = None
    discovered_at: datetime | None = None

    @property
    def review_not_started(self) -> bool:
        """No cursor in flight and never fully crawled."""
        return self.review_cursor is None and self.reviews_completed_at is None

    @property
    def review_in_progress(self) -> bool:
        """A Steam cursor is saved — next batch is pending dispatch."""
        return self.review_cursor is not None

    @property
    def review_complete(self) -> bool:
        """All reviews fetched at least once (cursor cleared, timestamp set)."""
        return self.review_cursor is None and self.reviews_completed_at is not None
