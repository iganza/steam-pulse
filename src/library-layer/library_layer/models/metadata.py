"""Game metadata context — store page data injected into Pass 2 synthesis prompt."""

import re
from decimal import Decimal

from library_layer.models.game import Game
from pydantic import BaseModel

_ABOUT_MAX_CHARS = 1500


class GameMetadataContext(BaseModel):
    short_desc: str | None = None
    about_the_game: str | None = None
    price_usd: Decimal | None = None
    is_free: bool = False
    tags: list[str] = []
    genres: list[str] = []
    platforms: list[str] = []
    deck_status: str = "Unknown"
    achievements_total: int = 0
    metacritic_score: int | None = None


def build_metadata_context(
    game: Game,
    tags: list[dict],
    genres: list[dict],
) -> GameMetadataContext:
    """Assemble GameMetadataContext from a Game model and tag/genre dicts. No I/O."""
    about: str | None = None
    if game.about_the_game is not None:
        stripped = re.sub(r"<[^>]+>", "", game.about_the_game)
        about = stripped[:_ABOUT_MAX_CHARS]

    platforms = [k.title() for k, v in (game.platforms or {}).items() if v]

    return GameMetadataContext(
        short_desc=game.short_desc,
        about_the_game=about,
        price_usd=game.price_usd,
        is_free=game.is_free,
        tags=[t["name"] for t in tags[:10]],
        genres=[g["name"] for g in genres],
        platforms=platforms,
        deck_status=game.deck_status,
        achievements_total=game.achievements_total,
        metacritic_score=game.metacritic_score,
    )
