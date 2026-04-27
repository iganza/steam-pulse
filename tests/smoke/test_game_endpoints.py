"""Smoke tests for game detail endpoints: /api/games/*."""

import httpx
import pytest

pytestmark = pytest.mark.smoke


def test_games_list(api: httpx.Client) -> None:
    r = api.get("/api/games", params={"limit": 5})
    assert r.status_code == 200
    data = r.json()
    assert "games" in data
    assert len(data["games"]) > 0


def test_games_basics_batch(api: httpx.Client, well_known_appid: int) -> None:
    r = api.get("/api/games/basics", params={"appids": str(well_known_appid)})
    assert r.status_code == 200
    data = r.json()
    assert "games" in data
    # Known appid should resolve; unknowns are silently omitted.
    assert any(g["appid"] == well_known_appid for g in data["games"])
    for g in data["games"]:
        assert "name" in g and isinstance(g["name"], str)
        assert "slug" in g and isinstance(g["slug"], str)
        # header_image may be null if the Steam crawl hasn't populated it.
        assert "header_image" in g
        # Sentiment fields (broadened for homepage hero strip).
        # Both may be null if the Steam crawl hasn't populated review stats.
        assert "positive_pct" in g
        assert "review_count" in g


def test_games_basics_rejects_non_numeric(api: httpx.Client) -> None:
    r = api.get("/api/games/basics", params={"appids": "notanumber"})
    assert r.status_code == 400


def test_game_report(api: httpx.Client, well_known_appid: int) -> None:
    r = api.get(f"/api/games/{well_known_appid}/report")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert "game" in data


def test_game_review_stats(api: httpx.Client, well_known_appid: int) -> None:
    r = api.get(f"/api/games/{well_known_appid}/review-stats")
    assert r.status_code == 200


def test_game_benchmarks(api: httpx.Client, well_known_appid: int) -> None:
    r = api.get(f"/api/games/{well_known_appid}/benchmarks")
    assert r.status_code == 200


def test_game_audience_overlap(api: httpx.Client, well_known_appid: int) -> None:
    r = api.get(f"/api/games/{well_known_appid}/audience-overlap")
    assert r.status_code == 200


def test_game_playtime_sentiment(api: httpx.Client, well_known_appid: int) -> None:
    r = api.get(f"/api/games/{well_known_appid}/playtime-sentiment")
    assert r.status_code == 200


def test_game_early_access_impact(api: httpx.Client, well_known_appid: int) -> None:
    r = api.get(f"/api/games/{well_known_appid}/early-access-impact")
    assert r.status_code == 200


def test_game_review_velocity(api: httpx.Client, well_known_appid: int) -> None:
    r = api.get(f"/api/games/{well_known_appid}/review-velocity")
    assert r.status_code == 200


def test_game_top_reviews(api: httpx.Client, well_known_appid: int) -> None:
    r = api.get(f"/api/games/{well_known_appid}/top-reviews")
    assert r.status_code == 200


def test_nonexistent_appid(api: httpx.Client) -> None:
    r = api.get("/api/games/999999999/report")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert data["status"] == "not_available"
