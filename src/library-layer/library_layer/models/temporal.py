"""Game temporal intelligence — model + pure classification functions."""

from datetime import date

from library_layer.models.game import Game
from pydantic import BaseModel


class GameTemporalContext(BaseModel):
    appid: int
    release_date: date | None
    days_since_release: int | None
    release_age_bucket: str | None  # "new"|"recent"|"established"|"legacy"
    is_coming_soon: bool
    has_early_access: bool
    ea_fraction: float | None
    ea_sentiment_delta: float | None
    review_velocity_lifetime: float | None  # reviews/day since release
    review_velocity_last_30d: int
    velocity_trend: str  # "accelerating"|"stable"|"decelerating"|"dead"
    is_evergreen: bool
    launch_trajectory: str  # "viral"|"slow_build"|"steady"|"declining"|"dead"


def classify_age_bucket(days: int | None) -> str | None:
    if days is None:
        return None
    if days < 30:
        return "new"
    if days < 180:
        return "recent"
    if days < 730:
        return "established"
    return "legacy"


def classify_velocity_trend(
    existing_trend: str, last_30d: int, days_since_release: int | None
) -> str:
    if last_30d == 0 and days_since_release is not None and days_since_release > 180:
        return "dead"
    return existing_trend


def classify_trajectory(
    velocity_lifetime: float | None,
    last_30d: int,
    days_since_release: int | None,
) -> str:
    if (
        velocity_lifetime is not None
        and velocity_lifetime > 50
        and days_since_release is not None
        and days_since_release < 180
    ):
        return "viral"
    if (
        velocity_lifetime is not None
        and velocity_lifetime > 0
        and last_30d > velocity_lifetime * 30 * 1.5
        and days_since_release is not None
        and days_since_release > 180
    ):
        return "slow_build"
    if (
        velocity_lifetime is not None
        and velocity_lifetime > 0
        and last_30d < velocity_lifetime * 30 * 0.3
        and days_since_release is not None
        and days_since_release > 90
    ):
        return "declining"
    if last_30d < 1 and days_since_release is not None and days_since_release > 365:
        return "dead"
    return "steady"


def check_evergreen(days_since_release: int | None, last_30d: int) -> bool:
    return days_since_release is not None and days_since_release > 730 and last_30d > 5


def build_temporal_context(
    game: Game, velocity_data: dict | None, ea_data: dict | None
) -> GameTemporalContext:
    """Assemble GameTemporalContext from a Game model + existing repo outputs.

    Args:
        game: Game model instance
        velocity_data: Return value of ReviewRepository.find_review_velocity()
        ea_data: Return value of ReviewRepository.find_early_access_impact()
    """
    # Parse release_date (Game model stores it as str | None)
    release_date_parsed: date | None = None
    if game.release_date and not game.coming_soon:
        try:
            release_date_parsed = date.fromisoformat(game.release_date)
        except (ValueError, TypeError):
            pass

    days_since_release: int | None = None
    if release_date_parsed:
        days_since_release = (date.today() - release_date_parsed).days

    # Velocity from existing repo data
    velocity_data = velocity_data or {}
    summary = velocity_data.get("summary", {})
    last_30d: int = summary.get("last_30_days", 0)
    existing_trend: str = summary.get("trend", "stable")

    # Lifetime velocity
    review_velocity_lifetime: float | None = None
    if days_since_release and days_since_release > 0 and game.review_count_english:
        review_velocity_lifetime = game.review_count_english / days_since_release

    # Early Access — ea_data can be None when the repo query returns no rows
    ea_data = ea_data or {}
    has_ea = ea_data.get("has_ea_reviews", False)
    ea_fraction: float | None = None
    ea_sentiment_delta: float | None = None
    if has_ea:
        ea_total = (ea_data.get("early_access") or {}).get("total", 0)
        post_total = (ea_data.get("post_launch") or {}).get("total", 0)
        total = ea_total + post_total
        if total > 0:
            ea_fraction = ea_total / total
        ea_sentiment_delta = ea_data.get("impact_delta")

    return GameTemporalContext(
        appid=game.appid,
        release_date=release_date_parsed,
        days_since_release=days_since_release,
        release_age_bucket=classify_age_bucket(days_since_release),
        is_coming_soon=bool(getattr(game, "coming_soon", False)),
        has_early_access=has_ea,
        ea_fraction=ea_fraction,
        ea_sentiment_delta=ea_sentiment_delta,
        review_velocity_lifetime=review_velocity_lifetime,
        review_velocity_last_30d=last_30d,
        velocity_trend=classify_velocity_trend(existing_trend, last_30d, days_since_release),
        is_evergreen=check_evergreen(days_since_release, last_30d),
        launch_trajectory=classify_trajectory(
            review_velocity_lifetime, last_30d, days_since_release
        ),
    )
