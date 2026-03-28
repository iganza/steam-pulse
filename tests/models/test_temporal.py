"""Tests for GameTemporalContext classification functions and builder."""

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
from library_layer.models.temporal import (
    GameTemporalContext,
    build_temporal_context,
    check_evergreen,
    classify_age_bucket,
    classify_trajectory,
    classify_velocity_trend,
)

# ---------------------------------------------------------------------------
# classify_age_bucket
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (None, None),
        (0, "new"),
        (29, "new"),
        (30, "recent"),
        (179, "recent"),
        (180, "established"),
        (729, "established"),
        (730, "legacy"),
        (3000, "legacy"),
    ],
)
def test_classify_age_bucket(days: int | None, expected: str | None) -> None:
    assert classify_age_bucket(days) == expected


# ---------------------------------------------------------------------------
# classify_velocity_trend
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("existing_trend", "last_30d", "days", "expected"),
    [
        ("accelerating", 0, 200, "dead"),
        ("decelerating", 0, 100, "decelerating"),
        ("accelerating", 5, 100, "accelerating"),
        ("stable", 10, None, "stable"),
    ],
)
def test_classify_velocity_trend(
    existing_trend: str, last_30d: int, days: int | None, expected: str
) -> None:
    assert classify_velocity_trend(existing_trend, last_30d, days) == expected


# ---------------------------------------------------------------------------
# classify_trajectory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("velocity_lifetime", "last_30d", "days", "expected"),
    [
        (60.0, 1800, 90, "viral"),
        (2.0, 120, 400, "slow_build"),
        (5.0, 10, 200, "declining"),
        (None, 0, 500, "dead"),
        (3.0, 80, 300, "steady"),
    ],
)
def test_classify_trajectory(
    velocity_lifetime: float | None, last_30d: int, days: int, expected: str
) -> None:
    assert classify_trajectory(velocity_lifetime, last_30d, days) == expected


# ---------------------------------------------------------------------------
# check_evergreen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days", "last_30d", "expected"),
    [
        (731, 6, True),
        (729, 10, False),
        (800, 4, False),
        (None, 10, False),
    ],
)
def test_check_evergreen(days: int | None, last_30d: int, expected: bool) -> None:
    assert check_evergreen(days, last_30d) == expected


# ---------------------------------------------------------------------------
# build_temporal_context
# ---------------------------------------------------------------------------


def _make_mock_game(
    appid: int = 440,
    release_date: str | None = "2007-10-10",
    coming_soon: bool = False,
    review_count_english: int = 12000,
) -> MagicMock:
    game = MagicMock()
    game.appid = appid
    game.release_date = release_date
    game.coming_soon = coming_soon
    game.review_count_english = review_count_english
    return game


def _make_velocity_data(
    last_30_days: int = 42,
    trend: str = "stable",
) -> dict:
    return {
        "monthly": [],
        "summary": {
            "avg_monthly": 100,
            "last_30_days": last_30_days,
            "last_3_months_avg": 90,
            "peak_month": "2024-01",
            "trend": trend,
        },
    }


def _make_ea_data(
    has_ea: bool = False,
    ea_total: int = 0,
    post_total: int = 0,
    impact_delta: float = 0.0,
) -> dict:
    return {
        "has_ea_reviews": has_ea,
        "early_access": {"total": ea_total, "pct_positive": 70.0},
        "post_launch": {"total": post_total, "pct_positive": 80.0},
        "impact_delta": impact_delta,
        "verdict": "improved" if impact_delta > 0 else "stable",
    }


def test_build_temporal_context_basic() -> None:
    game = _make_mock_game()
    velocity = _make_velocity_data()
    ea = _make_ea_data()

    ctx = build_temporal_context(game, velocity, ea)

    assert isinstance(ctx, GameTemporalContext)
    assert ctx.appid == 440
    assert ctx.release_date == date(2007, 10, 10)
    assert ctx.days_since_release is not None
    assert ctx.days_since_release > 0
    assert ctx.release_age_bucket == "legacy"
    assert ctx.is_coming_soon is False
    assert ctx.has_early_access is False
    assert ctx.ea_fraction is None
    assert ctx.ea_sentiment_delta is None
    assert ctx.review_velocity_lifetime is not None
    assert ctx.review_velocity_last_30d == 42
    assert ctx.velocity_trend == "stable"
    assert ctx.is_evergreen is True
    assert ctx.launch_trajectory in ("steady", "declining", "dead")


def test_build_temporal_context_coming_soon() -> None:
    game = _make_mock_game(coming_soon=True)
    ctx = build_temporal_context(game, _make_velocity_data(), _make_ea_data())

    assert ctx.is_coming_soon is True
    assert ctx.release_date is None
    assert ctx.days_since_release is None


def test_build_temporal_context_with_early_access() -> None:
    game = _make_mock_game()
    ea = _make_ea_data(has_ea=True, ea_total=200, post_total=800, impact_delta=5.5)

    ctx = build_temporal_context(game, _make_velocity_data(), ea)

    assert ctx.has_early_access is True
    assert ctx.ea_fraction == pytest.approx(0.2)
    assert ctx.ea_sentiment_delta == 5.5


def test_build_temporal_context_no_release_date() -> None:
    game = _make_mock_game(release_date=None)
    ctx = build_temporal_context(game, _make_velocity_data(), _make_ea_data())

    assert ctx.release_date is None
    assert ctx.days_since_release is None
    assert ctx.release_age_bucket is None
    assert ctx.review_velocity_lifetime is None


def test_build_temporal_context_recent_game() -> None:
    recent_date = (date.today() - timedelta(days=15)).isoformat()
    game = _make_mock_game(release_date=recent_date, review_count_english=500)
    velocity = _make_velocity_data(last_30_days=100, trend="accelerating")

    ctx = build_temporal_context(game, velocity, _make_ea_data())

    assert ctx.release_age_bucket == "new"
    assert ctx.velocity_trend == "accelerating"
