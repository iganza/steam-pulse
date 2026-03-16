"""Tests for ReviewRepository."""

from datetime import UTC, datetime

from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.review_repo import ReviewRepository


def _seed_game(game_repo: GameRepository, appid: int = 440) -> None:
    game_repo.upsert({
        "appid": appid,
        "name": f"App {appid}",
        "slug": f"app-{appid}",
        "type": "game",
        "developer": None,
        "publisher": None,
        "developers": "[]",
        "publishers": "[]",
        "website": None,
        "release_date": None,
        "coming_soon": False,
        "price_usd": None,
        "is_free": False,
        "short_desc": None,
        "detailed_description": None,
        "about_the_game": None,
        "review_count": 100,
        "total_positive": 80,
        "total_negative": 20,
        "positive_pct": 80,
        "review_score_desc": "Positive",
        "header_image": None,
        "background_image": None,
        "required_age": 0,
        "platforms": "{}",
        "supported_languages": None,
        "achievements_total": 0,
        "metacritic_score": None,
        "data_source": "steam_direct",
    })


def _make_reviews(appid: int = 440, count: int = 3) -> list[dict]:
    base_ts = 1700000000
    return [
        {
            "appid": appid,
            "steam_review_id": f"rev-{appid}-{i}",
            "voted_up": i % 2 == 0,
            "playtime_hours": i * 10,
            "body": f"Review body {i}",
            "posted_at": datetime.fromtimestamp(base_ts + i, tz=UTC),
        }
        for i in range(count)
    ]


def test_bulk_upsert_inserts_reviews(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    _seed_game(game_repo)
    reviews = _make_reviews(count=3)
    review_repo.bulk_upsert(reviews)
    assert review_repo.count_by_appid(440) == 3


def test_bulk_upsert_is_idempotent(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    _seed_game(game_repo)
    reviews = _make_reviews(count=3)
    review_repo.bulk_upsert(reviews)
    review_repo.bulk_upsert(reviews)  # second upsert — no duplicates
    assert review_repo.count_by_appid(440) == 3


def test_find_by_appid_paginates(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    _seed_game(game_repo)
    review_repo.bulk_upsert(_make_reviews(count=5))
    page1 = review_repo.find_by_appid(440, limit=2, offset=0)
    page2 = review_repo.find_by_appid(440, limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    # Pages should not overlap
    ids1 = {r.steam_review_id for r in page1}
    ids2 = {r.steam_review_id for r in page2}
    assert ids1.isdisjoint(ids2)


def test_latest_posted_at(
    game_repo: GameRepository, review_repo: ReviewRepository
) -> None:
    _seed_game(game_repo)
    reviews = _make_reviews(count=3)
    review_repo.bulk_upsert(reviews)
    latest = review_repo.latest_posted_at(440)
    assert latest is not None
    # The latest should be the review with i=2 (base_ts + 2)
    expected = datetime.fromtimestamp(1700000002, tz=UTC)
    assert latest.replace(tzinfo=UTC) == expected


def test_latest_posted_at_returns_none_for_empty(
    review_repo: ReviewRepository,
) -> None:
    assert review_repo.latest_posted_at(9999) is None
