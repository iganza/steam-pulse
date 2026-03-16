"""Tests for GameRepository."""

from datetime import date

from library_layer.repositories.game_repo import GameRepository


def _game_data(appid: int = 440, name: str = "Team Fortress 2") -> dict:
    return {
        "appid": appid,
        "name": name,
        "slug": f"team-fortress-2-{appid}",
        "type": "game",
        "developer": "Valve",
        "publisher": "Valve",
        "developers": '["Valve"]',
        "publishers": '["Valve"]',
        "website": "http://www.teamfortress.com/",
        "release_date": date(2007, 10, 10),
        "coming_soon": False,
        "price_usd": None,
        "is_free": True,
        "short_desc": "Nine classes, constant updates.",
        "detailed_description": "A detailed description.",
        "about_the_game": "About TF2.",
        "review_count": 188000,
        "total_positive": 182000,
        "total_negative": 6000,
        "positive_pct": 96,
        "review_score_desc": "Overwhelmingly Positive",
        "header_image": "https://example.com/header.jpg",
        "background_image": "https://example.com/bg.jpg",
        "required_age": 0,
        "platforms": '{"windows": true, "mac": false, "linux": true}',
        "supported_languages": "English",
        "achievements_total": 520,
        "metacritic_score": 92,
        "data_source": "steam_direct",
    }


def test_upsert_inserts_new_game(game_repo: GameRepository) -> None:
    game_repo.upsert(_game_data())
    game = game_repo.find_by_appid(440)
    assert game is not None
    assert game.appid == 440
    assert game.name == "Team Fortress 2"
    assert game.developer == "Valve"
    assert game.review_count == 188000


def test_upsert_updates_existing_game(game_repo: GameRepository) -> None:
    game_repo.upsert(_game_data())
    updated = _game_data()
    updated["name"] = "TF2 Updated"
    updated["review_count"] = 200000
    game_repo.upsert(updated)
    game = game_repo.find_by_appid(440)
    assert game is not None
    assert game.name == "TF2 Updated"
    assert game.review_count == 200000


def test_find_by_appid_returns_none_for_missing(game_repo: GameRepository) -> None:
    assert game_repo.find_by_appid(9999999) is None


def test_find_by_slug(game_repo: GameRepository) -> None:
    game_repo.upsert(_game_data())
    game = game_repo.find_by_slug("team-fortress-2-440")
    assert game is not None
    assert game.appid == 440


def test_find_eligible_for_reviews(game_repo: GameRepository) -> None:
    game_repo.upsert(_game_data(440, "TF2"))  # 188000 reviews
    small = _game_data(1, "Tiny Game")
    small["review_count"] = 50
    small["slug"] = "tiny-game-1"
    game_repo.upsert(small)

    eligible = game_repo.find_eligible_for_reviews(min_reviews=500)
    appids = [g.appid for g in eligible]
    assert 440 in appids
    assert 1 not in appids


def test_update_review_stats(game_repo: GameRepository) -> None:
    game_repo.upsert(_game_data())
    game_repo.update_review_stats(440, 190000, 6000, 196000, "Overwhelmingly Positive")
    game = game_repo.find_by_appid(440)
    assert game is not None
    assert game.total_positive == 190000
    assert game.review_count == 196000
    assert game.review_score_desc == "Overwhelmingly Positive"
    # Name unchanged
    assert game.name == "Team Fortress 2"


def test_get_review_count_returns_zero_for_missing(game_repo: GameRepository) -> None:
    assert game_repo.get_review_count(9999999) == 0


def test_ensure_stub_creates_minimal_row(game_repo: GameRepository) -> None:
    game_repo.ensure_stub(12345)
    game = game_repo.find_by_appid(12345)
    assert game is not None
    assert game.name == "App 12345"
    assert game.slug == "app-12345"
