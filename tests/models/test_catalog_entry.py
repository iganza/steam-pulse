"""Tests for CatalogEntry computed properties — all 4 state machine permutations."""

from datetime import datetime, timezone

from library_layer.models.catalog import CatalogEntry

NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _entry(**kwargs: object) -> CatalogEntry:
    return CatalogEntry(appid=1, name="G", **kwargs)


# ── Permutation 1: cursor=None, completed_at=None → not_started ─────────────


def test_not_started_properties() -> None:
    e = _entry(review_cursor=None, reviews_completed_at=None)
    assert e.review_not_started is True
    assert e.review_in_progress is False
    assert e.review_complete is False


# ── Permutation 2: cursor=non-None, completed_at=None → in_progress (first crawl)


def test_in_progress_first_crawl_properties() -> None:
    e = _entry(review_cursor="abc123", reviews_completed_at=None)
    assert e.review_not_started is False
    assert e.review_in_progress is True
    assert e.review_complete is False


# ── Permutation 3: cursor=non-None, completed_at=non-None → in_progress (re-crawl)


def test_in_progress_recrawl_properties() -> None:
    e = _entry(review_cursor="xyz789", reviews_completed_at=NOW)
    assert e.review_not_started is False
    assert e.review_in_progress is True
    assert e.review_complete is False


# ── Permutation 4: cursor=None, completed_at=non-None → complete ────────────


def test_complete_properties() -> None:
    e = _entry(review_cursor=None, reviews_completed_at=NOW)
    assert e.review_not_started is False
    assert e.review_in_progress is False
    assert e.review_complete is True


# ── Exhaustiveness: exactly one property True per state ─────────────────────


def test_exactly_one_property_true_per_permutation() -> None:
    cases = [
        _entry(review_cursor=None, reviews_completed_at=None),       # not_started
        _entry(review_cursor="abc", reviews_completed_at=None),      # in_progress (first)
        _entry(review_cursor="abc", reviews_completed_at=NOW),       # in_progress (re-crawl)
        _entry(review_cursor=None, reviews_completed_at=NOW),        # complete
    ]
    for entry in cases:
        true_count = sum([entry.review_not_started, entry.review_in_progress, entry.review_complete])
        assert true_count == 1, (
            f"Expected exactly one True for cursor={entry.review_cursor!r} "
            f"completed_at={entry.reviews_completed_at!r}, got {true_count}"
        )
