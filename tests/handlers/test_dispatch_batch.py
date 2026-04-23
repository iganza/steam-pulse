"""Tests for batch_analysis/dispatch_batch.py — the dispatch Lambda.

Covers:
  1. Returns top N appids ordered by review_count from the matview.
  2. dry_run returns candidates without starting an execution.
  3. Empty matview returns clean result with no execution started.
  4. batch_size override works.
  5. batch_size validation (non-positive, non-integer).
  6. post_batch action publishes BatchAnalysisCompleteEvent to SNS.

Module-level init (SteamPulseConfig, boto3 clients) runs at import time.
conftest.py seeds the required env vars; _get_module() defers the import
so it happens inside mock_aws where SSM is available.
"""

import json
from typing import Any
from unittest.mock import MagicMock

import boto3
from moto import mock_aws

from tests.conftest import MockLambdaContext

_SYSTEM_EVENTS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:system-events"


def _seed_ssm() -> None:
    ssm = boto3.client("ssm", region_name="us-east-1")
    ssm.put_parameter(
        Name="/steampulse/staging/batch/orchestrator-sfn-arn",
        Value="arn:aws:states:us-east-1:123:stateMachine:test-orchestrator",
        Type="String",
        Overwrite=True,
    )
    ssm.put_parameter(
        Name="/steampulse/test/messaging/system-events-topic-arn",
        Value=_SYSTEM_EVENTS_TOPIC_ARN,
        Type="String",
        Overwrite=True,
    )


def _get_module() -> Any:
    _seed_ssm()
    import lambda_functions.batch_analysis.dispatch_batch as db

    return db


def _mock_conn_with(appids: list[int]) -> MagicMock:
    """Create a mock connection whose cursor returns dict-like rows (RealDictCursor)."""
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [{"appid": a} for a in appids]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn


@mock_aws
def test_returns_top_n_candidates(monkeypatch: Any) -> None:
    mod = _get_module()

    mock_conn = _mock_conn_with([440, 730, 570])
    monkeypatch.setattr(mod, "get_conn", lambda **_kw: mock_conn)

    mock_sfn = MagicMock()
    mock_sfn.start_execution.return_value = {
        "executionArn": "arn:aws:states:us-east-1:123:execution:test:run-1"
    }
    monkeypatch.setattr(mod, "_sfn", mock_sfn)

    result = mod.handler({"batch_size": 3}, MockLambdaContext())

    assert result["dispatched"] == 3
    assert result["appids"] == [440, 730, 570]
    assert "execution_arn" in result
    mock_sfn.start_execution.assert_called_once()


@mock_aws
def test_dry_run_no_execution(monkeypatch: Any) -> None:
    mod = _get_module()

    mock_conn = _mock_conn_with([440, 730])
    monkeypatch.setattr(mod, "get_conn", lambda **_kw: mock_conn)

    mock_sfn = MagicMock()
    monkeypatch.setattr(mod, "_sfn", mock_sfn)

    result = mod.handler({"dry_run": True}, MockLambdaContext())

    assert result["dispatched"] == 2
    assert result["appids"] == [440, 730]
    assert result["dry_run"] is True
    assert "execution_arn" not in result
    mock_sfn.start_execution.assert_not_called()


@mock_aws
def test_empty_matview_no_execution(monkeypatch: Any) -> None:
    mod = _get_module()

    mock_conn = _mock_conn_with([])
    monkeypatch.setattr(mod, "get_conn", lambda **_kw: mock_conn)

    mock_sfn = MagicMock()
    monkeypatch.setattr(mod, "_sfn", mock_sfn)

    result = mod.handler({}, MockLambdaContext())

    assert result["dispatched"] == 0
    assert result["appids"] == []
    assert "execution_arn" not in result
    mock_sfn.start_execution.assert_not_called()


@mock_aws
def test_batch_size_override(monkeypatch: Any) -> None:
    mod = _get_module()

    mock_conn = _mock_conn_with([440, 730])
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(mod, "get_conn", lambda **_kw: mock_conn)

    mock_sfn = MagicMock()
    mock_sfn.start_execution.return_value = {
        "executionArn": "arn:aws:states:us-east-1:123:execution:test:run-2"
    }
    monkeypatch.setattr(mod, "_sfn", mock_sfn)

    result = mod.handler({"batch_size": 50}, MockLambdaContext())

    # Verify the SQL LIMIT used our override; the first bound param is
    # the MIN_CHUNKS_FOR_MERGE * chunk-size review floor.
    call_args = mock_cursor.execute.call_args
    assert call_args[0][1] == (mod._MIN_REVIEW_COUNT_FOR_BATCH, 50)
    assert result["dispatched"] == 2


@mock_aws
def test_batch_size_non_positive_uses_default(monkeypatch: Any) -> None:
    mod = _get_module()

    mock_conn = _mock_conn_with([440])
    monkeypatch.setattr(mod, "get_conn", lambda **_kw: mock_conn)

    mock_sfn = MagicMock()
    monkeypatch.setattr(mod, "_sfn", mock_sfn)

    # batch_size=0 should fall back to config default
    result = mod.handler({"batch_size": 0, "dry_run": True}, MockLambdaContext())
    assert result["dispatched"] == 1


@mock_aws
def test_batch_size_string_uses_default(monkeypatch: Any) -> None:
    mod = _get_module()

    mock_conn = _mock_conn_with([440])
    monkeypatch.setattr(mod, "get_conn", lambda **_kw: mock_conn)

    mock_sfn = MagicMock()
    monkeypatch.setattr(mod, "_sfn", mock_sfn)

    # batch_size="abc" should fall back to config default
    result = mod.handler({"batch_size": "abc", "dry_run": True}, MockLambdaContext())
    assert result["dispatched"] == 1


@mock_aws
def test_post_batch_publishes_event(monkeypatch: Any) -> None:
    mod = _get_module()

    # Create the SNS topic so publish succeeds
    sns = boto3.client("sns", region_name="us-east-1")
    sns.create_topic(Name="system-events")

    mock_sns = MagicMock()
    mock_sns.publish.return_value = {"MessageId": "test-msg-id"}
    monkeypatch.setattr(mod, "_sns", mock_sns)

    result = mod.handler(
        {"action": "post_batch", "execution_id": "exec-abc", "appids_count": 25},
        MockLambdaContext(),
    )

    assert result["status"] == "published"
    assert result["execution_id"] == "exec-abc"

    # Verify SNS publish was called with correct event_type and body
    mock_sns.publish.assert_called_once()
    call_kwargs = mock_sns.publish.call_args[1]
    assert call_kwargs["TopicArn"] == _SYSTEM_EVENTS_TOPIC_ARN
    assert call_kwargs["MessageAttributes"]["event_type"]["StringValue"] == "batch-analysis-complete"

    body = json.loads(call_kwargs["Message"])
    assert body["event_type"] == "batch-analysis-complete"
    assert body["execution_id"] == "exec-abc"
    assert body["appids_total"] == 25
