"""Tests for analyzer.py — Pydantic models, scoring helpers, and integration."""

from unittest.mock import MagicMock

import pytest
from library_layer.analyzer import (
    _chunk_reviews,
    analyze_reviews,
)
from library_layer.models.analyzer_models import (
    AudienceProfile,
    BatchStats,
    ChunkSummary,
    CommunityHealth,
    CompetitiveRef,
    CompetitorRef,
    ContentDepth,
    DevPriority,
    GameReport,
    MonetizationSentiment,
    RefundRisk,
)
from library_layer.utils.scores import (
    compute_hidden_gem_score as _compute_hidden_gem_score,
    compute_sentiment_score as _compute_sentiment_score,
    compute_sentiment_trend as _compute_sentiment_trend,
    sentiment_label as _sentiment_label,
)
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Helper to build a minimal valid GameReport (all required fields)
# ---------------------------------------------------------------------------

_MINIMAL_NEW_SECTIONS: dict = {
    "refund_risk": RefundRisk(
        refund_language_frequency="none",
        primary_refund_drivers=[],
        risk_level="low",
    ),
    "community_health": CommunityHealth(
        overall="not_applicable",
        signals=[],
        multiplayer_population="not_applicable",
    ),
    "monetization_sentiment": MonetizationSentiment(
        overall="not_applicable",
        signals=[],
        dlc_sentiment="not_applicable",
    ),
    "content_depth": ContentDepth(
        perceived_length="medium",
        replayability="medium",
        value_perception="good",
        signals=[],
    ),
}


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
    assert summary.technical_issues == []
    assert summary.refund_signals == []
    assert summary.community_health == []
    assert summary.monetization_sentiment == []
    assert summary.content_depth == []
    assert summary.batch_stats.positive_count == 0
    assert summary.batch_stats.negative_count == 0
    assert summary.batch_stats.avg_playtime_hours == 0.0
    assert summary.batch_stats.high_playtime_count == 0
    assert summary.batch_stats.early_access_count == 0
    assert summary.batch_stats.free_key_count == 0


def test_chunk_summary_new_fields() -> None:
    """ChunkSummary accepts all new signal types."""
    summary = ChunkSummary(
        technical_issues=["FPS drops in large battles"],
        refund_signals=["refunded after 2 hours"],
        community_health=["Discord community is active"],
        monetization_sentiment=["DLC is overpriced"],
        content_depth=["Beat the game in 6 hours"],
    )
    assert len(summary.technical_issues) == 1
    assert len(summary.refund_signals) == 1
    assert len(summary.community_health) == 1
    assert len(summary.monetization_sentiment) == 1
    assert len(summary.content_depth) == 1


def test_batch_stats_new_fields() -> None:
    """BatchStats includes high_playtime_count, early_access_count, free_key_count."""
    stats = BatchStats(
        positive_count=30,
        negative_count=20,
        avg_playtime_hours=15.5,
        high_playtime_count=8,
        early_access_count=3,
        free_key_count=2,
    )
    assert stats.high_playtime_count == 8
    assert stats.early_access_count == 3
    assert stats.free_key_count == 2


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
            design_strengths=["A", "B"],
            gameplay_friction=["X"],
            player_wishlist=["F1"],
            churn_triggers=["T1"],
            dev_priorities=[],
            genre_context="Average for the genre.",
            **_MINIMAL_NEW_SECTIONS,
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
            design_strengths=["A", "B"],
            gameplay_friction=["X"],
            player_wishlist=["F1"],
            churn_triggers=["T1"],
            dev_priorities=[],
            genre_context="Average for the genre.",
            **_MINIMAL_NEW_SECTIONS,
        )


def test_game_report_enforces_list_lengths() -> None:
    """design_strengths min_length=2 — only 1 item should fail."""
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
            design_strengths=["A"],  # min_length=2, only 1 item
            gameplay_friction=["X"],
            player_wishlist=["F1"],
            churn_triggers=["T1"],
            dev_priorities=[],
            genre_context="Average for the genre.",
            **_MINIMAL_NEW_SECTIONS,
        )


def test_game_report_lowered_minimums() -> None:
    """design_strengths min_length=2 allows fewer items for honest reports."""
    report = GameReport(
        game_name="Test",
        total_reviews_analyzed=10,
        overall_sentiment="Mixed",
        sentiment_score=0.5,
        sentiment_trend="stable",
        sentiment_trend_note="Stable.",
        one_liner="A decent game.",
        audience_profile=AudienceProfile(
            ideal_player="Casual player",
            casual_friendliness="medium",
            archetypes=["Explorer", "Builder"],
            not_for=["Speedrunners", "PvP fans"],
        ),
        design_strengths=["One", "Two"],
        gameplay_friction=["One issue"],
        player_wishlist=["One wish"],
        churn_triggers=["One trigger"],
        dev_priorities=[],
        genre_context="Average for the genre.",
        **_MINIMAL_NEW_SECTIONS,
    )
    assert len(report.design_strengths) == 2
    assert len(report.gameplay_friction) == 1


def test_game_report_new_sections() -> None:
    """GameReport includes all new structured sections."""
    report = GameReport(
        game_name="Test",
        total_reviews_analyzed=100,
        overall_sentiment="Mixed",
        sentiment_score=0.5,
        sentiment_trend="stable",
        sentiment_trend_note="Stable.",
        one_liner="A decent game.",
        audience_profile=AudienceProfile(
            ideal_player="Casual player",
            casual_friendliness="medium",
            archetypes=["Explorer", "Builder"],
            not_for=["Speedrunners", "PvP fans"],
        ),
        design_strengths=["Good art", "Solid music"],
        gameplay_friction=["Laggy UI"],
        player_wishlist=["Co-op mode"],
        churn_triggers=["Tutorial is confusing"],
        technical_issues=["Crashes on Mac"],
        refund_risk=RefundRisk(
            refund_language_frequency="rare",
            primary_refund_drivers=["crashes"],
            risk_level="low",
        ),
        community_health=CommunityHealth(
            overall="active",
            signals=["Helpful Discord"],
            multiplayer_population="not_applicable",
        ),
        monetization_sentiment=MonetizationSentiment(
            overall="fair",
            signals=["Fair price"],
            dlc_sentiment="not_applicable",
        ),
        content_depth=ContentDepth(
            perceived_length="medium",
            replayability="medium",
            value_perception="good",
            signals=["20 hours of content"],
        ),
        dev_priorities=[],
        competitive_context=[],
        genre_context="A solid entry in the genre.",
    )
    assert report.refund_risk.risk_level == "low"
    assert report.community_health.overall == "active"
    assert report.monetization_sentiment.overall == "fair"
    assert report.content_depth.perceived_length == "medium"
    assert len(report.technical_issues) == 1


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
# Sentiment trend tests — pure Python, no LLM
# ---------------------------------------------------------------------------


def test_sentiment_trend_improving() -> None:
    """Recent reviews more positive → 'improving'."""
    reviews = (
        [{"voted_up": i < 5, "posted_at": "2025-10-01T00:00:00"} for i in range(10)]
        + [{"voted_up": True, "posted_at": "2026-02-01T00:00:00"} for _ in range(10)]
    )
    trend, note = _compute_sentiment_trend(reviews)
    assert trend == "improving"
    assert "rose" in note.lower()


def test_sentiment_trend_declining() -> None:
    """Recent reviews less positive → 'declining'."""
    reviews = (
        [{"voted_up": True, "posted_at": "2025-10-01T00:00:00"} for _ in range(10)]
        + [{"voted_up": i < 3, "posted_at": "2026-02-01T00:00:00"} for i in range(10)]
    )
    trend, note = _compute_sentiment_trend(reviews)
    assert trend == "declining"
    assert "dropped" in note.lower()


def test_sentiment_trend_stable() -> None:
    """Similar sentiment → 'stable'."""
    reviews = (
        [{"voted_up": True, "posted_at": "2025-10-01T00:00:00"} for _ in range(10)]
        + [{"voted_up": True, "posted_at": "2026-02-01T00:00:00"} for _ in range(10)]
    )
    trend, note = _compute_sentiment_trend(reviews)
    assert trend == "stable"
    assert "steady" in note.lower()


def test_sentiment_trend_insufficient_data() -> None:
    """Too few reviews → 'stable' with note about insufficient data."""
    reviews = [{"voted_up": True, "posted_at": "2026-02-01T00:00:00"} for _ in range(5)]
    trend, note = _compute_sentiment_trend(reviews)
    assert trend == "stable"
    assert "insufficient" in note.lower()


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
        technical_issues=["Occasional FPS drops in dense areas"],
        refund_risk=RefundRisk(
            refund_language_frequency="rare",
            primary_refund_drivers=["performance issues"],
            risk_level="low",
        ),
        community_health=CommunityHealth(
            overall="active",
            signals=["Helpful subreddit", "Active Discord"],
            multiplayer_population="not_applicable",
        ),
        monetization_sentiment=MonetizationSentiment(
            overall="fair",
            signals=["Good value for the price"],
            dlc_sentiment="not_applicable",
        ),
        content_depth=ContentDepth(
            perceived_length="medium",
            replayability="high",
            value_perception="good",
            signals=["40+ hours for completionists"],
        ),
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


def test_analyze_reviews_returns_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_summary = ChunkSummary(batch_stats=BatchStats(positive_count=8, negative_count=2))
    fake_report = _fake_report()

    monkeypatch.setattr("library_layer.analyzer._get_instructor_client", MagicMock)
    monkeypatch.setattr("library_layer.analyzer._summarize_chunk", lambda *_: fake_summary)
    monkeypatch.setattr("library_layer.analyzer._synthesize", lambda *_args, **_kw: fake_report)

    reviews = [
        {"voted_up": True, "playtime_hours": 60, "review_text": "Great game!",
         "votes_helpful": 10, "votes_funny": 0, "posted_at": "2026-01-15T00:00:00",
         "written_during_early_access": False, "received_for_free": False}
        for _ in range(10)
    ]
    result = analyze_reviews(reviews, "Test Game")

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
        "technical_issues",
        "refund_risk",
        "community_health",
        "monetization_sentiment",
        "content_depth",
        "dev_priorities",
        "competitive_context",
        "genre_context",
        "hidden_gem_score",
        "sentiment_trend",
        "sentiment_trend_note",
        "total_reviews_analyzed",
    ):
        assert key in result, f"missing key: {key}"


def test_analyze_reviews_adds_appid(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_summary = ChunkSummary(batch_stats=BatchStats(positive_count=5, negative_count=5))
    fake_report = _fake_report()

    monkeypatch.setattr("library_layer.analyzer._get_instructor_client", MagicMock)
    monkeypatch.setattr("library_layer.analyzer._summarize_chunk", lambda *_: fake_summary)
    monkeypatch.setattr("library_layer.analyzer._synthesize", lambda *_args, **_kw: fake_report)

    reviews = [
        {"voted_up": True, "playtime_hours": 30, "review_text": "Fun!",
         "votes_helpful": 0, "votes_funny": 0, "posted_at": "2026-01-15T00:00:00",
         "written_during_early_access": False, "received_for_free": False}
        for _ in range(5)
    ]
    result = analyze_reviews(reviews, "Test Game", appid=440)

    assert result["appid"] == 440


def test_analyze_reviews_empty_reviews() -> None:
    with pytest.raises(ValueError, match="No reviews to analyze"):
        analyze_reviews([], "Test Game")
