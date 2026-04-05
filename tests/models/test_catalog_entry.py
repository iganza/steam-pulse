"""Tests for CatalogEntry computed properties."""

from datetime import datetime, timezone

from library_layer.models.catalog import CatalogEntry

NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _entry(**kwargs: object) -> CatalogEntry:
    return CatalogEntry(appid=1, name="G", **kwargs)


# ── not_started: completed_at=None ──────────────────────────────────────────


def test_not_started_when_never_crawled() -> None:
    e = _entry(reviews_completed_at=None)
    assert e.review_not_started is True
    assert e.review_complete is False


# ── complete: completed_at=non-None ─────────────────────────────────────────


def test_complete_when_timestamp_set() -> None:
    e = _entry(reviews_completed_at=NOW)
    assert e.review_not_started is False
    assert e.review_complete is True


# ── Exhaustiveness: exactly one of the two states True ──────────────────────


def test_exactly_one_state_true_per_entry() -> None:
    cases = [
        _entry(reviews_completed_at=None),  # not_started
        _entry(reviews_completed_at=NOW),  # complete
    ]
    for entry in cases:
        assert entry.review_not_started != entry.review_complete, (
            f"Expected exactly one True for completed_at={entry.reviews_completed_at!r}"
        )
