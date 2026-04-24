"""Tests for matview_refresh/start.py — cycle bookkeeping + full matview list."""

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


def test_start_records_cycle_and_returns_full_matview_list() -> None:
    """Handler inserts a running row and returns the full MATVIEW_NAMES list."""
    mock_repo = MagicMock()

    mod = _get_module(mock_repo)
    result = mod.handler({"cycle_id": "c1"}, MockLambdaContext())

    assert result["cycle_id"] == "c1"
    assert result["views"] == list(mod.MATVIEW_NAMES)
    assert result["start_time_ms"] > 0
    mock_repo.start_cycle.assert_called_once_with("c1")
