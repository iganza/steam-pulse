"""Smoke tests for catalog endpoints: genres, tags, analytics, developers, publishers."""

import httpx
import pytest

pytestmark = pytest.mark.smoke


def test_genres(api: httpx.Client) -> None:
    r = api.get("/api/genres")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0


def test_tags_top(api: httpx.Client) -> None:
    r = api.get("/api/tags/top")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0


def test_tags_grouped(api: httpx.Client) -> None:
    r = api.get("/api/tags/grouped")
    assert r.status_code == 200


def test_price_positioning(api: httpx.Client) -> None:
    r = api.get("/api/analytics/price-positioning", params={"genre": "action"})
    assert r.status_code == 200


def test_release_timing(api: httpx.Client) -> None:
    r = api.get("/api/analytics/release-timing", params={"genre": "action"})
    assert r.status_code == 200


def test_platform_gaps(api: httpx.Client) -> None:
    r = api.get("/api/analytics/platform-gaps", params={"genre": "action"})
    assert r.status_code == 200


def test_tag_trend(api: httpx.Client) -> None:
    r = api.get("/api/tags/roguelike/trend")
    assert r.status_code == 200


def test_developer_analytics(api: httpx.Client) -> None:
    r = api.get("/api/developers/valve/analytics")
    assert r.status_code == 200


def test_publisher_analytics(api: httpx.Client) -> None:
    r = api.get("/api/publishers/valve/analytics")
    assert r.status_code == 200


@pytest.mark.parametrize(
    "kind", ["popular", "top_rated", "hidden_gem", "new_release", "just_analyzed"]
)
def test_discovery_feed(api: httpx.Client, kind: str) -> None:
    r = api.get(f"/api/discovery/{kind}", params={"limit": 8})
    assert r.status_code == 200
    data = r.json()
    assert "games" in data
    assert isinstance(data["games"], list)


def test_discovery_feed_invalid_kind(api: httpx.Client) -> None:
    r = api.get("/api/discovery/not-a-kind")
    assert r.status_code == 422


def test_catalog_stats(api: httpx.Client) -> None:
    r = api.get("/api/catalog/stats")
    assert r.status_code == 200
    data = r.json()
    assert "total_games" in data
    assert isinstance(data["total_games"], int)
    assert data["total_games"] >= 0
