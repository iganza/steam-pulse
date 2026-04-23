"""Pydantic models for the three-phase LLM analysis pipeline (chunk → merge → synthesize)."""

import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _coerce_json_array(v: object) -> object:
    """Sonnet sometimes serializes nested arrays in tool_use as a string.
    If we get a JSON-encoded string where a list is expected, parse it."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return v
    return v

# Silent-truncation cap for ReviewQuote.text. Sized against Phase 2's
# merge-call context budget: worst case ~1920 quotes per merge batch
# (40 chunks x 15 topics x 3 quotes + 3 notable_quotes), so at 400
# chars each we stay under ~200k tokens including prompt scaffolding.
# 400 chars fits 2-3 English sentences — what an actually-representative
# quote should be. The value is enforced by a field_validator that
# TRUNCATES (never rejects) so a verbose LLM response still lands.
REVIEW_QUOTE_MAX_CHARS = 400


class StorePageAlignment(BaseModel):
    promises_delivered: list[str] = Field(default_factory=list, max_length=4)
    promises_broken: list[str] = Field(default_factory=list, max_length=3)
    hidden_strengths: list[str] = Field(default_factory=list, max_length=3)
    audience_match: Literal["aligned", "partial_mismatch", "significant_mismatch"]
    audience_match_note: str


class CompetitorRef(BaseModel):
    game: str
    sentiment: Literal["positive", "negative", "mixed"]
    context: str


# ---------------------------------------------------------------------------
# Three-phase pipeline models (chunk → merge → synthesize)
# ---------------------------------------------------------------------------


TopicCategory = Literal[
    "design_praise",
    "gameplay_friction",
    "wishlist_items",
    "dropout_moments",
    "technical_issues",
    "refund_signals",
    "community_health",
    "monetization_sentiment",
    "content_depth",
]


class ReviewQuote(BaseModel):
    """A verbatim quote linked back to its source review.

    `text` is silently truncated to `REVIEW_QUOTE_MAX_CHARS` — NOT
    validated. The Phase 2 merge prompt receives every quote from
    every chunk in its input; an unbounded quote field would blow
    the merge context window the first time the LLM copies a long
    review body verbatim. See `REVIEW_QUOTE_MAX_CHARS` for the
    context-budget math.
    """

    text: str
    steam_review_id: str
    voted_up: bool
    playtime_hours: int = 0
    votes_helpful: int = 0

    @field_validator("steam_review_id", mode="before")
    @classmethod
    def _coerce_review_id(cls, v: object) -> str:
        """LLM often returns numeric IDs as int — coerce to str."""
        return str(v)

    @field_validator("text", mode="before")
    @classmethod
    def _truncate_text(cls, v: object) -> object:
        if isinstance(v, str) and len(v) > REVIEW_QUOTE_MAX_CHARS:
            # Trim to the last whitespace inside the window so we don't
            # cut a word in half, then append an ellipsis.
            cut = v[: REVIEW_QUOTE_MAX_CHARS - 1]
            ws = cut.rfind(" ")
            if ws > REVIEW_QUOTE_MAX_CHARS // 2:
                cut = cut[:ws]
            return cut.rstrip() + "…"
        return v


class TopicSignal(BaseModel):
    """A structured topic extracted from a chunk of reviews.

    NOTE on `sentiment`: this is a per-TOPIC tag, not a game-wide sentiment
    score. Game-wide sentiment magnitude is owned by Steam (`positive_pct` /
    `review_score_desc` on the Game row) and is never derived from these tags.
    The topic-level tag is only used to render Topic cards in the UI and to
    weight signals during merge.
    """

    topic: str
    category: TopicCategory
    sentiment: Literal["positive", "negative", "mixed"]
    mention_count: int = Field(ge=1)
    confidence: Literal["low", "medium", "high"]
    summary: str
    quotes: list[ReviewQuote] = Field(default_factory=list)
    avg_playtime_hours: float = 0.0
    avg_helpful_votes: float = 0.0

    @field_validator("quotes", mode="before")
    @classmethod
    def _truncate_quotes(cls, v: object) -> object:
        v = _coerce_json_array(v)
        if isinstance(v, list) and len(v) > 3:
            return v[:3]
        return v


class RichBatchStats(BaseModel):
    positive_count: int = 0
    negative_count: int = 0
    avg_playtime_hours: float = 0.0
    high_playtime_count: int = 0
    early_access_count: int = 0
    free_key_count: int = 0
    date_range_start: str | None = None  # ISO date
    date_range_end: str | None = None


class RichChunkSummary(BaseModel):
    """Phase 1 output — structured topic signals from a chunk of reviews."""

    topics: list[TopicSignal] = Field(default_factory=list)
    competitor_refs: list[CompetitorRef] = Field(default_factory=list)
    notable_quotes: list[ReviewQuote] = Field(default_factory=list)
    batch_stats: RichBatchStats = Field(default_factory=RichBatchStats)

    _coerce_topics = field_validator("topics", mode="before")(_coerce_json_array)
    _coerce_competitor_refs = field_validator("competitor_refs", mode="before")(
        _coerce_json_array
    )

    @field_validator("notable_quotes", mode="before")
    @classmethod
    def _truncate_notable_quotes(cls, v: object) -> object:
        v = _coerce_json_array(v)
        if isinstance(v, list) and len(v) > 3:
            return v[:3]
        return v


class MergedSummary(BaseModel):
    """Phase 2 output — consolidated topic signals from merging chunk summaries."""

    topics: list[TopicSignal] = Field(default_factory=list)
    competitor_refs: list[CompetitorRef] = Field(default_factory=list)
    notable_quotes: list[ReviewQuote] = Field(default_factory=list)
    total_stats: RichBatchStats = Field(default_factory=RichBatchStats)
    merge_level: int = 0
    chunks_merged: int = 1
    source_chunk_ids: list[int] = Field(default_factory=list)

    _coerce_topics = field_validator("topics", mode="before")(_coerce_json_array)
    _coerce_competitor_refs = field_validator("competitor_refs", mode="before")(
        _coerce_json_array
    )

    @field_validator("notable_quotes", mode="before")
    @classmethod
    def _truncate_notable_quotes(cls, v: object) -> object:
        v = _coerce_json_array(v)
        if isinstance(v, list) and len(v) > 5:
            return v[:5]
        return v


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
    comparison_sentiment: Literal["positive", "negative", "mixed"]
    note: str


class RefundSignals(BaseModel):
    """Refund-related language extracted from reviews. NOT a prediction —
    these are observed patterns ('refunded', 'got my money back', etc.)."""

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
    confidence: Literal["low", "medium", "high"] = "medium"
    # Number of reviews mentioning playtime/content depth. Bounded so a broken
    # upstream (LLM or Python) can't emit negative or absurdly large values.
    sample_size: int = Field(default=0, ge=0, le=1_000_000)


class GameReport(BaseModel):
    """LLM-synthesized game intelligence report.

    NOTE: sentiment magnitude (Steam's `positive_pct` / `review_score_desc`) is
    NOT part of this report. Steam owns the sentiment number; this report owns
    the narrative. The two are joined at the API/UI layer, not here.
    """

    game_name: str
    total_reviews_analyzed: int
    sentiment_trend: Literal["improving", "stable", "declining"]
    sentiment_trend_note: str
    sentiment_trend_reliable: bool = False
    # Total reviews across the two 90-day windows used by compute_sentiment_trend.
    # Non-negative by construction — guard anyway.
    sentiment_trend_sample_size: int = Field(default=0, ge=0)
    one_liner: str
    audience_profile: AudienceProfile
    design_strengths: list[str] = Field(min_length=2, max_length=8)
    gameplay_friction: list[str] = Field(min_length=1, max_length=7)
    player_wishlist: list[str] = Field(min_length=1, max_length=6)
    churn_triggers: list[str] = Field(min_length=1, max_length=4)
    technical_issues: list[str] = Field(default_factory=list, max_length=6)
    refund_signals: RefundSignals
    community_health: CommunityHealth
    monetization_sentiment: MonetizationSentiment
    content_depth: ContentDepth
    dev_priorities: list[DevPriority]
    competitive_context: list[CompetitiveRef] = []
    genre_context: str
    hidden_gem_score: float = Field(ge=0.0, le=1.0, default=0.0)
    appid: int | None = None
    store_page_alignment: StorePageAlignment | None = None
    review_date_range_start: str | None = None
    review_date_range_end: str | None = None
