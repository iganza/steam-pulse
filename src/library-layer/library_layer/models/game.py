"""Game domain models."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


class Game(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    appid: int
    name: str
    slug: str
    type: str | None = None
    developer: str | None = None
    publisher: str | None = None
    developers: list[str] = []
    publishers: list[str] = []
    website: str | None = None
    release_date: str | None = None
    coming_soon: bool = False
    price_usd: Decimal | None = None
    is_free: bool = False
    short_desc: str | None = None
    detailed_description: str | None = None
    about_the_game: str | None = None
    review_count: int = 0
    total_positive: int = 0
    total_negative: int = 0
    positive_pct: Decimal | None = None
    review_score_desc: str | None = None
    header_image: str | None = None
    background_image: str | None = None
    required_age: int = 0
    platforms: dict = {}
    supported_languages: str | None = None
    achievements_total: int = 0
    metacritic_score: int | None = None
    crawled_at: datetime | None = None
    data_source: str = "steam_direct"

    @field_validator("release_date", mode="before")
    @classmethod
    def coerce_release_date(cls, v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        return str(v)


class GameSummary(BaseModel):
    """Lightweight projection used in list APIs."""

    model_config = ConfigDict(from_attributes=True)

    appid: int
    name: str
    slug: str
    developer: str | None = None
    header_image: str | None = None
    review_count: int = 0
    positive_pct: int | None = None
    price_usd: Decimal | None = None
    is_free: bool = False
    release_date: str | None = None

    @field_validator("release_date", mode="before")
    @classmethod
    def coerce_release_date(cls, v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        return str(v)
