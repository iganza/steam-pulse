"""Tests for MatviewRepository — audience overlap (mv_audience_overlap)."""

from datetime import UTC, datetime
from typing import Any

import pytest
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.matview_repo import MatviewRepository
from library_layer.repositories.review_repo import ReviewRepository

# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_game(game_repo: GameRepository, appid: int = 440, **kw: Any) -> None:
    game_repo.upsert(
        {
            "appid": appid,
            "name": kw.get("name", f"Game {appid}"),
            "slug": kw.get("slug", f"game-{appid}"),
            "type": "game",
            "developer": kw.get("developer", "Test Dev"),
            "developer_slug": kw.get("developer_slug", "test-dev"),
            "publisher": kw.get("publisher"),
            "publisher_slug": kw.get("publisher_slug"),
            "developers": "[]",
            "publishers": "[]",
            "website": None,
            "release_date": kw.get("release_date", "2022-06-15"),
            "release_date_raw": None,
            "coming_soon": False,
            "price_usd": kw.get("price_usd", 9.99),
            "is_free": kw.get("is_free", False),
            "short_desc": None,
            "detailed_description": None,
            "about_the_game": None,
            "review_count": kw.get("review_count", 100),
            "review_count_english": kw.get("review_count", 100),
            "total_positive": 75,
            "total_negative": 25,
            "positive_pct": kw.get("positive_pct", 75),
            "review_score_desc": "Mostly Positive",
            "header_image": None,
            "background_image": None,
            "required_age": 0,
            "platforms": kw.get("platforms", '{"windows": true, "mac": false, "linux": false}'),
            "supported_languages": None,
            "achievements_total": 0,
            "metacritic_score": None,
            "deck_compatibility": None,
            "deck_test_results": None,
            "content_descriptor_ids": None,
            "content_descriptor_notes": None,
            "controller_support": None,
            "dlc_appids": None,
            "parent_appid": None,
            "capsule_image": None,
            "recommendations_total": None,
            "support_url": None,
            "support_email": None,
            "legal_notice": None,
            "requirements_windows": None,
            "requirements_mac": None,
            "requirements_linux": None,
            "data_source": "steam_direct",
        }
    )


def _make_review(appid: int, author: str, voted_up: bool = True, idx: int = 0) -> dict:
    return {
        "appid": appid,
        "steam_review_id": f"rev-{appid}-{author}-{idx}",
        "author_steamid": author,
        "voted_up": voted_up,
        "playtime_hours": 10,
        "body": "review",
        "posted_at": datetime(2024, 1, 1, tzinfo=UTC),
        "language": "english",
        "votes_helpful": 0,
        "votes_funny": 0,
        "written_during_early_access": False,
        "received_for_free": False,
    }


# ---------------------------------------------------------------------------
# get_audience_overlap (mv_audience_overlap)
# ---------------------------------------------------------------------------


def test_audience_overlap_basic(
    db_conn: Any,
    matview_repo: MatviewRepository,
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    refresh_matviews: Any,
) -> None:
    """Shared reviewers counted correctly with correct overlap_pct math.

    Both games need >= 100 unique reviewers to pass the matview's
    games_with_reviews threshold.
    """
    _seed_game(game_repo, 440)
    _seed_game(game_repo, 570)

    # 10 shared reviewers + 90 unique to each game = 100 per game
    shared_authors = [f"shared_{i}" for i in range(10)]
    reviews = [_make_review(440, a) for a in shared_authors]
    reviews += [_make_review(440, f"only440_{i}", idx=i) for i in range(90)]
    reviews += [_make_review(570, a) for a in shared_authors]
    reviews += [_make_review(570, f"only570_{i}", idx=i) for i in range(90)]
    review_repo.bulk_upsert(reviews)
    refresh_matviews()

    result = matview_repo.get_audience_overlap(440, limit=10)
    assert result["total_reviewers"] == 100
    assert len(result["overlaps"]) == 1
    overlap = result["overlaps"][0]
    assert overlap["appid"] == 570
    assert overlap["overlap_count"] == 10
    assert overlap["overlap_pct"] == pytest.approx(10.0, abs=0.2)
    assert isinstance(overlap["shared_sentiment_pct"], float)


def test_audience_overlap_no_reviews(
    matview_repo: MatviewRepository,
    game_repo: GameRepository,
    refresh_matviews: Any,
) -> None:
    """Returns empty structure when appid has no reviews."""
    _seed_game(game_repo, 440)
    refresh_matviews()
    result = matview_repo.get_audience_overlap(440, limit=20)
    assert result == {"total_reviewers": 0, "overlaps": []}


def test_audience_overlap_excludes_self(
    db_conn: Any,
    matview_repo: MatviewRepository,
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    refresh_matviews: Any,
) -> None:
    """Game with reviewers but no overlaps returns correct total_reviewers."""
    _seed_game(game_repo, 440)
    review_repo.bulk_upsert([_make_review(440, "user1")])
    refresh_matviews()
    result = matview_repo.get_audience_overlap(440, limit=20)
    assert result["total_reviewers"] == 1
    assert result["overlaps"] == []


def test_audience_overlap_limit(
    db_conn: Any,
    matview_repo: MatviewRepository,
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    refresh_matviews: Any,
) -> None:
    """Result is capped at the requested limit.

    Each game needs >= 100 unique reviewers to pass the matview threshold.
    """
    for i in range(5):
        _seed_game(game_repo, 440 + i)
    # 1 shared reviewer across all 5 games + 99 unique per game = 100 each
    reviews: list[dict] = []
    for i in range(5):
        reviews.append(_make_review(440 + i, "shared"))
        reviews += [_make_review(440 + i, f"uniq{440 + i}_{j}", idx=j) for j in range(99)]
    review_repo.bulk_upsert(reviews)
    refresh_matviews()

    result = matview_repo.get_audience_overlap(440, limit=2)
    assert len(result["overlaps"]) <= 2
