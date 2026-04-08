"""NewReleasesService — business logic for the /new-releases feed.

Handles window translation (today/week/month/all), filter passthrough
(genre, tag), headline counts, and bucketing for the upcoming lens. All data
access goes through NewReleasesRepository (which reads from mv_new_releases).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Literal

from library_layer.repositories.new_releases_repo import NewReleasesRepository

Window = Literal["today", "week", "month", "all"]

_PAGE_SIZE_MAX = 100


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _window_start(window: Window, now: datetime | None = None) -> datetime | None:
    """Translate a window keyword to its lower bound (UTC). 'all' returns None."""
    now = now or _now()
    match window:
        case "today":
            return now - timedelta(hours=24)
        case "week":
            return now - timedelta(days=7)
        case "month":
            return now - timedelta(days=30)
        case "all":
            return None
        case _:
            raise ValueError(f"Unknown window: {window}")


def _window_start_date(window: Window, today: date | None = None) -> date | None:
    today = today or date.today()
    match window:
        case "today":
            return today
        case "week":
            return today - timedelta(days=7)
        case "month":
            return today - timedelta(days=30)
        case "all":
            return None
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
        today = date.today()
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
            "all": self._repo.count_released_between(
                None, today, genre=genre, tag=tag
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
        return {
            "items": [it.model_dump(mode="json") for it in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "filters": {"genre": genre, "tag": tag},
            "buckets": self._upcoming_buckets(items),
        }

    @staticmethod
    def _upcoming_buckets(items: list) -> dict[str, int]:
        today = date.today()
        week = today + timedelta(days=7)
        month = today + timedelta(days=30)
        b = {"this_week": 0, "this_month": 0, "this_quarter": 0, "tba": 0}
        for it in items:
            rd = it.release_date
            if rd is None:
                b["tba"] += 1
            elif rd <= week:
                b["this_week"] += 1
            elif rd <= month:
                b["this_month"] += 1
            else:
                b["this_quarter"] += 1
        return b

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
            "all": self._repo.count_added_since(None, genre=genre, tag=tag),
        }
