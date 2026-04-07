"""Tests for analyzer.py — Pydantic models, scoring helpers, and integration."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from library_layer.analyzer import (
    _build_synthesis_user_message,
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
    RefundSignals,
)
from library_layer.models.metadata import GameMetadataContext
from library_layer.utils.scores import (
    compute_hidden_gem_score as _compute_hidden_gem_score,
)
from library_layer.utils.scores import (
    compute_sentiment_trend as _compute_sentiment_trend,
)
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Helper to build a minimal valid GameReport (all required fields)
# ---------------------------------------------------------------------------

_MINIMAL_NEW_SECTIONS: dict = {
    "refund_signals": RefundSignals(
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


def test_game_report_no_longer_has_sentiment_score_field() -> None:
    """sentiment_score / overall_sentiment were dropped — Steam owns sentiment magnitude."""
    assert "sentiment_score" not in GameReport.model_fields
    assert "overall_sentiment" not in GameReport.model_fields


def test_game_report_enforces_list_lengths() -> None:
    """design_strengths min_length=2 — only 1 item should fail."""
    with pytest.raises(ValidationError):
        GameReport(
            game_name="Test",
            total_reviews_analyzed=10,
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
        refund_signals=RefundSignals(
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
    assert report.refund_signals.risk_level == "low"
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


def test_compute_hidden_gem_score_quality_and_scarcity() -> None:
    # Steam-derived: low review count + high positive_pct should boost score
    score = _compute_hidden_gem_score(positive_pct=95, review_count=500)
    assert score > 0.0
    # Above 10k reviews → not a hidden gem
    assert _compute_hidden_gem_score(positive_pct=95, review_count=15_000) == 0.0
    # Below 80% positive → not a gem regardless of scarcity
    assert _compute_hidden_gem_score(positive_pct=70, review_count=500) == 0.0
    # Missing inputs → safe zero
    assert _compute_hidden_gem_score(None, 500) == 0.0
    assert _compute_hidden_gem_score(95, None) == 0.0


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


def _trend_dates() -> tuple[str, str]:
    """Return (prior_date, recent_date) relative to today so tests don't rot."""
    from datetime import datetime, timedelta, UTC

    now = datetime.now(UTC)
    recent = (now - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")
    prior = (now - timedelta(days=120)).strftime("%Y-%m-%dT00:00:00")
    return prior, recent


def test_sentiment_trend_improving() -> None:
    """Recent reviews more positive → 'improving'."""
    prior, recent = _trend_dates()
    reviews = [{"voted_up": i < 5, "posted_at": prior} for i in range(10)] + [
        {"voted_up": True, "posted_at": recent} for _ in range(10)
    ]
    result = _compute_sentiment_trend(reviews)
    assert result["trend"] == "improving"
    assert "rose" in result["note"].lower()
    assert result["sample_size"] == 20
    assert result["reliable"] is False  # 10 + 10 < 50 each


def test_sentiment_trend_declining() -> None:
    """Recent reviews less positive → 'declining'."""
    prior, recent = _trend_dates()
    reviews = [{"voted_up": True, "posted_at": prior} for _ in range(10)] + [
        {"voted_up": i < 3, "posted_at": recent} for i in range(10)
    ]
    result = _compute_sentiment_trend(reviews)
    assert result["trend"] == "declining"
    assert "dropped" in result["note"].lower()


def test_sentiment_trend_stable() -> None:
    """Similar sentiment → 'stable'."""
    prior, recent = _trend_dates()
    reviews = [{"voted_up": True, "posted_at": prior} for _ in range(10)] + [
        {"voted_up": True, "posted_at": recent} for _ in range(10)
    ]
    result = _compute_sentiment_trend(reviews)
    assert result["trend"] == "stable"
    assert "steady" in result["note"].lower()


def test_sentiment_trend_reliable_when_both_windows_have_50() -> None:
    """50+ reviews per window → reliable=True."""
    prior, recent = _trend_dates()
    reviews = [{"voted_up": True, "posted_at": prior} for _ in range(50)] + [
        {"voted_up": True, "posted_at": recent} for _ in range(50)
    ]
    result = _compute_sentiment_trend(reviews)
    assert result["reliable"] is True
    assert result["sample_size"] == 100


def test_sentiment_trend_insufficient_data() -> None:
    """Too few reviews → 'stable' with note about insufficient data."""
    reviews = [{"voted_up": True, "posted_at": "2026-02-01T00:00:00"} for _ in range(5)]
    result = _compute_sentiment_trend(reviews)
    assert result["trend"] == "stable"
    assert "insufficient" in result["note"].lower()
    assert result["reliable"] is False


# ---------------------------------------------------------------------------
# Integration tests — mocked Instructor client
# ---------------------------------------------------------------------------


def _fake_report() -> GameReport:
    return GameReport(
        game_name="Test Game",
        total_reviews_analyzed=10,
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
        refund_signals=RefundSignals(
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
        {
            "voted_up": True,
            "playtime_hours": 60,
            "review_text": "Great game!",
            "votes_helpful": 10,
            "votes_funny": 0,
            "posted_at": "2026-01-15T00:00:00",
            "written_during_early_access": False,
            "received_for_free": False,
        }
        for _ in range(10)
    ]
    result = analyze_reviews(reviews, "Test Game")

    assert isinstance(result, dict)
    for key in (
        "game_name",
        "one_liner",
        "audience_profile",
        "design_strengths",
        "gameplay_friction",
        "player_wishlist",
        "churn_triggers",
        "technical_issues",
        "refund_signals",
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
    # The data-source-clarity refactor removed these — Steam owns sentiment magnitude.
    assert "sentiment_score" not in result
    assert "overall_sentiment" not in result


def test_analyze_reviews_adds_appid(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_summary = ChunkSummary(batch_stats=BatchStats(positive_count=5, negative_count=5))
    fake_report = _fake_report()

    monkeypatch.setattr("library_layer.analyzer._get_instructor_client", MagicMock)
    monkeypatch.setattr("library_layer.analyzer._summarize_chunk", lambda *_: fake_summary)
    monkeypatch.setattr("library_layer.analyzer._synthesize", lambda *_args, **_kw: fake_report)

    reviews = [
        {
            "voted_up": True,
            "playtime_hours": 30,
            "review_text": "Fun!",
            "votes_helpful": 0,
            "votes_funny": 0,
            "posted_at": "2026-01-15T00:00:00",
            "written_during_early_access": False,
            "received_for_free": False,
        }
        for _ in range(5)
    ]
    result = analyze_reviews(reviews, "Test Game", appid=440)

    assert result["appid"] == 440


def test_analyze_reviews_empty_reviews() -> None:
    with pytest.raises(ValueError, match="No reviews to analyze"):
        analyze_reviews([], "Test Game")


# ---------------------------------------------------------------------------
# _build_synthesis_user_message — metadata injection tests
# ---------------------------------------------------------------------------

_MINIMAL_AGGREGATED: dict = {
    "design_praise": [],
    "gameplay_friction": [],
    "wishlist_items": [],
    "dropout_moments": [],
    "competitor_refs": [],
    "notable_quotes": [],
    "technical_issues": [],
    "refund_signals": [],
    "community_health": [],
    "monetization_sentiment": [],
    "content_depth": [],
    "total_stats": {
        "positive_count": 5,
        "negative_count": 5,
        "avg_playtime_hours": 10.0,
        "high_playtime_count": 0,
        "early_access_count": 0,
        "free_key_count": 0,
    },
}


def _call_synthesis_msg(metadata: GameMetadataContext | None = None) -> str:
    return _build_synthesis_user_message(
        _MINIMAL_AGGREGATED,
        "Test Game",
        total_reviews=10,
        hidden_gem_score=0.3,
        sentiment_trend="stable",
        sentiment_trend_note="No change",
        steam_positive_pct=72,
        steam_review_score_desc="Mostly Positive",
        metadata=metadata,
    )


def test_synthesis_message_with_metadata_includes_store_description() -> None:
    meta = GameMetadataContext(
        short_desc="Short",
        about_the_game="Full description here",
        price_usd=Decimal("9.99"),
        platforms=["Windows"],
        tags=["RPG"],
        genres=["Action"],
        deck_status="Verified",
    )
    msg = _call_synthesis_msg(meta)
    assert "<store_description>" in msg
    assert "Full description here" in msg
    assert "store_page_alignment" in msg


def test_synthesis_message_without_metadata_omits_store_description() -> None:
    msg = _call_synthesis_msg(None)
    assert "<store_description>" not in msg
    assert "store_page_alignment" not in msg


def test_synthesis_message_metadata_none_about_omits_both_blocks() -> None:
    meta = GameMetadataContext(
        short_desc="Short",
        about_the_game=None,
        price_usd=Decimal("9.99"),
    )
    msg = _call_synthesis_msg(meta)
    # both store_description and store_page_alignment omitted when about_the_game is None
    assert "<store_description>" not in msg
    assert "store_page_alignment" not in msg


def test_synthesis_message_metadata_fields_in_game_context() -> None:
    meta = GameMetadataContext(
        price_usd=Decimal("14.99"),
        is_free=False,
        platforms=["Windows", "Mac"],
        deck_status="Playable",
        genres=["Indie"],
        tags=["Roguelike", "Action"],
        achievements_total=30,
        metacritic_score=78,
    )
    msg = _call_synthesis_msg(meta)
    assert "14.99" in msg
    assert "Windows, Mac" in msg
    assert "Playable" in msg
    assert "Indie" in msg
    assert "Roguelike, Action" in msg
    assert "30" in msg
    assert "78" in msg
