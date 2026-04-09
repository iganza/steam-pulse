"""NewReleasesService — business logic for the /new-releases feed.

Handles window translation (today/week/month/quarter), filter passthrough
(genre, tag), headline counts, and bucketing for the upcoming lens. All data
access goes through NewReleasesRepository (which reads from mv_new_releases).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Literal

from library_layer.repositories.new_releases_repo import NewReleasesRepository

Window = Literal["today", "week", "month", "quarter"]

_PAGE_SIZE_MAX = 100


def _now() -> datetime:
    """Current UTC time. Separate function so tests can monkeypatch it."""
    return datetime.now(tz=UTC)


def _today() -> date:
    """Current UTC date. Separate function so tests can monkeypatch it."""
    return _now().date()


def _window_start(window: Window, now: datetime | None = None) -> datetime:
    """Lower bound for the Just Added lens (rolling TIMESTAMPTZ windows).

    The repo's WHERE clause is `discovered_at >= since`, so for N days of data
    we subtract exactly N days from NOW. `today` is a rolling 24h window.
    """
    now = now or _now()
    match window:
        case "today":
            return now - timedelta(hours=24)
        case "week":
            return now - timedelta(days=7)
        case "month":
            return now - timedelta(days=30)
        case "quarter":
            return now - timedelta(days=90)
        case _:
            raise ValueError(f"Unknown window: {window}")


def _window_start_date(window: Window, today: date | None = None) -> date:
    """Lower bound for the Released lens (inclusive DATE windows).

    The repo's WHERE clause is `release_date >= since AND release_date <= today`
    (both inclusive), so for N calendar days we subtract N-1. Example: `week`
    returns 6 days ago, producing a 7-day inclusive range (today and the six
    prior calendar days). `today` returns today itself — a single calendar day.
    """
    today = today or _today()
    match window:
        case "today":
            return today
        case "week":
            return today - timedelta(days=6)
        case "month":
            return today - timedelta(days=29)
        case "quarter":
            return today - timedelta(days=89)
        case _:
            raise ValueError(f"Unknown window: {window}")


def _clamp_page(page: int, page_size: int) -> tuple[int, int, int]:
    page = max(1, page)
    page_size = max(1, min(page_size, _PAGE_SIZE_MAX))
    offset = (page - 1) * page_size
    return page, page_size, offset


class NewReleasesService:
    """Three-lens new releases feed: Released / Coming Soon / Just Added."""

    def __init__(self, repo: NewReleasesRepository) -> None:
        self._repo = repo

    # ── Released ─────────────────────────────────────────────────────────────

    def get_released(
        self,
        window: Window,
        page: int,
        page_size: int,
        genre: str | None = None,
        tag: str | None = None,
    ) -> dict:
        page, page_size, offset = _clamp_page(page, page_size)
        today = _today()
        since = _window_start_date(window, today)
        items = self._repo.find_recently_released(
            since, today, page_size, offset, genre=genre, tag=tag
        )
        total = self._repo.count_released_between(since, today, genre=genre, tag=tag)
        return {
            "items": [it.model_dump(mode="json") for it in items],
            "total": total,
            "window": window,
            "page": page,
            "page_size": page_size,
            "filters": {"genre": genre, "tag": tag},
            "counts": self._released_counts(today, genre, tag),
        }

    def _released_counts(
        self, today: date, genre: str | None, tag: str | None
    ) -> dict[str, int]:
        return {
            "today": self._repo.count_released_between(
                _window_start_date("today", today), today, genre=genre, tag=tag
            ),
            "week": self._repo.count_released_between(
                _window_start_date("week", today), today, genre=genre, tag=tag
            ),
            "month": self._repo.count_released_between(
                _window_start_date("month", today), today, genre=genre, tag=tag
            ),
            "quarter": self._repo.count_released_between(
                _window_start_date("quarter", today), today, genre=genre, tag=tag
            ),
        }

    # ── Coming Soon ──────────────────────────────────────────────────────────

    def get_upcoming(
        self,
        page: int,
        page_size: int,
        genre: str | None = None,
        tag: str | None = None,
    ) -> dict:
        page, page_size, offset = _clamp_page(page, page_size)
        items = self._repo.find_upcoming(page_size, offset, genre=genre, tag=tag)
        total = self._repo.count_upcoming(genre=genre, tag=tag)
        # Buckets are a summary of the *full* filtered upcoming set, not just
        # the current page — computed in SQL by the repo so they stay
        # consistent as the user pages through results.
        buckets = self._repo.upcoming_bucket_counts(genre=genre, tag=tag)
        return {
            "items": [it.model_dump(mode="json") for it in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "filters": {"genre": genre, "tag": tag},
            "buckets": buckets,
        }

    # ── Just Added ───────────────────────────────────────────────────────────

    def get_added(
        self,
        window: Window,
        page: int,
        page_size: int,
        genre: str | None = None,
        tag: str | None = None,
    ) -> dict:
        page, page_size, offset = _clamp_page(page, page_size)
        now = _now()
        since = _window_start(window, now)
        items = self._repo.find_recently_added(
            since, page_size, offset, genre=genre, tag=tag
        )
        total = self._repo.count_added_since(since, genre=genre, tag=tag)
        return {
            "items": [it.model_dump(mode="json") for it in items],
            "total": total,
            "window": window,
            "page": page,
            "page_size": page_size,
            "filters": {"genre": genre, "tag": tag},
            "counts": self._added_counts(now, genre, tag),
        }

    def _added_counts(
        self, now: datetime, genre: str | None, tag: str | None
    ) -> dict[str, int]:
        return {
            "today": self._repo.count_added_since(
                _window_start("today", now), genre=genre, tag=tag
            ),
            "week": self._repo.count_added_since(
                _window_start("week", now), genre=genre, tag=tag
            ),
            "month": self._repo.count_added_since(
                _window_start("month", now), genre=genre, tag=tag
            ),
            "quarter": self._repo.count_added_since(
                _window_start("quarter", now), genre=genre, tag=tag
            ),
        }
