"""Unit tests for the Boxleiter v1 revenue estimator (multi-signal)."""

from datetime import date
from decimal import Decimal

import pytest
from library_layer.models.game import Game
from library_layer.services.revenue_estimator import (
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
        "positive_pct": Decimal("80"),
    }
    base.update(overrides)
    return Game.model_validate(base)


# --- Baseline ---


def test_baseline_default() -> None:
    """1000 reviews, $19.99, recent, 80% positive, no genre/tag → 30x base * 1.05 price factor."""
    game = _game()
    result = compute_estimate(game, genres=[], tags=[])
    assert result.reason is None
    assert result.method == METHOD_VERSION
    # 30 * 1.0 (1k reviews) * 1.0 (80%) * 1.0 (age 1) * 1.0 (default) * 1.05 ($19.99)
    expected_mult = Decimal("30") * Decimal("1.05")
    expected_owners = int(Decimal("1000") * expected_mult)
    assert result.estimated_owners == expected_owners  # 31500
    assert result.estimated_revenue_usd == (Decimal(expected_owners) * Decimal("19.99")).quantize(
        Decimal("0.01")
    )


# --- Genre/tag factors ---


def test_strategy_sim_factor() -> None:
    game = _game()
    result = compute_estimate(
        game,
        genres=[{"name": "Strategy", "slug": "strategy"}],
        tags=[],
    )
    # 30 * 1.0 * 1.0 * 1.0 * 1.05 (strategy) * 1.05 (price) = 33.075
    expected_owners = int(Decimal("1000") * Decimal("33.075"))
    assert result.estimated_owners == expected_owners


def test_niche_tag_factor() -> None:
    game = _game()
    result = compute_estimate(
        game,
        genres=[{"name": "Adventure", "slug": "adventure"}],
        tags=[{"name": "Visual Novel", "slug": "visual-novel"}],
    )
    # 30 * 1.0 * 1.0 * 1.0 * 0.9 (niche) * 1.05 (price) = 28.35
    expected_owners = int(Decimal("1000") * Decimal("28.35"))
    assert result.estimated_owners == expected_owners


def test_niche_beats_strategy() -> None:
    game = _game()
    result_niche = compute_estimate(
        game,
        genres=[{"name": "Strategy", "slug": "strategy"}],
        tags=[{"name": "Visual Novel", "slug": "visual-novel"}],
    )
    result_strat = compute_estimate(
        game,
        genres=[{"name": "Strategy", "slug": "strategy"}],
        tags=[],
    )
    # Niche tag (0.9) wins over strategy genre (1.05) → fewer owners
    assert result_niche.estimated_owners < result_strat.estimated_owners


def test_casual_genre_factor() -> None:
    game = _game()
    result = compute_estimate(
        game,
        genres=[{"name": "Casual", "slug": "casual"}],
        tags=[],
    )
    # 30 * 1.0 * 1.0 * 1.0 * 1.1 (casual) * 1.05 (price) = 34.65
    expected_owners = int(Decimal("1000") * Decimal("34.65"))
    assert result.estimated_owners == expected_owners


# --- Exclusions ---


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


# --- Review count factor ---


def test_review_count_factor_mega_hit() -> None:
    game = _game(review_count=500_000, price_usd=Decimal("10.00"), positive_pct=Decimal("80"))
    result = compute_estimate(game, genres=[], tags=[])
    # 30 * 0.6 (500k) * 1.0 (80%) * 1.0 (recent) * 1.0 (default) * 1.0 ($10) = 18
    assert result.estimated_owners == int(Decimal("500000") * Decimal("18"))


def test_review_count_factor_popular() -> None:
    game = _game(review_count=100_000, price_usd=Decimal("10.00"), positive_pct=Decimal("80"))
    result = compute_estimate(game, genres=[], tags=[])
    # 30 * 0.8 (100k) * 1.0 (80%) * 1.0 (recent) * 1.0 (default) * 1.0 ($10) = 24
    assert result.estimated_owners == int(Decimal("100000") * Decimal("24"))


def test_review_count_factor_small() -> None:
    game = _game(review_count=100, price_usd=Decimal("10.00"), positive_pct=Decimal("80"))
    result = compute_estimate(game, genres=[], tags=[])
    # 30 * 1.15 (100) * 1.0 * 1.0 * 1.0 * 1.0 = 34.5
    assert result.estimated_owners == int(Decimal("100") * Decimal("34.5"))


# --- Review score factor ---


def test_review_score_high() -> None:
    game = _game(positive_pct=Decimal("95"), price_usd=Decimal("10.00"))
    result = compute_estimate(game, genres=[], tags=[])
    # 30 * 1.0 (1k) * 0.9 (95%) * 1.0 * 1.0 * 1.0 = 27
    assert result.estimated_owners == int(Decimal("1000") * Decimal("27"))


def test_review_score_mixed() -> None:
    game = _game(positive_pct=Decimal("65"), price_usd=Decimal("10.00"))
    result = compute_estimate(game, genres=[], tags=[])
    # 30 * 1.0 * 1.15 (65%) * 1.0 * 1.0 * 1.0 = 34.5
    assert result.estimated_owners == int(Decimal("1000") * Decimal("34.5"))


def test_review_score_negative() -> None:
    game = _game(positive_pct=Decimal("45"), price_usd=Decimal("10.00"))
    result = compute_estimate(game, genres=[], tags=[])
    # 30 * 1.0 * 1.3 (45%) * 1.0 * 1.0 * 1.0 = 39
    assert result.estimated_owners == int(Decimal("1000") * Decimal("39"))


def test_missing_positive_pct_uses_baseline() -> None:
    game = _game(positive_pct=None, price_usd=Decimal("10.00"))
    result = compute_estimate(game, genres=[], tags=[])
    # 30 * 1.0 * 1.0 (None→baseline) * 1.0 * 1.0 * 1.0 = 30
    assert result.estimated_owners == int(Decimal("1000") * Decimal("30"))


# --- Age factor ---


def test_age_factor_old_game() -> None:
    old_year = date.today().year - 6
    game = _game(
        release_date=f"{old_year}-01-01", price_usd=Decimal("10.00"), positive_pct=Decimal("80")
    )
    result = compute_estimate(game, genres=[], tags=[])
    # 30 * 1.0 * 1.0 * 1.1 (age 6, 4-7 bracket) * 1.0 * 1.0 = 33
    assert result.estimated_owners == int(Decimal("1000") * Decimal("33"))


def test_age_factor_very_old_game() -> None:
    old_year = date.today().year - 14
    game = _game(
        release_date=f"{old_year}-01-01", price_usd=Decimal("10.00"), positive_pct=Decimal("80")
    )
    result = compute_estimate(game, genres=[], tags=[])
    # 30 * 1.0 * 1.0 * 1.3 (age 14, 13+ bracket) * 1.0 * 1.0 = 39
    assert result.estimated_owners == int(Decimal("1000") * Decimal("39"))


# --- Price factor ---


def test_sub_5_price_factor() -> None:
    game = _game(price_usd=Decimal("4.99"), positive_pct=Decimal("80"))
    result = compute_estimate(game, genres=[], tags=[])
    # 30 * 1.0 * 1.0 * 1.0 * 1.0 * 0.85 (<$5) = 25.5
    assert result.estimated_owners == int(Decimal("1000") * Decimal("25.5"))


def test_premium_price_factor() -> None:
    game = _game(price_usd=Decimal("59.99"), positive_pct=Decimal("80"))
    result = compute_estimate(game, genres=[], tags=[])
    # 30 * 1.0 * 1.0 * 1.0 * 1.0 * 1.1 ($40+) = 33
    assert result.estimated_owners == int(Decimal("1000") * Decimal("33"))


# --- Factor composition ---


def test_sub_5_and_old_compose() -> None:
    old_year = date.today().year - 6
    game = _game(
        price_usd=Decimal("4.99"),
        release_date=f"{old_year}-01-01",
        positive_pct=Decimal("80"),
    )
    result = compute_estimate(game, genres=[], tags=[])
    # 30 * 1.0 * 1.0 * 1.1 (age 6) * 1.0 * 0.85 (<$5) = 28.05
    expected_owners = int(Decimal("1000") * Decimal("28.05"))
    assert result.estimated_owners == expected_owners


def test_revenue_is_owners_times_price() -> None:
    game = _game(price_usd=Decimal("10.00"), review_count=100, positive_pct=Decimal("80"))
    result = compute_estimate(game, genres=[], tags=[])
    # 30 * 1.15 (100 reviews) * 1.0 * 1.0 * 1.0 * 1.0 ($10) = 34.5
    assert result.estimated_owners == 3450
    assert result.estimated_revenue_usd == Decimal("34500.00")


# --- Validation targets (Steam-only, ±50%) ---


def test_validation_elden_ring() -> None:
    """Elden Ring: 785k reviews, $60, 2022, ~93% positive. Steam ~15.7M (Alinea)."""
    game = _game(
        review_count=785_663,
        price_usd=Decimal("59.99"),
        release_date="2022-02-25",
        positive_pct=Decimal("93"),
    )
    result = compute_estimate(game, genres=[], tags=[])
    assert result.estimated_owners is not None
    # Steam-only target ~10-20M; ±50% band = 5M-30M
    assert 5_000_000 <= result.estimated_owners <= 30_000_000


def test_validation_terraria() -> None:
    """Terraria: 1.1M reviews, $10, 2011, ~97% positive. Steam ~33M PC (confirmed)."""
    game = _game(
        review_count=1_142_929,
        price_usd=Decimal("9.99"),
        release_date="2011-05-16",
        positive_pct=Decimal("97"),
    )
    result = compute_estimate(game, genres=[], tags=[])
    assert result.estimated_owners is not None
    # Steam-only target ~23-33M; ±50% band = 12M-50M
    assert 12_000_000 <= result.estimated_owners <= 50_000_000


def test_validation_black_myth() -> None:
    """Black Myth Wukong: 849k reviews, $60, 2024, ~97% positive. Steam ~20M (Yicai)."""
    game = _game(
        review_count=848_978,
        price_usd=Decimal("59.99"),
        release_date="2024-08-20",
        positive_pct=Decimal("97"),
    )
    result = compute_estimate(game, genres=[], tags=[])
    assert result.estimated_owners is not None
    # Steam-only target ~15-20M; ±50% band = 7.5M-30M
    assert 7_500_000 <= result.estimated_owners <= 30_000_000


def test_validation_hades() -> None:
    """Hades: 127k reviews, $25, 2020, ~97% positive. Steam target: 3-5M."""
    game = _game(
        review_count=127_000,
        price_usd=Decimal("25.00"),
        release_date="2020-09-17",
        positive_pct=Decimal("97"),
    )
    result = compute_estimate(game, genres=[], tags=[])
    assert result.estimated_owners is not None
    assert 1_500_000 <= result.estimated_owners <= 7_500_000


def test_validation_dwarf_fortress() -> None:
    """Dwarf Fortress: 38k reviews, $30, 2022, ~96% positive, niche. Steam target: 1-1.5M."""
    game = _game(
        review_count=38_000,
        price_usd=Decimal("29.99"),
        release_date="2022-12-06",
        positive_pct=Decimal("96"),
    )
    result = compute_estimate(
        game,
        genres=[],
        tags=[{"name": "Hardcore", "slug": "hardcore"}],
    )
    assert result.estimated_owners is not None
    assert 500_000 <= result.estimated_owners <= 2_250_000


def test_validation_victoria_3() -> None:
    """Victoria 3: 16k reviews, $50, 2022, ~67% positive, strategy. Steam target: 400k-700k."""
    game = _game(
        review_count=16_000,
        price_usd=Decimal("49.99"),
        release_date="2022-10-25",
        positive_pct=Decimal("67"),
    )
    result = compute_estimate(
        game,
        genres=[{"name": "Strategy", "slug": "strategy"}],
        tags=[],
    )
    assert result.estimated_owners is not None
    assert 200_000 <= result.estimated_owners <= 1_050_000
