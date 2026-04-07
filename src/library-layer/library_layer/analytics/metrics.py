"""Metric registry for the Builder lens.

Single source of truth for the trend metrics exposed via
`GET /api/analytics/metrics` and consumed by `/api/analytics/trend-query`.
Adding a new metric is a backend-only change: append a `MetricDefinition`
to `METRIC_REGISTRY`, ensure the column exists in the trend matviews, done.
"""

from typing import Literal

from pydantic import BaseModel

MetricCategory = Literal[
    "volume",
    "sentiment",
    "pricing",
    "velocity",
    "early_access",
    "platform",
]
MetricUnit = Literal["count", "pct", "currency", "score"]
ChartHint = Literal["bar", "line", "stacked_area", "composed"]
# v1 of the registry reads from the trend matviews only. Engagement (playtime)
# metrics from `index_insights` and category metrics from game_categories are
# deferred to a follow-up — they require a different source path.
MetricSource = Literal["trend_matview"]


class MetricDefinition(BaseModel):
    id: str
    label: str
    description: str
    category: MetricCategory
    unit: MetricUnit
    source: MetricSource
    column: str
    default_chart_hint: ChartHint


def _m(
    id: str,
    label: str,
    description: str,
    category: MetricCategory,
    unit: MetricUnit,
    column: str,
    default_chart_hint: ChartHint,
) -> MetricDefinition:
    return MetricDefinition(
        id=id,
        label=label,
        description=description,
        category=category,
        unit=unit,
        source="trend_matview",
        column=column,
        default_chart_hint=default_chart_hint,
    )


_METRICS: list[MetricDefinition] = [
    # Volume
    _m("releases", "Releases", "Number of games released in the period.",
       "volume", "count", "releases", "bar"),
    _m("free_count", "Free Releases", "Number of free-to-play games released.",
       "volume", "count", "free_count", "bar"),
    # Sentiment
    _m("positive_count", "Positive Reviews", "Games with Steam positive_pct >= 70.",
       "sentiment", "count", "positive_count", "stacked_area"),
    _m("mixed_count", "Mixed Reviews", "Games with Steam positive_pct 40-70.",
       "sentiment", "count", "mixed_count", "stacked_area"),
    _m("negative_count", "Negative Reviews", "Games with Steam positive_pct < 40.",
       "sentiment", "count", "negative_count", "stacked_area"),
    _m("avg_steam_pct", "Avg Steam Positive %", "Average Steam positive_pct across releases.",
       "sentiment", "pct", "avg_steam_pct", "line"),
    _m("avg_metacritic", "Avg Metacritic", "Average Metacritic score across releases.",
       "sentiment", "score", "avg_metacritic", "line"),
    # Pricing
    _m("avg_paid_price", "Avg Paid Price", "Average price of non-free releases.",
       "pricing", "currency", "avg_paid_price", "line"),
    _m("free_pct", "Free %", "Share of releases that are free-to-play.",
       "pricing", "pct", "free_pct", "line"),
    # Velocity
    _m("velocity_under_1", "Velocity <1/day", "Releases with <1 review/day.",
       "velocity", "count", "velocity_under_1", "stacked_area"),
    _m("velocity_1_10", "Velocity 1-10/day", "Releases with 1-10 reviews/day.",
       "velocity", "count", "velocity_1_10", "stacked_area"),
    _m("velocity_10_50", "Velocity 10-50/day", "Releases with 10-50 reviews/day.",
       "velocity", "count", "velocity_10_50", "stacked_area"),
    _m("velocity_50_plus", "Velocity 50+/day", "Releases with 50+ reviews/day.",
       "velocity", "count", "velocity_50_plus", "stacked_area"),
    # Early access
    _m("ea_count", "Early Access Games", "Games that spent time in Early Access.",
       "early_access", "count", "ea_count", "bar"),
    _m("ea_pct", "Early Access %", "Share of releases that went through Early Access.",
       "early_access", "pct", "ea_pct", "line"),
    _m("ea_avg_steam_pct", "EA Avg Steam %", "Avg Steam positive_pct for EA releases.",
       "early_access", "pct", "ea_avg_steam_pct", "line"),
    _m("non_ea_avg_steam_pct", "Non-EA Avg Steam %", "Avg Steam positive_pct for non-EA releases.",
       "early_access", "pct", "non_ea_avg_steam_pct", "line"),
    # Platform
    _m("mac_pct", "Mac %", "Share of releases supporting macOS.",
       "platform", "pct", "mac_pct", "line"),
    _m("linux_pct", "Linux %", "Share of releases supporting Linux.",
       "platform", "pct", "linux_pct", "line"),
    _m("deck_verified_pct", "Deck Verified %", "Share of releases marked Steam Deck Verified.",
       "platform", "pct", "deck_verified_pct", "line"),
]

METRIC_REGISTRY: dict[str, MetricDefinition] = {m.id: m for m in _METRICS}


def get_metric(metric_id: str) -> MetricDefinition:
    """Look up a metric by id. Raises ValueError on unknown ids."""
    try:
        return METRIC_REGISTRY[metric_id]
    except KeyError:
        raise ValueError(f"unknown metric: {metric_id!r}") from None
