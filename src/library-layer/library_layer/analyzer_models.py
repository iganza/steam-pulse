"""Pydantic models for the two-pass LLM analysis pipeline."""

from typing import Literal

from pydantic import BaseModel, Field


class CompetitorRef(BaseModel):
    game: str
    sentiment: Literal["positive", "negative", "neutral"]
    context: str


class BatchStats(BaseModel):
    positive_count: int = 0
    negative_count: int = 0
    avg_playtime_hours: float = 0.0


class ChunkSummary(BaseModel):
    design_praise: list[str] = []
    gameplay_friction: list[str] = []
    wishlist_items: list[str] = []
    dropout_moments: list[str] = []
    competitor_refs: list[CompetitorRef] = []
    notable_quotes: list[str] = []
    batch_stats: BatchStats = Field(default_factory=BatchStats)


class AudienceProfile(BaseModel):
    ideal_player: str
    casual_friendliness: Literal["low", "medium", "high"]
    archetypes: list[str] = Field(min_length=2, max_length=4)
    not_for: list[str] = Field(min_length=2, max_length=3)


class DevPriority(BaseModel):
    action: str
    why_it_matters: str
    frequency: str
    effort: Literal["low", "medium", "high"]


class CompetitiveRef(BaseModel):
    game: str
    comparison_sentiment: Literal["positive", "negative", "neutral"]
    note: str


class GameReport(BaseModel):
    game_name: str
    total_reviews_analyzed: int
    overall_sentiment: Literal[
        "Overwhelmingly Positive",
        "Very Positive",
        "Mostly Positive",
        "Mixed",
        "Mostly Negative",
        "Very Negative",
        "Overwhelmingly Negative",
    ]
    sentiment_score: float = Field(ge=0.0, le=1.0)
    sentiment_trend: Literal["improving", "stable", "declining"]
    sentiment_trend_note: str
    one_liner: str
    audience_profile: AudienceProfile
    design_strengths: list[str] = Field(min_length=4, max_length=8)
    gameplay_friction: list[str] = Field(min_length=3, max_length=7)
    player_wishlist: list[str] = Field(min_length=3, max_length=6)
    churn_triggers: list[str] = Field(min_length=2, max_length=4)
    dev_priorities: list[DevPriority]
    competitive_context: list[CompetitiveRef] = []
    genre_context: str
    hidden_gem_score: float = Field(ge=0.0, le=1.0, default=0.0)
    appid: int | None = None
