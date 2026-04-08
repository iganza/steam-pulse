"""Unit tests for NewReleasesService — window math, bucketing, filters."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

from library_layer.models.new_release import NewReleaseEntry
from library_layer.services.new_releases_service import (
    NewReleasesService,
    _window_start,
    _window_start_date,
)


def _entry(appid: int, release_date: date | None = None, coming_soon: bool = False) -> NewReleaseEntry:
    return NewReleaseEntry(
        appid=appid,
        name=f"Game {appid}",
        slug=f"game-{appid}",
        discovered_at=datetime.now(tz=UTC),
        release_date=release_date,
        coming_soon=coming_soon,
    )


def test_window_start_today_is_24h_ago() -> None:
    now = datetime(2026, 4, 8, 12, 0, tzinfo=UTC)
    assert _window_start("today", now) == now - timedelta(hours=24)


def test_window_start_week_is_7d_ago() -> None:
    now = datetime(2026, 4, 8, tzinfo=UTC)
    assert _window_start("week", now) == now - timedelta(days=7)


def test_window_start_quarter_is_90d_ago() -> None:
    now = datetime(2026, 4, 8, tzinfo=UTC)
    assert _window_start("quarter", now) == now - timedelta(days=90)
    today = date(2026, 4, 8)
    assert _window_start_date("quarter", today) == today - timedelta(days=90)


def test_get_released_returns_envelope_and_counts() -> None:
    repo = MagicMock()
    repo.find_recently_released.return_value = [_entry(1, date(2026, 4, 7))]
    repo.count_released_between.return_value = 5
    svc = NewReleasesService(repo)

    result = svc.get_released("week", page=1, page_size=24)

    assert result["window"] == "week"
    assert result["total"] == 5
    assert len(result["items"]) == 1
    assert result["items"][0]["appid"] == 1
    assert set(result["counts"].keys()) == {"today", "week", "month", "quarter"}
    assert result["filters"] == {"genre": None, "tag": None}
    # 1 total + 4 headline counts (today/week/month/all) = 5
    assert repo.count_released_between.call_count == 5


def test_get_released_quarter_passes_90d_lower_bound() -> None:
    repo = MagicMock()
    repo.find_recently_released.return_value = []
    repo.count_released_between.return_value = 0
    svc = NewReleasesService(repo)

    svc.get_released("quarter", page=1, page_size=24)

    args, _ = repo.find_recently_released.call_args
    since = args[0]
    assert since is not None
    assert (date.today() - since) == timedelta(days=90)


def test_get_released_passes_genre_and_tag_filters() -> None:
    repo = MagicMock()
    repo.find_recently_released.return_value = []
    repo.count_released_between.return_value = 0
    svc = NewReleasesService(repo)

    result = svc.get_released("week", page=1, page_size=24, genre="action", tag="roguelike")

    assert result["filters"] == {"genre": "action", "tag": "roguelike"}
    _, kwargs = repo.find_recently_released.call_args
    assert kwargs["genre"] == "action"
    assert kwargs["tag"] == "roguelike"


def test_get_added_translates_window_to_datetime() -> None:
    repo = MagicMock()
    repo.find_recently_added.return_value = []
    repo.count_added_since.return_value = 0
    svc = NewReleasesService(repo)

    svc.get_added("today", page=1, page_size=24)

    args, _ = repo.find_recently_added.call_args
    since = args[0]
    assert since is not None
    assert since.tzinfo is not None
    delta = datetime.now(tz=UTC) - since
    assert timedelta(hours=23) < delta < timedelta(hours=25)


def test_get_added_passes_filters() -> None:
    repo = MagicMock()
    repo.find_recently_added.return_value = []
    repo.count_added_since.return_value = 0
    svc = NewReleasesService(repo)

    svc.get_added("week", page=1, page_size=24, genre="indie", tag=None)

    _, kwargs = repo.find_recently_added.call_args
    assert kwargs["genre"] == "indie"
    assert kwargs["tag"] is None


def test_get_upcoming_buckets_by_release_date() -> None:
    today = date.today()
    repo = MagicMock()
    repo.find_upcoming.return_value = [
        _entry(1, today + timedelta(days=3), coming_soon=True),    # this_week
        _entry(2, today + timedelta(days=20), coming_soon=True),   # this_month
        _entry(3, today + timedelta(days=60), coming_soon=True),   # this_quarter
        _entry(4, None, coming_soon=True),                         # tba
    ]
    repo.count_upcoming.return_value = 4
    svc = NewReleasesService(repo)

    result = svc.get_upcoming(page=1, page_size=24)

    assert result["buckets"]["this_week"] == 1
    assert result["buckets"]["this_month"] == 1
    assert result["buckets"]["this_quarter"] == 1
    assert result["buckets"]["tba"] == 1


def test_get_upcoming_passes_filters() -> None:
    repo = MagicMock()
    repo.find_upcoming.return_value = []
    repo.count_upcoming.return_value = 0
    svc = NewReleasesService(repo)

    svc.get_upcoming(page=1, page_size=24, genre="rpg", tag=None)

    _, kwargs = repo.find_upcoming.call_args
    assert kwargs["genre"] == "rpg"


def test_paging_clamps_negative_and_huge_values() -> None:
    repo = MagicMock()
    repo.find_recently_released.return_value = []
    repo.count_released_between.return_value = 0
    svc = NewReleasesService(repo)

    result = svc.get_released("week", page=-3, page_size=99999)

    assert result["page"] == 1
    assert result["page_size"] == 100  # clamped to MAX
