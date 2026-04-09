"""NewReleaseEntry — row shape for the /new-releases feed (mv_new_releases)."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_serializer


class NewReleaseEntry(BaseModel):
    """One row from mv_new_releases. Used by all three lenses."""

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("price_usd")
    def _serialize_price(self, v: Decimal | None) -> float | None:
        # Pydantic's JSON mode serializes Decimal as str by default, which
        # breaks the frontend's `price_usd: number | null` contract and
        # disagrees with every other API endpoint that casts price_usd to
        # float. Force numeric serialization here.
        return float(v) if v is not None else None

    appid: int
    name: str
    slug: str | None = None
    type: str | None = None
    developer: str | None = None
    developer_slug: str | None = None
    publisher: str | None = None
    publisher_slug: str | None = None
    header_image: str | None = None
    release_date: date | None = None
    coming_soon: bool = False
    price_usd: Decimal | None = None
    is_free: bool = False
    review_count: int | None = None
    review_count_english: int | None = None
    positive_pct: int | None = None
    review_score_desc: str | None = None
    discovered_at: datetime
    meta_crawled_at: datetime | None = None
    metadata_pending: bool = False
    days_since_release: int | None = None
    has_analysis: bool = False
    top_tags: list[str] = []
    top_tag_slugs: list[str] = []
    genres: list[str] = []
    genre_slugs: list[str] = []
