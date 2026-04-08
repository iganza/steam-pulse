"""Revenue estimator — Boxleiter v1.

Estimates owners and gross revenue for a Steam game using the
review-count x multiplier heuristic (a.k.a. "Boxleiter ratio").

Sources for the base multipliers:
  - Boxleiter GDC talk — the original review-count-to-sales ratio heuristic
  - VG Insights public methodology writeups
  - Gamalytic methodology posts

These numbers are **rough cuts for v1**. Every output should be treated as
±50%. The method is versioned (`boxleiter_v1`) so refinements ship as a
backfill, not a schema change.

Every output is **gross revenue, pre-Steam-cut**. It's a ceiling, not what
the developer took home. User-facing surfaces MUST say so.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from library_layer.models.game import Game
from pydantic import BaseModel

METHOD_VERSION = "boxleiter_v1"

# Base multipliers (review_count → owners) per rough genre bucket.
# See module docstring for sources. Numbers are intentionally round — the
# noise in the underlying heuristic swamps any pretense of precision.
GENRE_MULTIPLIERS: dict[str, int] = {
    "mainstream": 20,  # AAA / high-profile — unused in v1 (no reliable classifier yet)
    "indie": 30,  # default bucket
    "strategy_sim": 50,  # Strategy / Simulation genres review at low rates per sale
    "niche": 70,  # Visual novels, hardcore sims, etc.
}

# Genre-name → bucket. Matched case-insensitively against Steam genre names.
_STRATEGY_SIM_GENRES = frozenset({"strategy", "simulation"})

# Tag-name (lowercase) → niche bucket. These are the tag labels whose audiences
# are believed to review at lower rates per purchase, so they map to the most
# expansive owners-per-review multiplier (70x).
_NICHE_TAG_NAMES = frozenset(
    {
        "visual novel",
        "hentai",
        "dating sim",
        "hardcore",
        "grand strategy",
        "wargame",
        "4x",
    }
)

_AGE_DECAY_YEARS = 3
_AGE_DECAY_FACTOR = Decimal("0.85")
_SUB_5_FACTOR = Decimal("0.80")
_REVIEW_FLOOR = 50
_EXCLUDED_TYPES = frozenset({"dlc", "demo", "music", "tool", "video", "mod"})


class RevenueEstimate(BaseModel):
    estimated_owners: int | None = None
    estimated_revenue_usd: Decimal | None = None
    method: str = METHOD_VERSION
    reason: str | None = None  # populated when the estimate is None


def _select_bucket(genres: list[dict], tags: list[dict]) -> str:
    """Choose the boxleiter bucket for this game.

    v1 is deliberately simple: niche tags win over strategy/sim genres win
    over the indie default. Mainstream bucket is reserved for a future
    AAA-publisher classifier — never returned in v1.
    """
    tag_names = {(t.get("name") or "").strip().lower() for t in tags}
    if tag_names & _NICHE_TAG_NAMES:
        return "niche"

    genre_names = {(g.get("name") or "").strip().lower() for g in genres}
    if genre_names & _STRATEGY_SIM_GENRES:
        return "strategy_sim"

    return "indie"


def _parse_release_year(release_date: str | None) -> int | None:
    if not release_date:
        return None
    try:
        return int(release_date[:4])
    except (ValueError, TypeError):
        return None


def compute_estimate(
    game: Game,
    genres: list[dict],
    tags: list[dict],
) -> RevenueEstimate:
    """Compute a Boxleiter v1 revenue estimate for a game.

    Returns a `RevenueEstimate`. When no estimate can be produced, both value
    fields are None and `reason` is populated with a short machine-readable
    code (e.g. "insufficient_reviews", "free_to_play").
    """
    if game.type and game.type.lower() in _EXCLUDED_TYPES:
        return RevenueEstimate(reason="excluded_type")

    if game.is_free:
        return RevenueEstimate(reason="free_to_play")

    if game.price_usd is None:
        return RevenueEstimate(reason="missing_price")

    review_count = game.review_count or 0
    if review_count < _REVIEW_FLOOR:
        return RevenueEstimate(reason="insufficient_reviews")

    bucket = _select_bucket(genres, tags)
    multiplier = Decimal(GENRE_MULTIPLIERS[bucket])

    # Age decay: older games accumulate reviews slowly relative to sales,
    # so the raw ratio overshoots. Knock 15% off for anything > 3y old.
    release_year = _parse_release_year(game.release_date)
    if release_year is not None:
        current_year = date.today().year
        if current_year - release_year > _AGE_DECAY_YEARS:
            multiplier = multiplier * _AGE_DECAY_FACTOR

    # Price tier: sub-$5 games review at higher rates per sale.
    if game.price_usd < Decimal("5"):
        multiplier = multiplier * _SUB_5_FACTOR

    owners = int(Decimal(review_count) * multiplier)
    revenue = (Decimal(owners) * game.price_usd).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return RevenueEstimate(
        estimated_owners=owners,
        estimated_revenue_usd=revenue,
        method=METHOD_VERSION,
    )


__all__ = [
    "GENRE_MULTIPLIERS",
    "METHOD_VERSION",
    "RevenueEstimate",
    "compute_estimate",
]
