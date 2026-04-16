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


def test_discovery_feed_row_shape(api: httpx.Client) -> None:
    """Validate the response row shape so a silent field rename / serialization
    regression (Decimal, datetime) fails loudly instead of slipping through."""
    r = api.get("/api/discovery/popular", params={"limit": 8})
    assert r.status_code == 200
    games = r.json()["games"]
    assert games, "popular feed should return at least one game"
    g = games[0]
    for key in (
        "appid",
        "name",
        "slug",
        "review_count",
        "positive_pct",
        "is_early_access",
        # 0048: English-only post-release split — homepage cards consume these.
        "review_count_post_release",
        "positive_pct_post_release",
        "review_score_desc_post_release",
        "has_early_access_reviews",
        "coming_soon",
    ):
        assert key in g, f"missing {key} in response row"
    # Type assertions that would catch Decimal / datetime serialization bugs
    # (stdlib json.dumps used by JSONResponse can't serialize those, so a
    # regression reintroduces a 500 which is already caught; these assertions
    # catch the subtler case of JSONResponse being swapped for a plain dict
    # where FastAPI's encoder silently emits strings for Decimal).
    if g.get("price_usd") is not None:
        assert isinstance(g["price_usd"], (int, float)), "price_usd must be a number"
    if g.get("last_analyzed") is not None:
        assert isinstance(g["last_analyzed"], str), "last_analyzed must be a string"
    if g.get("release_date") is not None:
        assert isinstance(g["release_date"], str), "release_date must be a string"


def test_discovery_feed_cache_headers(api: httpx.Client) -> None:
    """Cache-Control s-maxage must stay on the response — CDN freshness depends on it."""
    r = api.get("/api/discovery/popular")
    assert r.status_code == 200
    assert "s-maxage=300" in r.headers.get("cache-control", "")


def test_discovery_feed_limit_upper_bound(api: httpx.Client) -> None:
    """limit is validated 1..24 — anything over should 422, not silently truncate."""
    r = api.get("/api/discovery/popular", params={"limit": 25})
    assert r.status_code == 422


def test_catalog_stats(api: httpx.Client) -> None:
    r = api.get("/api/catalog/stats")
    assert r.status_code == 200
    data = r.json()
    assert "total_games" in data
    assert isinstance(data["total_games"], int)
    assert data["total_games"] >= 0
