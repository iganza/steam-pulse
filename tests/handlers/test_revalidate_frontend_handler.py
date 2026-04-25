"""Tests for revalidate_frontend handler — SQS → POST /api/revalidate."""

import json
import os
from typing import Any

import boto3
import pytest
from moto import mock_aws
from pytest_httpx import HTTPXMock

from tests.conftest import MockLambdaContext

_FRONTEND_BASE_URL = "https://frontend.example.lambda-url.us-west-2.on.aws"
_REVALIDATE_TOKEN_PARAM = "/steampulse/test/frontend/revalidate-token"
_TOKEN = "test-token-abc123"


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
    """Force re-import so module-level SSM lookup runs under moto."""
    import sys

    sys.modules.pop("lambda_functions.revalidate_frontend.handler", None)
    sys.modules.pop("lambda_functions.revalidate_frontend", None)


@pytest.fixture(autouse=True)
def _env() -> None:
    os.environ["FRONTEND_BASE_URL"] = _FRONTEND_BASE_URL
    os.environ["REVALIDATE_TOKEN_PARAM"] = _REVALIDATE_TOKEN_PARAM
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


def _seed_ssm() -> None:
    ssm = boto3.client("ssm", region_name="us-east-1")
    ssm.put_parameter(
        Name=_REVALIDATE_TOKEN_PARAM,
        Value=_TOKEN,
        Type="String",
        Overwrite=True,
    )


def _get_module() -> Any:
    """Re-seed SSM and reset the lazy http client between tests."""
    _seed_ssm()
    import lambda_functions.revalidate_frontend.handler as h

    h._http_client = None
    return h


def _sns_wrapped_event(appid: int, message_id: str = "msg-1") -> dict:
    """Build an SQS record whose body is the SNS notification envelope."""
    inner = {"event_type": "report-ready", "appid": appid, "game_name": "Test"}
    body = {
        "Type": "Notification",
        "TopicArn": "arn:aws:sns:us-east-1:123:content-events",
        "Message": json.dumps(inner),
    }
    return {
        "Records": [
            {
                "messageId": message_id,
                "body": json.dumps(body),
                "receiptHandle": "receipt",
            }
        ],
    }


def _multi_record_event(records: list[tuple[int, str]]) -> dict:
    """Build a multi-record event from [(appid, message_id), ...]."""
    return {
        "Records": [
            {
                "messageId": message_id,
                "body": json.dumps(
                    {
                        "Type": "Notification",
                        "Message": json.dumps(
                            {"event_type": "report-ready", "appid": appid}
                        ),
                    }
                ),
                "receiptHandle": "receipt",
            }
            for appid, message_id in records
        ],
    }


@mock_aws
def test_happy_path_posts_revalidate_with_token_and_appid(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{_FRONTEND_BASE_URL}/api/revalidate",
        json={"ok": True, "appid": 12345, "now": 0},
    )
    handler = _get_module()
    result = handler.handler(_sns_wrapped_event(12345), MockLambdaContext())

    assert result == {"batchItemFailures": []}
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    req = requests[0]
    assert req.headers["x-revalidate-token"] == _TOKEN
    assert json.loads(req.content) == {"appid": 12345}


@mock_aws
def test_non_2xx_returns_batch_item_failure(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{_FRONTEND_BASE_URL}/api/revalidate",
        status_code=500,
        json={"ok": False, "error": "boom"},
    )
    handler = _get_module()
    result = handler.handler(_sns_wrapped_event(99, message_id="msg-99"), MockLambdaContext())

    assert result == {"batchItemFailures": [{"itemIdentifier": "msg-99"}]}


@mock_aws
def test_missing_appid_returns_batch_item_failure(httpx_mock: HTTPXMock) -> None:
    handler = _get_module()
    bad_event = {
        "Records": [
            {
                "messageId": "bad-1",
                "body": json.dumps(
                    {
                        "Type": "Notification",
                        "Message": json.dumps({"event_type": "report-ready"}),
                    }
                ),
                "receiptHandle": "r",
            }
        ],
    }
    result = handler.handler(bad_event, MockLambdaContext())

    assert result == {"batchItemFailures": [{"itemIdentifier": "bad-1"}]}
    # No HTTP call attempted when appid extraction fails.
    assert httpx_mock.get_requests() == []


@mock_aws
def test_partial_batch_failure_only_reports_failed_record(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{_FRONTEND_BASE_URL}/api/revalidate",
        json={"ok": True, "appid": 1, "now": 0},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{_FRONTEND_BASE_URL}/api/revalidate",
        status_code=502,
        json={"ok": False},
    )
    handler = _get_module()
    result = handler.handler(
        _multi_record_event([(1, "ok-msg"), (2, "fail-msg")]),
        MockLambdaContext(),
    )

    assert result == {"batchItemFailures": [{"itemIdentifier": "fail-msg"}]}


@mock_aws
def test_unwrapped_sqs_body_also_parses(httpx_mock: HTTPXMock) -> None:
    """Defensive path: direct SQS message with no SNS wrapping still parses."""
    httpx_mock.add_response(
        method="POST",
        url=f"{_FRONTEND_BASE_URL}/api/revalidate",
        json={"ok": True, "appid": 7, "now": 0},
    )
    handler = _get_module()
    direct_event = {
        "Records": [
            {
                "messageId": "direct-1",
                "body": json.dumps({"event_type": "report-ready", "appid": 7}),
                "receiptHandle": "r",
            }
        ],
    }
    result = handler.handler(direct_event, MockLambdaContext())

    assert result == {"batchItemFailures": []}
    assert len(httpx_mock.get_requests()) == 1
