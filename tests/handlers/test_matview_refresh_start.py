"""Tests for matview_refresh/start.py — debounce gate + cycle bookkeeping."""

import time
from typing import Any
from unittest.mock import MagicMock, patch

from tests.conftest import MockLambdaContext


def _get_module(mock_repo: MagicMock) -> Any:
    with (
        patch("lambda_functions.matview_refresh.start.MatviewRepository", return_value=mock_repo),
        patch("lambda_functions.matview_refresh.start.get_conn"),
    ):
        import importlib

        import lambda_functions.matview_refresh.start as mod

        importlib.reload(mod)
        mod._repo = mock_repo
        return mod


def test_start_debounces_when_recent_complete() -> None:
    """force=false + recent complete cycle → skip=true, no start_cycle call."""
    mock_repo = MagicMock()
    mock_repo.get_running_cycle_id.return_value = None
    mock_repo.get_last_refresh_time.return_value = time.time() - 10

    mod = _get_module(mock_repo)
    result = mod.handler({"force": False, "cycle_id": "c1"}, MockLambdaContext())

    assert result["skip"] is True
    assert result["cycle_id"] == "c1"
    mock_repo.start_cycle.assert_not_called()


def test_start_runs_when_no_recent_complete() -> None:
    """force=false + no running + no recent cycle → skip=false, start_cycle inserted."""
    mock_repo = MagicMock()
    mock_repo.get_running_cycle_id.return_value = None
    mock_repo.get_last_refresh_time.return_value = None

    mod = _get_module(mock_repo)
    result = mod.handler({"force": False, "cycle_id": "c2"}, MockLambdaContext())

    assert result["skip"] is False
    assert result["cycle_id"] == "c2"
    assert result["views"] == list(mod.MATVIEW_NAMES)
    assert result["start_time_ms"] > 0
    mock_repo.start_cycle.assert_called_once_with("c2")


def test_start_returns_subset_for_report_ready_trigger() -> None:
    """trigger_event=report-ready → views list narrows to REPORT_DEPENDENT_VIEWS."""
    mock_repo = MagicMock()
    mock_repo.get_running_cycle_id.return_value = None
    mock_repo.get_last_refresh_time.return_value = None

    mod = _get_module(mock_repo)
    result = mod.handler(
        {"force": False, "cycle_id": "c-rr", "trigger_event": "report-ready"},
        MockLambdaContext(),
    )

    assert result["skip"] is False
    assert result["views"] == list(mod.REPORT_DEPENDENT_VIEWS)
    mock_repo.start_cycle.assert_called_once_with("c-rr")


def test_start_returns_full_list_for_batch_analysis_complete() -> None:
    """trigger_event=batch-analysis-complete → full matview list (force path)."""
    mock_repo = MagicMock()

    mod = _get_module(mock_repo)
    result = mod.handler(
        {"force": True, "cycle_id": "c-bac", "trigger_event": "batch-analysis-complete"},
        MockLambdaContext(),
    )

    assert result["skip"] is False
    assert result["views"] == list(mod.MATVIEW_NAMES)


def test_start_returns_full_list_for_catalog_refresh_complete() -> None:
    """trigger_event=catalog-refresh-complete → full matview list."""
    mock_repo = MagicMock()
    mock_repo.get_running_cycle_id.return_value = None
    mock_repo.get_last_refresh_time.return_value = None

    mod = _get_module(mock_repo)
    result = mod.handler(
        {"force": False, "cycle_id": "c-crc", "trigger_event": "catalog-refresh-complete"},
        MockLambdaContext(),
    )

    assert result["skip"] is False
    assert result["views"] == list(mod.MATVIEW_NAMES)


def test_start_defaults_to_full_list_when_trigger_event_empty() -> None:
    """Empty trigger_event (EB cron / operator CLI) → full matview list."""
    mock_repo = MagicMock()
    mock_repo.get_running_cycle_id.return_value = None
    mock_repo.get_last_refresh_time.return_value = None

    mod = _get_module(mock_repo)
    result = mod.handler(
        {"force": False, "cycle_id": "c-empty", "trigger_event": ""},
        MockLambdaContext(),
    )

    assert result["skip"] is False
    assert result["views"] == list(mod.MATVIEW_NAMES)


def test_start_debounce_skip_ignores_trigger_event() -> None:
    """Debounce still short-circuits a report-ready trigger — subset is covered by the last full cycle."""
    mock_repo = MagicMock()
    mock_repo.get_running_cycle_id.return_value = None
    mock_repo.get_last_refresh_time.return_value = time.time() - 10

    mod = _get_module(mock_repo)
    result = mod.handler(
        {"force": False, "cycle_id": "c-rr", "trigger_event": "report-ready"},
        MockLambdaContext(),
    )

    assert result["skip"] is True
    assert result["views"] == []
    mock_repo.start_cycle.assert_not_called()


def test_start_force_bypasses_debounce_and_running_guard() -> None:
    """force=true skips both the in-flight guard and the debounce check."""
    mock_repo = MagicMock()
    mock_repo.get_running_cycle_id.return_value = "cycle-in-flight"
    mock_repo.get_last_refresh_time.return_value = time.time() - 10

    mod = _get_module(mock_repo)
    result = mod.handler({"force": True, "cycle_id": "c3"}, MockLambdaContext())

    assert result["skip"] is False
    mock_repo.start_cycle.assert_called_once_with("c3")
    # force path must not even read the running / debounce state.
    mock_repo.get_running_cycle_id.assert_not_called()
    mock_repo.get_last_refresh_time.assert_not_called()


def test_start_skips_when_cycle_running() -> None:
    """In-flight guard: skip when there's a non-stale running cycle."""
    mock_repo = MagicMock()
    mock_repo.get_running_cycle_id.return_value = "cycle-in-flight"
    mock_repo.get_last_refresh_time.return_value = None  # even if no recent complete

    mod = _get_module(mock_repo)
    result = mod.handler({"force": False, "cycle_id": "c4"}, MockLambdaContext())

    assert result["skip"] is True
    mock_repo.start_cycle.assert_not_called()
    # debounce is not evaluated once the in-flight guard short-circuits.
    mock_repo.get_last_refresh_time.assert_not_called()


def test_start_passes_stale_cutoff_to_repo() -> None:
    """Start calls get_running_cycle_id with the configured stale threshold."""
    mock_repo = MagicMock()
    mock_repo.get_running_cycle_id.return_value = None
    mock_repo.get_last_refresh_time.return_value = None

    mod = _get_module(mock_repo)
    mod.handler({"force": False, "cycle_id": "c5"}, MockLambdaContext())

    mock_repo.get_running_cycle_id.assert_called_once_with(mod.RUNNING_STALE_SECONDS)
