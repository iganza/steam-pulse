"""Pydantic models for the Phase-4 cross-genre LLM synthesis.

The LLM consumes per-game GameReport rows (Phase-3 output) across a genre
and emits a single GenreSynthesis. Persisted in mv_genre_synthesis.

All models double as the `response_model` passed to instructor's tool_use
schema AND as the on-disk shape stored in the synthesis JSONB column.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Minimum mention_count for a cross-genre friction / wishlist signal.
# Matches the v1 system prompt rule ("mention_count >= 3"). Enforced at
# the schema boundary so instructor/tool_use rejects a weak LLM response
# and triggers a retry instead of silently persisting noise.
SHARED_SIGNAL_MIN_MENTIONS = 3


class FrictionPoint(BaseModel):
    title: str
    description: str
    representative_quote: str
    source_appid: int
    mention_count: int = Field(ge=SHARED_SIGNAL_MIN_MENTIONS)


class WishlistItem(BaseModel):
    title: str
    description: str
    representative_quote: str
    source_appid: int
    mention_count: int = Field(ge=SHARED_SIGNAL_MIN_MENTIONS)


class BenchmarkGame(BaseModel):
    appid: int
    name: str
    why_benchmark: str


class ChurnInsight(BaseModel):
    typical_dropout_hour: float = Field(ge=0)
    primary_reason: str
    representative_quote: str
    source_appid: int


class DevPriority(BaseModel):
    """Phase-4 dev priority — distinct from analyzer_models.DevPriority.

    The per-game DevPriority has `frequency: str` and counts across a single
    game's reviews. This cross-genre version counts mentions across input
    reports, so `frequency` is an integer mention_count.
    """

    action: str
    why_it_matters: str
    frequency: int = Field(ge=1)
    effort: Literal["low", "medium", "high"]


class GenreSynthesis(BaseModel):
    """Phase-4 LLM output schema. Persisted in mv_genre_synthesis.synthesis."""

    narrative_summary: str
    friction_points: list[FrictionPoint] = Field(min_length=1, max_length=20)
    wishlist_items: list[WishlistItem] = Field(min_length=1, max_length=10)
    benchmark_games: list[BenchmarkGame] = Field(min_length=1, max_length=10)
    churn_insight: ChurnInsight
    dev_priorities: list[DevPriority] = Field(min_length=1, max_length=10)


class GenreSynthesisRow(BaseModel):
    """Row shape for mv_genre_synthesis — what the repository returns.

    Fields match the SQL columns 1:1. `avg_positive_pct` and
    `median_review_count` are always defined because the service refuses
    to synthesize below MIN_REPORTS_PER_GENRE.
    """

    slug: str
    display_name: str
    input_appids: list[int]
    input_count: int
    prompt_version: str
    input_hash: str
    synthesis: GenreSynthesis
    narrative_summary: str
    avg_positive_pct: float
    median_review_count: int
    computed_at: datetime
