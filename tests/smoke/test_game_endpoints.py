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


def test_game_report(api: httpx.Client, well_known_appid: int) -> None:
    r = api.get(f"/api/games/{well_known_appid}/report")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert "game" in data


def test_game_report_exposes_post_release_split(
    api: httpx.Client, well_known_appid: int
) -> None:
    """game_meta must expose the English-only post-release split fields (0048)."""
    r = api.get(f"/api/games/{well_known_appid}/report")
    assert r.status_code == 200
    game = r.json()["game"]
    for key in (
        "review_count_post_release",
        "positive_count_post_release",
        "positive_pct_post_release",
        "review_score_desc_post_release",
        "has_early_access_reviews",
        "coming_soon",
    ):
        assert key in game, f"missing {key} in /api/games/{{appid}}/report game_meta"


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
