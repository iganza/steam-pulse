"""Tests for ReportRepository."""

import pytest
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.report_repo import ReportRepository


def _seed_game(game_repo: GameRepository, appid: int = 440) -> None:
    game_repo.upsert(
        {
            "appid": appid,
            "name": "Team Fortress 2",
            "slug": f"team-fortress-2-{appid}",
            "type": "game",
            "developer": "Valve",
            "developer_slug": "valve",
            "publisher": "Valve",
            "publisher_slug": "valve",
            "developers": "[]",
            "publishers": "[]",
            "website": None,
            "release_date": None,
            "coming_soon": False,
            "price_usd": None,
            "is_free": True,
            "short_desc": None,
            "detailed_description": None,
            "about_the_game": None,
            "review_count": 188000,
            "review_count_english": 188000,
            "total_positive": 182000,
            "total_negative": 6000,
            "positive_pct": 96,
            "review_score_desc": "Overwhelmingly Positive",
            "header_image": None,
            "background_image": None,
            "required_age": 0,
            "platforms": "{}",
            "supported_languages": None,
            "achievements_total": 0,
            "metacritic_score": None,
            "deck_compatibility": None,
            "deck_test_results": None,
            "data_source": "steam_direct",
        }
    )


def _report(appid: int = 440) -> dict:
    return {
        "appid": appid,
        "game_name": "Team Fortress 2",
        "one_liner": "The gold standard of team shooters.",
        "total_reviews_analyzed": 2000,
        "design_strengths": ["Class variety"],
        "gameplay_friction": ["Bot problem"],
    }


def test_upsert_and_find(game_repo: GameRepository, report_repo: ReportRepository) -> None:
    _seed_game(game_repo)
    report_repo.upsert(_report())
    result = report_repo.find_by_appid(440)
    assert result is not None
    assert result.appid == 440
    assert result.reviews_analyzed == 2000
    assert result.report_json["game_name"] == "Team Fortress 2"


def test_upsert_updates_existing(game_repo: GameRepository, report_repo: ReportRepository) -> None:
    _seed_game(game_repo)
    report_repo.upsert(_report())
    updated = _report()
    updated["total_reviews_analyzed"] = 3000
    report_repo.upsert(updated)
    result = report_repo.find_by_appid(440)
    assert result is not None
    assert result.reviews_analyzed == 3000


def test_find_public(game_repo: GameRepository, report_repo: ReportRepository) -> None:
    _seed_game(game_repo, 440)
    _seed_game(game_repo, 441)
    report_repo.upsert({**_report(440)})
    report_repo.upsert({**_report(441)})
    # Default is_public=True
    public = report_repo.find_public()
    appids = [r.appid for r in public]
    assert 440 in appids
    assert 441 in appids


def test_find_by_appid_returns_none_for_missing(
    report_repo: ReportRepository,
) -> None:
    assert report_repo.find_by_appid(9999999) is None


def test_upsert_syncs_hidden_gem_to_games(
    game_repo: GameRepository, report_repo: ReportRepository
) -> None:
    """upsert() denormalizes hidden_gem_score (but not sentiment_score) onto games."""
    _seed_game(game_repo)
    report_repo.upsert({**_report(), "hidden_gem_score": 0.42})
    game = game_repo.find_by_appid(440)
    assert game is not None
    assert float(game.hidden_gem_score) == pytest.approx(0.42, abs=0.01)


def test_upsert_updated_hidden_gem_syncs_to_games(
    game_repo: GameRepository, report_repo: ReportRepository
) -> None:
    """A second upsert with a changed hidden_gem updates the games row."""
    _seed_game(game_repo)
    report_repo.upsert({**_report(), "hidden_gem_score": 0.42})
    report_repo.upsert({**_report(), "hidden_gem_score": 0.71})
    game = game_repo.find_by_appid(440)
    assert game is not None
    assert float(game.hidden_gem_score) == pytest.approx(0.71, abs=0.01)
