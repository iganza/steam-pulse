"""Review domain model."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Review(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    appid: int
    steam_review_id: str
    author_steamid: str | None = None
    voted_up: bool
    playtime_hours: int = 0
    body: str
    posted_at: datetime | None = None
    language: str | None = None
    votes_helpful: int = 0
    votes_funny: int = 0
    written_during_early_access: bool = False
    received_for_free: bool = False
    crawled_at: datetime | None = None
