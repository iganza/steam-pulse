"""Review domain model."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Review(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    appid: int
    steam_review_id: str
    voted_up: bool
    playtime_hours: int = 0
    body: str
    posted_at: datetime | None = None
    crawled_at: datetime | None = None
