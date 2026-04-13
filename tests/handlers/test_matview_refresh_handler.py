"""Tests for admin/matview_refresh_handler.py — matview refresh with debounce.

Covers:
  1. Debounce skips refresh when last refresh was recent.
  2. batch-analysis-complete event bypasses debounce.
  3. Normal event respects debounce.
  4. Malformed SQS record does not crash _is_force_refresh.
"""

import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

from tests.conftest import MockLambdaContext


def _make_sqs_event(event_type: str) -> dict:
    """Build an SQS event with an SNS-wrapped message body."""
    sns_message = json.dumps({"event_type": event_type, "execution_id": "exec-1"})
    return {
        "Records": [
            {
                "messageId": "msg-1",
                "body": json.dumps({"Message": sns_message}),
            }
        ]
    }


def _get_module(mock_repo: MagicMock) -> Any:
    with patch(
        "lambda_functions.admin.matview_refresh_handler.MatviewRepository",
        return_value=mock_repo,
    ):
        with patch("lambda_functions.admin.matview_refresh_handler.get_conn"):
            import importlib

            import lambda_functions.admin.matview_refresh_handler as mod

            importlib.reload(mod)
            mod._repo = mock_repo
            return mod


def test_batch_analysis_complete_bypasses_debounce() -> None:
    """batch-analysis-complete event forces refresh even when debounced."""
    mock_repo = MagicMock()
    # Last refresh was 10 seconds ago — normally debounced
    mock_repo.get_last_refresh_time.return_value = time.time() - 10
    mock_repo.refresh_all.return_value = {"mv_test": True}
    mock_repo.log_refresh.return_value = None

    mod = _get_module(mock_repo)
    event = _make_sqs_event("batch-analysis-complete")

    result = mod.handler(event, MockLambdaContext())

    assert result["status"] == "refreshed"
    mock_repo.refresh_all.assert_called_once()


def test_normal_event_respects_debounce() -> None:
    """Non-force events are debounced when last refresh was recent."""
    mock_repo = MagicMock()
    mock_repo.get_last_refresh_time.return_value = time.time() - 10

    mod = _get_module(mock_repo)
    event = _make_sqs_event("report-ready")

    result = mod.handler(event, MockLambdaContext())

    assert result["status"] == "skipped"
    assert result["reason"] == "debounced"
    mock_repo.refresh_all.assert_not_called()


def test_malformed_record_does_not_crash() -> None:
    """Malformed SQS records are skipped without crashing."""
    mock_repo = MagicMock()
    mock_repo.get_last_refresh_time.return_value = time.time() - 10

    mod = _get_module(mock_repo)
    event = {"Records": [{"messageId": "bad", "body": "not-json"}]}

    # Should not raise — malformed record treated as non-force, then debounced
    result = mod.handler(event, MockLambdaContext())

    assert result["status"] == "skipped"
