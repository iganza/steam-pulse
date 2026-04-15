"""Smoke tests for /api/analytics/trends/* endpoints."""

import httpx
import pytest

pytestmark = pytest.mark.smoke

TREND_SLUGS = [
    "release-volume",
    "sentiment",
    "genre-share",
    "velocity",
    "pricing",
    "early-access",
    "platforms",
    "engagement",
    "categories",
]

# Endpoints whose matviews may legitimately be empty on some environments
ALLOW_EMPTY_PERIODS = {"engagement"}


# -- Every trend endpoint returns 200 with periods ----------------------------


@pytest.mark.parametrize("slug", TREND_SLUGS)
def test_trend_endpoint_returns_periods(api: httpx.Client, slug: str) -> None:
    r = api.get(f"/api/analytics/trends/{slug}", params={"granularity": "year", "limit": 3})
    assert r.status_code == 200
    data = r.json()
    assert "periods" in data
    if slug not in ALLOW_EMPTY_PERIODS:
        assert len(data["periods"]) > 0


# -- game_type dimension ------------------------------------------------------


@pytest.mark.parametrize("game_type", ["game", "dlc", "all"])
def test_game_type_returns_200(api: httpx.Client, game_type: str) -> None:
    r = api.get(
        "/api/analytics/trends/release-volume",
        params={"granularity": "year", "type": game_type, "limit": 3},
    )
    assert r.status_code == 200


def test_invalid_game_type_returns_400(api: httpx.Client) -> None:
    r = api.get("/api/analytics/trends/release-volume", params={"type": "mod"})
    assert r.status_code == 400


# -- granularity dimension -----------------------------------------------------


@pytest.mark.parametrize("granularity", ["month", "year"])
def test_granularity(api: httpx.Client, granularity: str) -> None:
    r = api.get(
        "/api/analytics/trends/release-volume",
        params={"granularity": granularity, "limit": 3},
    )
    assert r.status_code == 200
    assert len(r.json()["periods"]) > 0


# -- filters -------------------------------------------------------------------


def test_genre_filter(api: httpx.Client) -> None:
    r = api.get(
        "/api/analytics/trends/release-volume",
        params={"granularity": "year", "genre": "action", "limit": 3},
    )
    assert r.status_code == 200
    assert r.json()["filter"]["genre"] == "action"


def test_tag_filter(api: httpx.Client) -> None:
    r = api.get(
        "/api/analytics/trends/release-volume",
        params={"granularity": "year", "tag": "roguelike", "limit": 3},
    )
    assert r.status_code == 200
    assert r.json()["filter"]["tag"] == "roguelike"


def test_genre_plus_tag_returns_400(api: httpx.Client) -> None:
    r = api.get(
        "/api/analytics/trends/release-volume",
        params={"genre": "action", "tag": "roguelike"},
    )
    assert r.status_code == 400


# -- data consistency ---------------------------------------------------------


def test_velocity_buckets_sum_to_total(api: httpx.Client) -> None:
    r = api.get(
        "/api/analytics/trends/velocity", params={"granularity": "year", "limit": 1}
    )
    assert r.status_code == 200
    p = r.json()["periods"][0]
    bucket_sum = (
        p["velocity_under_1"] + p["velocity_1_10"] + p["velocity_10_50"] + p["velocity_50_plus"]
    )
    assert bucket_sum == p["total"]


def test_avg_price_incl_free_differs_from_avg_paid(api: httpx.Client) -> None:
    r = api.get(
        "/api/analytics/trends/pricing", params={"granularity": "year", "limit": 1}
    )
    assert r.status_code == 200
    p = r.json()["periods"][0]
    assert p["avg_price_incl_free"] != p["avg_paid_price"]
