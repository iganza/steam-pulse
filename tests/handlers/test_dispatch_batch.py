"""Tests for batch_analysis/dispatch_batch.py — the dispatch Lambda.

Covers:
  1. Auto-dispatch path is disabled — any non-post_batch event raises.
  2. post_batch action publishes BatchAnalysisCompleteEvent to SNS.

Module-level init (SteamPulseConfig, boto3 clients) runs at import time.
conftest.py seeds the required env vars; _get_module() defers the import
so it happens inside mock_aws where SSM is available.
"""

import json
from typing import Any
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

from tests.conftest import MockLambdaContext

_SYSTEM_EVENTS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:system-events"


def _seed_ssm() -> None:
    ssm = boto3.client("ssm", region_name="us-east-1")
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


@mock_aws
def test_auto_dispatch_is_disabled() -> None:
    mod = _get_module()

    with pytest.raises(RuntimeError, match="auto-dispatch path is disabled"):
        mod.handler({"batch_size": 3}, MockLambdaContext())


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
