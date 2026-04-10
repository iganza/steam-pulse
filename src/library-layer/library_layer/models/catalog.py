"""Catalog domain models."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_serializer


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


class CatalogReportEntry(BaseModel):
    """One row from mv_catalog_reports — a game with a completed analysis report."""

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("price_usd", "estimated_revenue_usd")
    def _serialize_decimal(self, v: Decimal | None) -> float | None:
        return float(v) if v is not None else None

    appid: int
    name: str
    slug: str | None = None
    developer: str | None = None
    developer_slug: str | None = None
    header_image: str | None = None
    release_date: date | None = None
    price_usd: Decimal | None = None
    is_free: bool = False
    review_count: int | None = None
    positive_pct: int | None = None
    review_score_desc: str | None = None
    hidden_gem_score: float | None = None
    estimated_revenue_usd: Decimal | None = None
    last_analyzed: datetime
    reviews_analyzed: int | None = None
    top_tags: list[str] = []
    tag_slugs: list[str] = []
    genres: list[str] = []
    genre_slugs: list[str] = []


class AnalysisCandidateEntry(BaseModel):
    """One row from mv_analysis_candidates — a game eligible for analysis."""

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("estimated_revenue_usd")
    def _serialize_decimal(self, v: Decimal | None) -> float | None:
        return float(v) if v is not None else None

    appid: int
    game_name: str
    slug: str | None = None
    developer: str | None = None
    header_image: str | None = None
    review_count: int | None = None
    positive_pct: int | None = None
    review_score_desc: str | None = None
    release_date: date | None = None
    estimated_revenue_usd: Decimal | None = None
    request_count: int = 0
