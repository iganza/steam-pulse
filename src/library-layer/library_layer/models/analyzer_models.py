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
    high_playtime_count: int = 0
    early_access_count: int = 0
    free_key_count: int = 0


class ChunkSummary(BaseModel):
    design_praise: list[str] = []
    gameplay_friction: list[str] = []
    wishlist_items: list[str] = []
    dropout_moments: list[str] = []
    competitor_refs: list[CompetitorRef] = []
    notable_quotes: list[str] = []
    technical_issues: list[str] = []
    refund_signals: list[str] = []
    community_health: list[str] = []
    monetization_sentiment: list[str] = []
    content_depth: list[str] = []
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


class RefundRisk(BaseModel):
    refund_language_frequency: Literal["none", "rare", "moderate", "frequent"]
    primary_refund_drivers: list[str] = Field(default_factory=list, max_length=3)
    risk_level: Literal["low", "medium", "high"]


class CommunityHealth(BaseModel):
    overall: Literal["thriving", "active", "declining", "dead", "not_applicable"]
    signals: list[str] = Field(default_factory=list, max_length=4)
    multiplayer_population: Literal["healthy", "shrinking", "critical", "not_applicable"]


class MonetizationSentiment(BaseModel):
    overall: Literal["fair", "mixed", "predatory", "not_applicable"]
    signals: list[str] = Field(default_factory=list, max_length=3)
    dlc_sentiment: Literal["positive", "mixed", "negative", "not_applicable"]


class ContentDepth(BaseModel):
    perceived_length: Literal["short", "medium", "long", "endless"]
    replayability: Literal["low", "medium", "high"]
    value_perception: Literal["poor", "fair", "good", "excellent"]
    signals: list[str] = Field(default_factory=list, max_length=3)


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
    design_strengths: list[str] = Field(min_length=2, max_length=8)
    gameplay_friction: list[str] = Field(min_length=1, max_length=7)
    player_wishlist: list[str] = Field(min_length=1, max_length=6)
    churn_triggers: list[str] = Field(min_length=1, max_length=4)
    technical_issues: list[str] = Field(default_factory=list, max_length=6)
    refund_risk: RefundRisk
    community_health: CommunityHealth
    monetization_sentiment: MonetizationSentiment
    content_depth: ContentDepth
    dev_priorities: list[DevPriority]
    competitive_context: list[CompetitiveRef] = []
    genre_context: str
    hidden_gem_score: float = Field(ge=0.0, le=1.0, default=0.0)
    appid: int | None = None
