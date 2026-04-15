"""Revenue estimator — Boxleiter v1 (multi-signal).

Estimates Steam-only owners and gross revenue for a Steam game using a
multi-signal review-count x multiplier heuristic (a.k.a. "Boxleiter ratio").

The base multiplier (30x) is adjusted by five signals: review count,
review score, release age, genre/audience, and price tier. All adjustments
are multiplicative.

Sources for calibration:
  - VG Insights public methodology writeups (~30x recent)
  - Gamalytic methodology posts (dynamic 20-60x, 4 signals)
  - GameDiscoverCo NB 2025 (63x average, 36-59x by sales tier)
  - steam-revenue-calculator.com (~48x flat)
  - SteamRev (~35x flat, "~3% of players leave reviews")

These numbers are **rough cuts**. Every output should be treated as ±50%.
The method is versioned (`boxleiter_v1`) so refinements ship as a backfill,
not a schema change.

Every output is **gross revenue, pre-Steam-cut** for **Steam-only** sales.
It's a ceiling, not what the developer took home, and does not include
console/Epic/other-store sales. User-facing surfaces MUST say so.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from library_layer.models.game import Game
from pydantic import BaseModel

METHOD_VERSION = "boxleiter_v1"

BASE_MULTIPLIER = Decimal("30")

# Tag names (lowercase) whose audiences are engaged and review at higher
# rates per sale — they get a LOWER multiplier (0.9x) because fewer
# unseen buyers exist per review.
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

_STRATEGY_SIM_GENRES = frozenset({"strategy", "simulation"})
_CASUAL_GENRES = frozenset({"casual"})

_AGE_BOUNDARY_RECENT = 3
_AGE_BOUNDARY_MID = 7
_AGE_BOUNDARY_OLD = 12

_REVIEW_FLOOR = 50
_EXCLUDED_TYPES = frozenset({"dlc", "demo", "music", "tool", "video", "mod"})


class RevenueEstimate(BaseModel):
    estimated_owners: int | None = None
    estimated_revenue_usd: Decimal | None = None
    method: str = METHOD_VERSION
    reason: str | None = None  # populated when the estimate is None


def _review_count_factor(review_count: int) -> Decimal:
    """Scale multiplier by review volume.

    Mega-popular games have proportionally MORE reviewers per Steam buyer
    (cultural events drive review engagement), and their non-Steam sales
    are invisible to us. Both effects mean fewer Steam owners per review
    than the base assumes — so the factor decreases for high review counts.
    """
    if review_count < 500:
        return Decimal("1.15")
    if review_count < 50_000:
        return Decimal("1.0")
    if review_count < 200_000:
        return Decimal("0.8")
    return Decimal("0.6")


def _review_score_factor(positive_pct: Decimal | None) -> Decimal:
    """Adjust for review-score-driven review propensity.

    Highly-rated games (>90%) attract more reviews per sale (fans are
    motivated to recommend), so the multiplier is lower. Mixed/negative
    games get fewer reviews per sale (only vocal minority reviews).
    """
    if positive_pct is None:
        return Decimal("1.0")
    if positive_pct >= 90:
        return Decimal("0.9")
    if positive_pct >= 75:
        return Decimal("1.0")
    if positive_pct >= 60:
        return Decimal("1.15")
    return Decimal("1.3")


def _age_factor(release_year: int | None) -> Decimal:
    """Adjust for release age.

    Older games have accumulated reviews over many years while early
    buyers who never reviewed dilute the ratio. Review culture was also
    weaker in Steam's early years. Both effects mean older games have
    more owners per review — a higher multiplier.
    """
    if release_year is None:
        return Decimal("1.0")
    age = date.today().year - release_year
    if age <= _AGE_BOUNDARY_RECENT:
        return Decimal("1.0")
    if age <= _AGE_BOUNDARY_MID:
        return Decimal("1.1")
    if age <= _AGE_BOUNDARY_OLD:
        return Decimal("1.2")
    return Decimal("1.3")


def _genre_factor(genres: list[dict], tags: list[dict]) -> Decimal:
    """Genre/audience-driven adjustment.

    Niche audiences (visual novels, wargames, etc.) are engaged communities
    that review at higher rates per sale — lower multiplier needed. Casual
    audiences review less — higher multiplier.
    """
    tag_names = {(t.get("name") or "").strip().lower() for t in tags}
    if tag_names & _NICHE_TAG_NAMES:
        return Decimal("0.9")

    genre_names = {(g.get("name") or "").strip().lower() for g in genres}
    if genre_names & _CASUAL_GENRES:
        return Decimal("1.1")
    if genre_names & _STRATEGY_SIM_GENRES:
        return Decimal("1.05")

    return Decimal("1.0")


def _price_factor(price_usd: Decimal) -> Decimal:
    """Adjust for price tier.

    Cheap games have higher review rates per sale (low-commitment purchases
    attract more casual feedback). Premium games have lower rates.
    """
    if price_usd < Decimal("5"):
        return Decimal("0.85")
    if price_usd < Decimal("15"):
        return Decimal("1.0")
    if price_usd < Decimal("40"):
        return Decimal("1.05")
    return Decimal("1.1")


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

    release_year = _parse_release_year(game.release_date)

    multiplier = (
        BASE_MULTIPLIER
        * _review_count_factor(review_count)
        * _review_score_factor(game.positive_pct)
        * _age_factor(release_year)
        * _genre_factor(genres, tags)
        * _price_factor(game.price_usd)
    )

    owners = int(Decimal(review_count) * multiplier)
    revenue = (Decimal(owners) * game.price_usd).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return RevenueEstimate(
        estimated_owners=owners,
        estimated_revenue_usd=revenue,
        method=METHOD_VERSION,
    )


__all__ = [
    "BASE_MULTIPLIER",
    "METHOD_VERSION",
    "RevenueEstimate",
    "compute_estimate",
]
