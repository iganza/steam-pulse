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
    mock_repo.get_last_refresh_time.return_value = time.time() - 10

    mod = _get_module(mock_repo)
    result = mod.handler({"force": False, "cycle_id": "c1"}, MockLambdaContext())

    assert result["skip"] is True
    assert result["cycle_id"] == "c1"
    mock_repo.start_cycle.assert_not_called()


def test_start_runs_when_no_recent_complete() -> None:
    """force=false + no recent cycle → skip=false, start_cycle inserted."""
    mock_repo = MagicMock()
    mock_repo.get_last_refresh_time.return_value = None

    mod = _get_module(mock_repo)
    result = mod.handler({"force": False, "cycle_id": "c2"}, MockLambdaContext())

    assert result["skip"] is False
    assert result["cycle_id"] == "c2"
    assert result["views"] == list(mod.MATVIEW_NAMES)
    assert result["start_time_ms"] > 0
    mock_repo.start_cycle.assert_called_once_with("c2")


def test_start_force_bypasses_debounce() -> None:
    """force=true + recent complete cycle → skip=false (debounce bypassed)."""
    mock_repo = MagicMock()
    mock_repo.get_last_refresh_time.return_value = time.time() - 10

    mod = _get_module(mock_repo)
    result = mod.handler({"force": True, "cycle_id": "c3"}, MockLambdaContext())

    assert result["skip"] is False
    mock_repo.start_cycle.assert_called_once_with("c3")
