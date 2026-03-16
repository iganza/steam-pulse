"""Time/datetime utilities."""

from datetime import UTC, datetime


def unix_to_datetime(ts: int) -> datetime:
    """Convert a Unix timestamp integer to a timezone-aware UTC datetime.

    Args:
        ts: Unix epoch seconds.

    Returns:
        A UTC-aware datetime object.
    """
    return datetime.fromtimestamp(ts, tz=UTC)
