"""Game domain models."""

import json
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
    developer_slug: str | None = None
    publisher: str | None = None
    publisher_slug: str | None = None
    developers: list[str] = []
    publishers: list[str] = []
    website: str | None = None
    release_date: str | None = None
    release_date_raw: str | None = None
    coming_soon: bool = False
    price_usd: Decimal | None = None
    is_free: bool = False
    short_desc: str | None = None
    detailed_description: str | None = None
    about_the_game: str | None = None
    review_count: int = 0
    review_count_english: int = 0
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
    deck_compatibility: int | None = None
    deck_test_results: list[dict] = []
    # content / input (0041)
    content_descriptor_ids: list[int] = []
    content_descriptor_notes: str | None = None
    controller_support: str | None = None
    # DLC / franchise
    dlc_appids: list[int] = []
    parent_appid: int | None = None
    # media
    capsule_image: str | None = None
    # engagement
    recommendations_total: int | None = None
    # support
    support_url: str | None = None
    support_email: str | None = None
    legal_notice: str | None = None
    # system requirements
    requirements_windows: str | None = None
    requirements_mac: str | None = None
    requirements_linux: str | None = None
    hidden_gem_score: float | None = None
    last_analyzed: datetime | None = None
    crawled_at: datetime | None = None
    meta_crawled_at: datetime | None = None
    review_crawled_at: datetime | None = None
    reviews_completed_at: datetime | None = None
    tags_crawled_at: datetime | None = None
    data_source: str = "steam_direct"
    # Boxleiter v1 revenue estimates — gross, pre-Steam-cut, ±50%
    estimated_owners: int | None = None
    estimated_revenue_usd: Decimal | None = None
    revenue_estimate_method: str | None = None
    revenue_estimate_computed_at: datetime | None = None
    revenue_estimate_reason: str | None = None
    has_early_access_reviews: bool = False

    @field_validator("developers", "publishers", mode="before")
    @classmethod
    def coerce_list(cls, v: object) -> list[str]:
        if v is None:
            return []
        return v  # type: ignore[return-value]

    @field_validator("content_descriptor_ids", "dlc_appids", mode="before")
    @classmethod
    def coerce_int_list(cls, v: object) -> list[int]:
        if v is None:
            return []
        if isinstance(v, str):
            return json.loads(v)
        return v  # type: ignore[return-value]

    @field_validator(
        "review_count",
        "review_count_english",
        "total_positive",
        "total_negative",
        "required_age",
        "achievements_total",
        mode="before",
    )
    @classmethod
    def coerce_int(cls, v: object) -> int:
        if v is None:
            return 0
        return v  # type: ignore[return-value]

    @field_validator("platforms", mode="before")
    @classmethod
    def coerce_dict(cls, v: object) -> dict:
        if v is None:
            return {}
        return v  # type: ignore[return-value]

    @field_validator("deck_test_results", mode="before")
    @classmethod
    def coerce_deck_results(cls, v: object) -> list[dict]:
        if v is None:
            return []
        if isinstance(v, str):
            return json.loads(v)
        return v  # type: ignore[return-value]

    @field_validator("release_date", mode="before")
    @classmethod
    def coerce_release_date(cls, v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        return str(v)

    @property
    def deck_status(self) -> str:
        """Human-readable Steam Deck compatibility status."""
        return {0: "Unknown", 1: "Unsupported", 2: "Playable", 3: "Verified"}.get(
            self.deck_compatibility or 0, "Unknown"
        )


class GameSummary(BaseModel):
    """Lightweight projection used in list APIs."""

    model_config = ConfigDict(from_attributes=True)

    appid: int
    name: str
    slug: str
    developer: str | None = None
    publisher: str | None = None
    publisher_slug: str | None = None
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
