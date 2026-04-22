"""Tests for matview_refresh/finalize.py — aggregate Map results into log."""

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import MockLambdaContext


def _get_module(mock_repo: MagicMock) -> Any:
    with (
        patch(
            "lambda_functions.matview_refresh.finalize.MatviewRepository",
            return_value=mock_repo,
        ),
        patch("lambda_functions.matview_refresh.finalize.get_conn"),
    ):
        import importlib

        import lambda_functions.matview_refresh.finalize as mod

        importlib.reload(mod)
        mod._repo = mock_repo
        return mod


def _event(results: list[dict], cycle_id: str = "c1") -> dict:
    return {
        "cycle_id": cycle_id,
        "start_time_ms": int(time.time() * 1000) - 100,
        "results": results,
    }


def test_finalize_all_success() -> None:
    """All successes → status='complete', no raise."""
    mock_repo = MagicMock()
    mod = _get_module(mock_repo)

    result = mod.handler(
        _event(
            [
                {"name": "mv_a", "success": True, "duration_ms": 100, "error": ""},
                {"name": "mv_b", "success": True, "duration_ms": 200, "error": ""},
            ]
        ),
        MockLambdaContext(),
    )

    assert result["status"] == "complete"
    assert result["success_count"] == 2
    assert result["failure_count"] == 0
    mock_repo.complete_cycle.assert_called_once()


def test_finalize_partial_failure_raises_with_failed_names() -> None:
    """Mixed → cycle persisted, then raises so SFN is marked Failed (not Succeeded)."""
    mock_repo = MagicMock()
    mod = _get_module(mock_repo)

    with pytest.raises(RuntimeError, match="mv_b"):
        mod.handler(
            _event(
                [
                    {"name": "mv_a", "success": True, "duration_ms": 100, "error": ""},
                    {"name": "mv_b", "success": False, "duration_ms": 0, "error": "boom"},
                ]
            ),
            MockLambdaContext(),
        )
    # Cycle row is persisted before the raise so operators can inspect per_view_results.
    mock_repo.complete_cycle.assert_called_once()


def test_finalize_all_failure_raises() -> None:
    """All failures → status='failed' + raise so SFN fails visibly."""
    mock_repo = MagicMock()
    mod = _get_module(mock_repo)

    with pytest.raises(RuntimeError):
        mod.handler(
            _event(
                [
                    {"name": "mv_a", "success": False, "duration_ms": 0, "error": "boom"},
                ]
            ),
            MockLambdaContext(),
        )
    # Still persisted the failure before raising.
    mock_repo.complete_cycle.assert_called_once()
