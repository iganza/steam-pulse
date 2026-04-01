"""Tests for models/metadata.py — pure function tests, no DB required."""

from decimal import Decimal

from library_layer.models.metadata import GameMetadataContext, build_metadata_context


def _make_game(**kwargs: object) -> object:
    """Build a minimal mock Game object for testing."""
    from unittest.mock import MagicMock

    game = MagicMock()
    game.short_desc = kwargs.get("short_desc", "A great game")
    game.about_the_game = kwargs.get("about_the_game", "<p>Full description</p>")
    game.price_usd = kwargs.get("price_usd", Decimal("19.99"))
    game.is_free = kwargs.get("is_free", False)
    game.platforms = kwargs.get("platforms", {"windows": True, "mac": False, "linux": True})
    game.achievements_total = kwargs.get("achievements_total", 10)
    game.metacritic_score = kwargs.get("metacritic_score", None)
    game.deck_status = kwargs.get("deck_status", "Verified")
    return game


def test_all_fields_populated() -> None:
    game = _make_game(
        short_desc="Short",
        about_the_game="<b>Full</b>",
        price_usd=Decimal("9.99"),
        is_free=False,
        platforms={"windows": True, "mac": True, "linux": False},
        achievements_total=50,
        metacritic_score=85,
        deck_status="Playable",
    )
    tags = [{"name": "RPG"}, {"name": "Action"}]
    genres = [{"name": "Adventure"}]

    ctx = build_metadata_context(game, tags, genres)

    assert ctx.short_desc == "Short"
    assert ctx.about_the_game == "Full"
    assert ctx.price_usd == Decimal("9.99")
    assert ctx.is_free is False
    assert ctx.tags == ["RPG", "Action"]
    assert ctx.genres == ["Adventure"]
    assert ctx.platforms == ["Windows", "Mac"]
    assert ctx.achievements_total == 50
    assert ctx.metacritic_score == 85
    assert ctx.deck_status == "Playable"


def test_about_the_game_none() -> None:
    game = _make_game(about_the_game=None)
    ctx = build_metadata_context(game, [], [])
    assert ctx.about_the_game is None


def test_html_stripped_from_about_the_game() -> None:
    game = _make_game(about_the_game="<h1>Title</h1><p>Body <b>text</b></p>")
    ctx = build_metadata_context(game, [], [])
    assert ctx.about_the_game == "TitleBody text"


def test_about_the_game_truncated_at_1500() -> None:
    long_text = "x" * 2000
    game = _make_game(about_the_game=long_text)
    ctx = build_metadata_context(game, [], [])
    assert ctx.about_the_game is not None
    assert len(ctx.about_the_game) == 1500


def test_platforms_none_guard() -> None:
    game = _make_game(platforms=None)
    game.platforms = None
    ctx = build_metadata_context(game, [], [])
    assert ctx.platforms == []


def test_empty_platforms_dict() -> None:
    game = _make_game(platforms={})
    ctx = build_metadata_context(game, [], [])
    assert ctx.platforms == []


def test_false_platform_excluded() -> None:
    game = _make_game(platforms={"windows": True, "mac": False, "linux": False})
    ctx = build_metadata_context(game, [], [])
    assert ctx.platforms == ["Windows"]


def test_top_10_tags_only() -> None:
    tags = [{"name": f"tag{i}"} for i in range(15)]
    game = _make_game()
    ctx = build_metadata_context(game, tags, [])
    assert len(ctx.tags) == 10
    assert ctx.tags == [f"tag{i}" for i in range(10)]


def test_gameMetadataContext_defaults() -> None:
    ctx = GameMetadataContext()
    assert ctx.short_desc is None
    assert ctx.about_the_game is None
    assert ctx.price_usd is None
    assert ctx.is_free is False
    assert ctx.tags == []
    assert ctx.genres == []
    assert ctx.platforms == []
    assert ctx.deck_status == "Unknown"
    assert ctx.achievements_total == 0
    assert ctx.metacritic_score is None
