"""Unit tests for the Boxleiter v1 revenue estimator."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from library_layer.models.game import Game
from library_layer.services.revenue_estimator import (
    GENRE_MULTIPLIERS,
    METHOD_VERSION,
    compute_estimate,
)


def _game(**overrides: object) -> Game:
    base: dict = {
        "appid": 1,
        "name": "Test",
        "slug": "test",
        "type": "game",
        "price_usd": Decimal("19.99"),
        "is_free": False,
        "review_count": 1000,
        "release_date": f"{date.today().year - 1}-01-01",
    }
    base.update(overrides)
    return Game.model_validate(base)


def test_indie_default_bucket() -> None:
    game = _game()
    result = compute_estimate(game, genres=[], tags=[])
    assert result.reason is None
    assert result.method == METHOD_VERSION
    assert result.estimated_owners == 1000 * GENRE_MULTIPLIERS["indie"]
    assert result.estimated_revenue_usd == Decimal("299850.00")


def test_strategy_sim_bucket() -> None:
    game = _game()
    result = compute_estimate(
        game,
        genres=[{"name": "Strategy", "slug": "strategy"}],
        tags=[],
    )
    assert result.estimated_owners == 1000 * GENRE_MULTIPLIERS["strategy_sim"]


def test_niche_tag_bucket() -> None:
    game = _game()
    result = compute_estimate(
        game,
        genres=[{"name": "Adventure", "slug": "adventure"}],
        tags=[{"name": "Visual Novel", "slug": "visual-novel"}],
    )
    assert result.estimated_owners == 1000 * GENRE_MULTIPLIERS["niche"]


def test_niche_beats_strategy() -> None:
    game = _game()
    result = compute_estimate(
        game,
        genres=[{"name": "Strategy", "slug": "strategy"}],
        tags=[{"name": "Visual Novel", "slug": "visual-novel"}],
    )
    assert result.estimated_owners == 1000 * GENRE_MULTIPLIERS["niche"]


def test_free_to_play_returns_none() -> None:
    game = _game(is_free=True, price_usd=None)
    result = compute_estimate(game, genres=[], tags=[])
    assert result.estimated_owners is None
    assert result.estimated_revenue_usd is None
    assert result.reason == "free_to_play"


@pytest.mark.parametrize("game_type", ["dlc", "demo", "music", "tool", "DLC"])
def test_excluded_types_return_none(game_type: str) -> None:
    game = _game(type=game_type)
    result = compute_estimate(game, genres=[], tags=[])
    assert result.reason == "excluded_type"
    assert result.estimated_owners is None


def test_insufficient_reviews() -> None:
    game = _game(review_count=49)
    result = compute_estimate(game, genres=[], tags=[])
    assert result.reason == "insufficient_reviews"
    assert result.estimated_owners is None


def test_missing_price() -> None:
    game = _game(price_usd=None, is_free=False)
    result = compute_estimate(game, genres=[], tags=[])
    assert result.reason == "missing_price"


def test_age_decay_applied_for_old_game() -> None:
    old_year = date.today().year - 6
    game = _game(release_date=f"{old_year}-01-01")
    result = compute_estimate(game, genres=[], tags=[])
    # indie=15 x 0.85 = 12.75 → int(1000 * 12.75) = 12750
    assert result.estimated_owners == 12750


def test_sub_5_price_shave_applied() -> None:
    game = _game(price_usd=Decimal("4.99"))
    result = compute_estimate(game, genres=[], tags=[])
    # indie=15 x 0.80 = 12 → 1000 * 12 = 12000
    assert result.estimated_owners == 12000


def test_sub_5_and_old_compose() -> None:
    old_year = date.today().year - 6
    game = _game(price_usd=Decimal("4.99"), release_date=f"{old_year}-01-01")
    result = compute_estimate(game, genres=[], tags=[])
    # indie=15 x 0.85 x 0.80 = 10.2 → 1000 * 10.2 = 10200
    assert result.estimated_owners == 10200


def test_revenue_is_owners_times_price() -> None:
    game = _game(price_usd=Decimal("10.00"), review_count=100)
    result = compute_estimate(game, genres=[], tags=[])
    assert result.estimated_owners == 1500
    assert result.estimated_revenue_usd == Decimal("15000.00")
