"""Tests for matview_refresh/refresh_one.py — worker returns failures as data."""

from typing import Any
from unittest.mock import MagicMock, patch

import psycopg2

from tests.conftest import MockLambdaContext


def _get_module(mock_repo: MagicMock) -> Any:
    with (
        patch(
            "lambda_functions.matview_refresh.refresh_one.MatviewRepository",
            return_value=mock_repo,
        ),
        patch("lambda_functions.matview_refresh.refresh_one.get_conn"),
    ):
        import importlib

        import lambda_functions.matview_refresh.refresh_one as mod

        importlib.reload(mod)
        mod._repo = mock_repo
        return mod


def test_worker_success_returns_duration() -> None:
    """Happy path: {"name", "success": true, "duration_ms"}."""
    mock_repo = MagicMock()
    mock_repo.refresh_one.return_value = 1234

    mod = _get_module(mock_repo)
    result = mod.handler({"name": "mv_genre_counts", "cycle_id": "c1"}, MockLambdaContext())

    assert result["name"] == "mv_genre_counts"
    assert result["success"] is True
    assert result["duration_ms"] == 1234
    assert result["error"] == ""


def test_worker_captures_failure_as_data() -> None:
    """refresh_one raising psycopg2.Error → success=false, no re-raise.

    Map state needs a successful Lambda result to aggregate partial failures
    at Finalize instead of aborting under default retry behavior.
    """
    mock_repo = MagicMock()
    mock_repo.refresh_one.side_effect = psycopg2.Error("boom")

    mod = _get_module(mock_repo)
    result = mod.handler({"name": "mv_genre_counts", "cycle_id": "c1"}, MockLambdaContext())

    assert result["success"] is False
    assert "boom" in result["error"]
    assert result["duration_ms"] == 0


def test_worker_captures_value_error_as_data() -> None:
    """Unknown view name (repo raises ValueError) also returns as data."""
    mock_repo = MagicMock()
    mock_repo.refresh_one.side_effect = ValueError("Unknown matview name: 'bogus'")

    mod = _get_module(mock_repo)
    result = mod.handler({"name": "bogus", "cycle_id": "c1"}, MockLambdaContext())

    assert result["success"] is False
    assert "bogus" in result["error"]
