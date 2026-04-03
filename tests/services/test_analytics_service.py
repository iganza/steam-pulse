"""Tests for AnalyticsService — business logic with mocked repository."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from library_layer.services.analytics_service import AnalyticsService


@pytest.fixture
def mock_repo() -> MagicMock:
    return MagicMock()


@pytest.fixture
def svc(mock_repo: MagicMock) -> AnalyticsService:
    return AnalyticsService(mock_repo)


# -------------------------------------------------------------------
# _validate_granularity
# -------------------------------------------------------------------


def test_validate_granularity_valid(svc: AnalyticsService) -> None:
    for g in ("week", "month", "quarter", "year"):
        assert svc._validate_granularity(g) == g


def test_validate_granularity_invalid(svc: AnalyticsService) -> None:
    with pytest.raises(ValueError, match="Invalid granularity"):
        svc._validate_granularity("daily")


# -------------------------------------------------------------------
# _format_period
# -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dt", "granularity", "expected"),
    [
        (datetime(2024, 1, 1), "year", "2024"),
        (datetime(2024, 3, 15), "quarter", "2024-Q1"),
        (datetime(2024, 7, 1), "quarter", "2024-Q3"),
        (datetime(2024, 6, 1), "month", "2024-06"),
        (datetime(2024, 1, 8), "week", "2024-W02"),
    ],
)
def test_format_period(svc: AnalyticsService, dt: datetime, granularity: str, expected: str) -> None:
    assert svc._format_period(dt, granularity) == expected


# -------------------------------------------------------------------
# _compute_trend
# -------------------------------------------------------------------


def test_trend_increasing(svc: AnalyticsService) -> None:
    values = [10, 10, 10, 10, 20, 25, 30]
    assert svc._compute_trend(values) == "increasing"


def test_trend_decreasing(svc: AnalyticsService) -> None:
    values = [50, 50, 50, 50, 10, 8, 5]
    assert svc._compute_trend(values) == "decreasing"


def test_trend_stable(svc: AnalyticsService) -> None:
    values = [10, 10, 10, 10, 10, 10, 10]
    assert svc._compute_trend(values) == "stable"


def test_trend_too_few(svc: AnalyticsService) -> None:
    assert svc._compute_trend([10, 20, 30]) == "stable"


# -------------------------------------------------------------------
# get_release_volume
# -------------------------------------------------------------------


def test_get_release_volume(svc: AnalyticsService, mock_repo: MagicMock) -> None:
    mock_repo.find_release_volume_rows.return_value = [
        {"period": datetime(2024, 1, 1), "releases": 100, "avg_sentiment": 71.5, "avg_reviews": 400, "free_count": 20},
        {"period": datetime(2024, 2, 1), "releases": 120, "avg_sentiment": 68.0, "avg_reviews": 350, "free_count": 25},
    ]
    result = svc.get_release_volume(granularity="month", genre_slug="action")
    assert result["granularity"] == "month"
    assert result["filter"]["genre"] == "action"
    assert len(result["periods"]) == 2
    assert result["periods"][0]["period"] == "2024-01"
    assert result["summary"]["total_releases"] == 220


# -------------------------------------------------------------------
# get_sentiment_distribution
# -------------------------------------------------------------------


def test_get_sentiment_distribution(svc: AnalyticsService, mock_repo: MagicMock) -> None:
    mock_repo.find_sentiment_distribution_rows.return_value = [
        {"period": datetime(2024, 1, 1), "total": 100, "positive_count": 60, "mixed_count": 30,
         "negative_count": 10, "avg_sentiment": 70.0, "avg_metacritic": 72.0},
    ]
    result = svc.get_sentiment_distribution(granularity="month")
    p = result["periods"][0]
    assert p["positive_pct"] == 60.0
    assert p["avg_metacritic"] == 72.0


# -------------------------------------------------------------------
# get_genre_share
# -------------------------------------------------------------------


def test_get_genre_share_buckets_other(svc: AnalyticsService, mock_repo: MagicMock) -> None:
    mock_repo.find_genre_share_rows.return_value = [
        {"period": datetime(2024, 1, 1), "genre": "Action", "genre_slug": "action", "releases": 50},
        {"period": datetime(2024, 1, 1), "genre": "Indie", "genre_slug": "indie", "releases": 30},
        {"period": datetime(2024, 1, 1), "genre": "RPG", "genre_slug": "rpg", "releases": 20},
    ]
    result = svc.get_genre_share(granularity="year", top_n=2)
    assert "Other" in result["genres"]
    p = result["periods"][0]
    assert p["shares"]["Action"] == 0.5
    assert p["shares"]["Indie"] == 0.3
    assert p["shares"]["Other"] == 0.2


# -------------------------------------------------------------------
# get_price_trend
# -------------------------------------------------------------------


def test_get_price_trend_free_pct(svc: AnalyticsService, mock_repo: MagicMock) -> None:
    mock_repo.find_price_trend_rows.return_value = [
        {"period": datetime(2024, 1, 1), "total": 200, "avg_paid_price": 18.50,
         "avg_price_incl_free": 14.00, "free_count": 40},
    ]
    result = svc.get_price_trend(granularity="year")
    assert result["periods"][0]["free_pct"] == 20.0


# -------------------------------------------------------------------
# get_ea_trend
# -------------------------------------------------------------------


def test_get_ea_trend_ea_pct(svc: AnalyticsService, mock_repo: MagicMock) -> None:
    mock_repo.find_ea_trend_rows.return_value = [
        {"period": datetime(2024, 1, 1), "total_releases": 100, "ea_count": 25,
         "ea_avg_sentiment": 74.0, "non_ea_avg_sentiment": 68.0},
    ]
    result = svc.get_ea_trend(granularity="year")
    assert result["periods"][0]["ea_pct"] == 25.0


# -------------------------------------------------------------------
# get_platform_trend
# -------------------------------------------------------------------


def test_get_platform_trend_pcts(svc: AnalyticsService, mock_repo: MagicMock) -> None:
    mock_repo.find_platform_trend_rows.return_value = [
        {"period": datetime(2024, 1, 1), "total": 200, "windows_count": 200,
         "mac_count": 60, "linux_count": 40, "deck_verified": 50,
         "deck_playable": 30, "deck_unsupported": 20},
    ]
    result = svc.get_platform_trend(granularity="year")
    p = result["periods"][0]
    assert p["mac_pct"] == 30.0
    assert p["linux_pct"] == 20.0
    assert p["deck_verified_pct"] == 25.0


# -------------------------------------------------------------------
# get_engagement_depth
# -------------------------------------------------------------------


def test_get_engagement_depth_no_data(svc: AnalyticsService, mock_repo: MagicMock) -> None:
    mock_repo.find_engagement_depth_rows.return_value = []
    result = svc.get_engagement_depth(granularity="year")
    assert result["data_available"] is False
    assert result["periods"] == []


def test_get_engagement_depth_with_data(svc: AnalyticsService, mock_repo: MagicMock) -> None:
    mock_repo.find_engagement_depth_rows.return_value = [
        {"period": "2024-01-01", "total_reviews": 1000, "playtime_under_2h": 150,
         "playtime_2_10h": 350, "playtime_10_50h": 300, "playtime_50_200h": 150,
         "playtime_200h_plus": 50},
    ]
    result = svc.get_engagement_depth(granularity="year")
    assert result["data_available"] is True
    p = result["periods"][0]
    assert p["playtime_under_2h_pct"] == 15.0
    assert p["playtime_200h_plus_pct"] == 5.0


# -------------------------------------------------------------------
# get_category_trend
# -------------------------------------------------------------------


def test_get_category_trend_adoption(svc: AnalyticsService, mock_repo: MagicMock) -> None:
    mock_repo.find_category_trend_rows.return_value = [
        {"period": datetime(2024, 1, 1), "category_name": "Single-player", "games_with_category": 180},
        {"period": datetime(2024, 1, 1), "category_name": "Multi-player", "games_with_category": 60},
    ]
    mock_repo.find_release_volume_rows.return_value = [
        {"period": datetime(2024, 1, 1), "releases": 200, "avg_sentiment": None, "avg_reviews": None, "free_count": 0},
    ]
    result = svc.get_category_trend(granularity="year", top_n=4)
    p = result["periods"][0]
    assert p["adoption"]["Single-player"] == 0.9
    assert p["adoption"]["Multi-player"] == 0.3


# -------------------------------------------------------------------
# Empty input — no division errors
# -------------------------------------------------------------------


def test_empty_rows_no_crash(svc: AnalyticsService, mock_repo: MagicMock) -> None:
    mock_repo.find_release_volume_rows.return_value = []
    result = svc.get_release_volume(granularity="month")
    assert result["periods"] == []
    assert result["summary"]["total_releases"] == 0

    mock_repo.find_sentiment_distribution_rows.return_value = []
    assert svc.get_sentiment_distribution()["periods"] == []

    mock_repo.find_genre_share_rows.return_value = []
    assert svc.get_genre_share()["periods"] == []

    mock_repo.find_velocity_distribution_rows.return_value = []
    assert svc.get_velocity_distribution()["periods"] == []

    mock_repo.find_price_trend_rows.return_value = []
    assert svc.get_price_trend()["periods"] == []

    mock_repo.find_ea_trend_rows.return_value = []
    assert svc.get_ea_trend()["periods"] == []

    mock_repo.find_platform_trend_rows.return_value = []
    assert svc.get_platform_trend()["periods"] == []

    mock_repo.find_category_trend_rows.return_value = []
    mock_repo.find_release_volume_rows.return_value = []
    assert svc.get_category_trend()["periods"] == []
