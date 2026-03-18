"""Tests for analyzer.py — Pydantic models, scoring helpers, and integration."""

from unittest.mock import MagicMock

import pytest
from library_layer.analyzer import (
    _chunk_reviews,
    _compute_hidden_gem_score,
    _compute_sentiment_score,
    _sentiment_label,
    analyze_reviews,
)
from library_layer.analyzer_models import (
    AudienceProfile,
    BatchStats,
    ChunkSummary,
    CompetitiveRef,
    CompetitorRef,
    DevPriority,
    GameReport,
)
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Pydantic model tests — no mocks needed
# ---------------------------------------------------------------------------


def test_chunk_summary_defaults() -> None:
    summary = ChunkSummary()
    assert summary.design_praise == []
    assert summary.gameplay_friction == []
    assert summary.wishlist_items == []
    assert summary.dropout_moments == []
    assert summary.competitor_refs == []
    assert summary.notable_quotes == []
    assert summary.batch_stats.positive_count == 0
    assert summary.batch_stats.negative_count == 0
    assert summary.batch_stats.avg_playtime_hours == 0.0


def test_chunk_summary_rejects_invalid_sentiment() -> None:
    with pytest.raises(ValidationError):
        CompetitorRef(game="Hades", sentiment="unknown", context="compared favourably")  # type: ignore[arg-type]


def test_game_report_rejects_sentiment_score_out_of_range() -> None:
    with pytest.raises(ValidationError):
        GameReport(
            game_name="Test",
            total_reviews_analyzed=10,
            overall_sentiment="Mixed",
            sentiment_score=1.5,
            sentiment_trend="stable",
            sentiment_trend_note="N/A",
            one_liner="A game.",
            audience_profile=AudienceProfile(
                ideal_player="Anyone",
                casual_friendliness="medium",
                archetypes=["Gamer", "Explorer"],
                not_for=["Speedrunners", "Completionists"],
            ),
            design_strengths=["A", "B", "C", "D"],
            gameplay_friction=["X", "Y", "Z"],
            player_wishlist=["F1", "F2", "F3"],
            churn_triggers=["T1", "T2"],
            dev_priorities=[],
            genre_context="Average for the genre.",
        )


def test_game_report_rejects_invalid_overall_sentiment() -> None:
    with pytest.raises(ValidationError):
        GameReport(
            game_name="Test",
            total_reviews_analyzed=10,
            overall_sentiment="Positive",  # type: ignore[arg-type]  # not in Literal
            sentiment_score=0.7,
            sentiment_trend="stable",
            sentiment_trend_note="N/A",
            one_liner="A game.",
            audience_profile=AudienceProfile(
                ideal_player="Anyone",
                casual_friendliness="medium",
                archetypes=["Gamer", "Explorer"],
                not_for=["Speedrunners", "Completionists"],
            ),
            design_strengths=["A", "B", "C", "D"],
            gameplay_friction=["X", "Y", "Z"],
            player_wishlist=["F1", "F2", "F3"],
            churn_triggers=["T1", "T2"],
            dev_priorities=[],
            genre_context="Average for the genre.",
        )


def test_game_report_enforces_list_lengths() -> None:
    with pytest.raises(ValidationError):
        GameReport(
            game_name="Test",
            total_reviews_analyzed=10,
            overall_sentiment="Mixed",
            sentiment_score=0.5,
            sentiment_trend="stable",
            sentiment_trend_note="N/A",
            one_liner="A game.",
            audience_profile=AudienceProfile(
                ideal_player="Anyone",
                casual_friendliness="medium",
                archetypes=["Gamer", "Explorer"],
                not_for=["Speedrunners", "Completionists"],
            ),
            design_strengths=["A", "B", "C"],  # min_length=4, only 3 items
            gameplay_friction=["X", "Y", "Z"],
            player_wishlist=["F1", "F2", "F3"],
            churn_triggers=["T1", "T2"],
            dev_priorities=[],
            genre_context="Average for the genre.",
        )


def test_audience_profile_casual_friendliness_literal() -> None:
    with pytest.raises(ValidationError):
        AudienceProfile(
            ideal_player="Anyone",
            casual_friendliness="extreme",  # type: ignore[arg-type]
            archetypes=["Gamer", "Explorer"],
            not_for=["Speedrunners", "Completionists"],
        )


def test_dev_priority_effort_literal() -> None:
    with pytest.raises(ValidationError):
        DevPriority(
            action="Fix it",
            why_it_matters="Revenue",
            frequency="50%",
            effort="critical",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Scoring helper tests — pure Python, no LLM
# ---------------------------------------------------------------------------


def test_compute_sentiment_score_all_positive() -> None:
    chunks = [ChunkSummary(batch_stats=BatchStats(positive_count=10, negative_count=0))]
    assert _compute_sentiment_score(chunks) == 1.0


def test_compute_sentiment_score_mixed() -> None:
    chunks = [ChunkSummary(batch_stats=BatchStats(positive_count=5, negative_count=5))]
    score = _compute_sentiment_score(chunks)
    assert score == pytest.approx(0.5)


def test_compute_sentiment_score_empty() -> None:
    assert _compute_sentiment_score([]) == 0.5


def test_compute_hidden_gem_score_low_reviews() -> None:
    # Low review count + high sentiment should boost score
    score = _compute_hidden_gem_score(total_reviews=100, sentiment_score=0.9)
    assert score > 0.0
    # Very high review count should return 0
    assert _compute_hidden_gem_score(total_reviews=100_000, sentiment_score=0.9) == 0.0


def test_sentiment_label_boundaries() -> None:
    assert _sentiment_label(0.95) == "Overwhelmingly Positive"
    assert _sentiment_label(0.80) == "Very Positive"
    assert _sentiment_label(0.65) == "Mostly Positive"
    assert _sentiment_label(0.45) == "Mixed"
    assert _sentiment_label(0.30) == "Mostly Negative"
    assert _sentiment_label(0.15) == "Very Negative"
    assert _sentiment_label(0.10) == "Overwhelmingly Negative"


def test_chunk_reviews_exact_size() -> None:
    reviews = [{"id": i} for i in range(50)]
    chunks = _chunk_reviews(reviews)
    assert len(chunks) == 1
    assert len(chunks[0]) == 50

    reviews_51 = [{"id": i} for i in range(51)]
    chunks_51 = _chunk_reviews(reviews_51)
    assert len(chunks_51) == 2


def test_chunk_reviews_empty() -> None:
    assert _chunk_reviews([]) == []


# ---------------------------------------------------------------------------
# Integration tests — mocked Instructor client
# ---------------------------------------------------------------------------


def _fake_report() -> GameReport:
    return GameReport(
        game_name="Test Game",
        total_reviews_analyzed=10,
        overall_sentiment="Very Positive",
        sentiment_score=0.8,
        sentiment_trend="stable",
        sentiment_trend_note="Reviews have been consistent over time.",
        one_liner="A polished experience that rewards patient players.",
        audience_profile=AudienceProfile(
            ideal_player="Core gamers who enjoy deliberate mechanics.",
            casual_friendliness="medium",
            archetypes=["Explorer", "Strategist"],
            not_for=["Casual players", "Speedrunners"],
        ),
        design_strengths=[
            "Tight controls",
            "Strong art direction",
            "Rewarding progression",
            "Good audio",
        ],
        gameplay_friction=[
            "Steep learning curve",
            "Poor onboarding",
            "Inventory management issues",
        ],
        player_wishlist=["Co-op mode", "Map editor", "Controller remapping"],
        churn_triggers=["Tutorial failure within first 10 minutes", "Difficulty spike at hour 3"],
        dev_priorities=[
            DevPriority(
                action="Redesign the tutorial flow",
                why_it_matters="High early dropout rate is suppressing word-of-mouth.",
                frequency="~40% of negative reviews",
                effort="medium",
            )
        ],
        competitive_context=[
            CompetitiveRef(
                game="Hades", comparison_sentiment="positive", note="cited as genre benchmark"
            )
        ],
        genre_context="Performs above average for the roguelite genre.",
    )


async def test_analyze_reviews_returns_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_summary = ChunkSummary(batch_stats=BatchStats(positive_count=8, negative_count=2))
    fake_report = _fake_report()

    monkeypatch.setattr("library_layer.analyzer._get_instructor_client", MagicMock)
    monkeypatch.setattr("library_layer.analyzer._summarize_chunk", lambda *_: fake_summary)
    monkeypatch.setattr("library_layer.analyzer._synthesize", lambda *_: fake_report)

    reviews = [
        {"voted_up": True, "playtime_at_review": 3600, "review_text": "Great game!"}
        for _ in range(10)
    ]
    result = await analyze_reviews(reviews, "Test Game")

    assert isinstance(result, dict)
    for key in (
        "game_name",
        "overall_sentiment",
        "sentiment_score",
        "one_liner",
        "audience_profile",
        "design_strengths",
        "gameplay_friction",
        "player_wishlist",
        "churn_triggers",
        "dev_priorities",
        "competitive_context",
        "genre_context",
        "hidden_gem_score",
        "sentiment_trend",
        "sentiment_trend_note",
        "total_reviews_analyzed",
    ):
        assert key in result, f"missing key: {key}"


async def test_analyze_reviews_adds_appid(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_summary = ChunkSummary(batch_stats=BatchStats(positive_count=5, negative_count=5))
    fake_report = _fake_report()

    monkeypatch.setattr("library_layer.analyzer._get_instructor_client", MagicMock)
    monkeypatch.setattr("library_layer.analyzer._summarize_chunk", lambda *_: fake_summary)
    monkeypatch.setattr("library_layer.analyzer._synthesize", lambda *_: fake_report)

    reviews = [
        {"voted_up": True, "playtime_at_review": 1800, "review_text": "Fun!"} for _ in range(5)
    ]
    result = await analyze_reviews(reviews, "Test Game", appid=440)

    assert result["appid"] == 440


async def test_analyze_reviews_empty_reviews() -> None:
    with pytest.raises(ValueError, match="No reviews to analyze"):
        await analyze_reviews([], "Test Game")
