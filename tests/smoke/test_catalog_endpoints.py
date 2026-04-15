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
