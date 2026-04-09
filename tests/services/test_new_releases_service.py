"""Unit tests for NewReleasesService — window math, bucketing, filters."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from library_layer.models.new_release import NewReleaseEntry
from library_layer.services import new_releases_service as nrs
from library_layer.services.new_releases_service import (
    NewReleasesService,
    _window_start,
    _window_start_date,
)

# Fixed date used by any test that touches `_today()` / `_now()` internally.
FIXED_TODAY = date(2026, 4, 8)
FIXED_NOW = datetime(2026, 4, 8, 12, 0, tzinfo=UTC)


@pytest.fixture
def frozen_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Freeze `_today()` / `_now()` in the service module so tests are
    deterministic across midnight. See PR #64 review comments."""
    monkeypatch.setattr(nrs, "_today", lambda: FIXED_TODAY)
    monkeypatch.setattr(nrs, "_now", lambda: FIXED_NOW)


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
    # Just Added uses rolling TIMESTAMPTZ windows — exactly 90 days.
    now = datetime(2026, 4, 8, tzinfo=UTC)
    assert _window_start("quarter", now) == now - timedelta(days=90)
    # Released uses inclusive DATE windows — N-1 days back for an N-day range.
    today = date(2026, 4, 8)
    assert _window_start_date("quarter", today) == today - timedelta(days=89)


def test_window_start_date_week_is_inclusive_7_days() -> None:
    """Released 'week' must return 6 days ago so `since..today` inclusive = 7d."""
    today = date(2026, 4, 8)
    assert _window_start_date("week", today) == today - timedelta(days=6)
    assert _window_start_date("month", today) == today - timedelta(days=29)
    assert _window_start_date("today", today) == today


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
    # 1 total + 4 headline counts (today/week/month/quarter) = 5
    assert repo.count_released_between.call_count == 5


def test_get_released_quarter_passes_89d_lower_bound(frozen_time: None) -> None:
    """Released 'quarter' = 90 inclusive calendar days → since is 89 days back.

    Uses `frozen_time` so the test doesn't tip over midnight.
    """
    repo = MagicMock()
    repo.find_recently_released.return_value = []
    repo.count_released_between.return_value = 0
    svc = NewReleasesService(repo)

    svc.get_released("quarter", page=1, page_size=24)

    args, _ = repo.find_recently_released.call_args
    since = args[0]
    assert since is not None
    assert (FIXED_TODAY - since) == timedelta(days=89)


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


def test_get_added_translates_window_to_datetime(frozen_time: None) -> None:
    """`get_added("today")` must pass `FIXED_NOW - 24h` to the repo.

    Uses `frozen_time` and asserts an exact value — previously this test
    compared against the wall clock with a 23-25h tolerance, which could
    still flake under slow CI or debugger pauses.
    """
    repo = MagicMock()
    repo.find_recently_added.return_value = []
    repo.count_added_since.return_value = 0
    svc = NewReleasesService(repo)

    svc.get_added("today", page=1, page_size=24)

    args, _ = repo.find_recently_added.call_args
    since = args[0]
    assert since == FIXED_NOW - timedelta(hours=24)


def test_get_added_passes_filters() -> None:
    repo = MagicMock()
    repo.find_recently_added.return_value = []
    repo.count_added_since.return_value = 0
    svc = NewReleasesService(repo)

    svc.get_added("week", page=1, page_size=24, genre="indie", tag=None)

    _, kwargs = repo.find_recently_added.call_args
    assert kwargs["genre"] == "indie"
    assert kwargs["tag"] is None


def test_get_upcoming_buckets_from_repo_aggregate() -> None:
    """Buckets come from the repo's SQL aggregate, not the paginated items.

    This matters because the previous implementation computed buckets by
    iterating the current page only — the numbers changed as the user paged.
    The repo aggregate reflects the full filtered upcoming set.
    """
    repo = MagicMock()
    repo.find_upcoming.return_value = []
    repo.count_upcoming.return_value = 4
    repo.upcoming_bucket_counts.return_value = {
        "this_week": 1, "this_month": 1, "this_quarter": 1, "tba": 1,
    }
    svc = NewReleasesService(repo)

    result = svc.get_upcoming(page=1, page_size=24)

    # Service should have delegated bucketing to the repo with the same filters.
    repo.upcoming_bucket_counts.assert_called_once_with(genre=None, tag=None)
    assert result["buckets"] == {
        "this_week": 1, "this_month": 1, "this_quarter": 1, "tba": 1,
    }


def test_get_upcoming_delegates_bucket_upper_bound_to_repo() -> None:
    """Documents the contract: service passes through whatever the repo returns.

    The SQL inside `upcoming_bucket_counts()` bounds `this_quarter` to
    `<= CURRENT_DATE + 90 days` so a game releasing in 2028 can't inflate
    the "later this quarter" number — this test just ensures the service
    layer doesn't post-process/override the repo's values.
    """
    repo = MagicMock()
    repo.find_upcoming.return_value = []
    repo.count_upcoming.return_value = 1000  # many upcoming rows overall
    repo.upcoming_bucket_counts.return_value = {
        "this_week": 2, "this_month": 10, "this_quarter": 25, "tba": 40,
    }
    svc = NewReleasesService(repo)

    result = svc.get_upcoming(page=1, page_size=24)

    # Sum of buckets (77) != total (1000) by design — anything beyond +90d
    # is in `total` but not in any bucket. Service must not reconcile these.
    assert sum(result["buckets"].values()) < result["total"]
    assert result["buckets"]["this_quarter"] == 25


def test_get_upcoming_buckets_respect_filters() -> None:
    """Bucket aggregate must receive the same genre/tag filters as the list."""
    repo = MagicMock()
    repo.find_upcoming.return_value = []
    repo.count_upcoming.return_value = 0
    repo.upcoming_bucket_counts.return_value = {
        "this_week": 0, "this_month": 0, "this_quarter": 0, "tba": 0,
    }
    svc = NewReleasesService(repo)

    svc.get_upcoming(page=1, page_size=24, genre="indie", tag="roguelike")

    repo.upcoming_bucket_counts.assert_called_once_with(genre="indie", tag="roguelike")


def test_get_upcoming_passes_filters() -> None:
    repo = MagicMock()
    repo.find_upcoming.return_value = []
    repo.count_upcoming.return_value = 0
    repo.upcoming_bucket_counts.return_value = {
        "this_week": 0, "this_month": 0, "this_quarter": 0, "tba": 0,
    }
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
