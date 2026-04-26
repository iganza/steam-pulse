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
_FRONTEND_BUCKET = "test-frontend-bucket"
_CACHE_KEY_PREFIX = "cache/test-build/"
_BUILD_ID = "test-build"


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
    os.environ["FRONTEND_BUCKET"] = _FRONTEND_BUCKET
    os.environ["CACHE_BUCKET_KEY_PREFIX"] = _CACHE_KEY_PREFIX
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


def _seed_ssm_and_bucket() -> None:
    ssm = boto3.client("ssm", region_name="us-east-1")
    ssm.put_parameter(
        Name=_REVALIDATE_TOKEN_PARAM,
        Value=_TOKEN,
        Type="String",
        Overwrite=True,
    )
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=_FRONTEND_BUCKET)


def _cache_key(appid: int, slug: str) -> str:
    return f"{_CACHE_KEY_PREFIX}{_BUILD_ID}/games/{appid}/{slug}"


def _put_page_cache(appid: int, slug: str) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    base = _cache_key(appid, slug)
    s3.put_object(Bucket=_FRONTEND_BUCKET, Key=f"{base}.cache", Body=b"<html/>")
    s3.put_object(Bucket=_FRONTEND_BUCKET, Key=f"{base}.cache.meta", Body=b"{}")


def _page_cache_keys_present(appid: int, slug: str) -> bool:
    s3 = boto3.client("s3", region_name="us-east-1")
    resp = s3.list_objects_v2(Bucket=_FRONTEND_BUCKET, Prefix=_cache_key(appid, slug))
    return resp.get("KeyCount", 0) > 0


def _get_module() -> Any:
    """Re-seed SSM and reset the lazy http client between tests."""
    _seed_ssm_and_bucket()
    import lambda_functions.revalidate_frontend.handler as h

    h._http_client = None
    return h


def _slug(appid: int) -> str:
    return f"test-game-{appid}"


def _sns_wrapped_event(appid: int, message_id: str = "msg-1") -> dict:
    """Build an SQS record whose body is the SNS notification envelope."""
    inner = {
        "event_type": "report-ready",
        "appid": appid,
        "game_name": "Test",
        "slug": _slug(appid),
    }
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
                            {
                                "event_type": "report-ready",
                                "appid": appid,
                                "slug": _slug(appid),
                            }
                        ),
                    }
                ),
                "receiptHandle": "receipt",
            }
            for appid, message_id in records
        ],
    }


@mock_aws
def test_happy_path_posts_revalidate_and_deletes_s3_page_cache(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{_FRONTEND_BASE_URL}/api/revalidate",
        json={"ok": True, "appid": 12345, "slug": _slug(12345), "now": 0},
    )
    handler = _get_module()
    _put_page_cache(12345, _slug(12345))
    assert _page_cache_keys_present(12345, _slug(12345))

    result = handler.handler(_sns_wrapped_event(12345), MockLambdaContext())

    assert result == {"batchItemFailures": []}
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    req = requests[0]
    assert req.headers["x-revalidate-token"] == _TOKEN
    assert json.loads(req.content) == {"appid": 12345, "slug": _slug(12345)}
    assert not _page_cache_keys_present(12345, _slug(12345)), (
        "page cache file + .meta should be deleted from S3"
    )


@mock_aws
def test_s3_delete_failure_returns_batch_item_failure(
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{_FRONTEND_BASE_URL}/api/revalidate",
        json={"ok": True, "appid": 1, "slug": _slug(1), "now": 0},
    )
    handler = _get_module()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated S3 outage")

    monkeypatch.setattr(handler._s3, "delete_objects", _boom)
    result = handler.handler(_sns_wrapped_event(1, message_id="s3-fail"), MockLambdaContext())

    assert result == {"batchItemFailures": [{"itemIdentifier": "s3-fail"}]}


@mock_aws
def test_s3_per_key_errors_returns_batch_item_failure(
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delete_objects returns 200 with `Errors` list — must surface as failure."""
    httpx_mock.add_response(
        method="POST",
        url=f"{_FRONTEND_BASE_URL}/api/revalidate",
        json={"ok": True, "appid": 2, "slug": _slug(2), "now": 0},
    )
    handler = _get_module()

    def _partial_failure(*_args: object, **_kwargs: object) -> dict:
        return {
            "Deleted": [{"Key": "ok-key"}],
            "Errors": [{"Key": "bad-key", "Code": "AccessDenied"}],
        }

    monkeypatch.setattr(handler._s3, "delete_objects", _partial_failure)
    result = handler.handler(
        _sns_wrapped_event(2, message_id="s3-partial"), MockLambdaContext()
    )

    assert result == {"batchItemFailures": [{"itemIdentifier": "s3-partial"}]}


def test_module_load_rejects_malformed_cache_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail fast at cold start if CACHE_BUCKET_KEY_PREFIX is wrong shape."""
    import sys

    monkeypatch.setenv("CACHE_BUCKET_KEY_PREFIX", "not-cache/foo/")
    sys.modules.pop("lambda_functions.revalidate_frontend.handler", None)
    with pytest.raises(ValueError, match="must match 'cache/"):
        import lambda_functions.revalidate_frontend.handler  # noqa: F401


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
def test_missing_slug_returns_batch_item_failure(httpx_mock: HTTPXMock) -> None:
    handler = _get_module()
    bad_event = {
        "Records": [
            {
                "messageId": "bad-slug",
                "body": json.dumps(
                    {
                        "Type": "Notification",
                        "Message": json.dumps(
                            {"event_type": "report-ready", "appid": 5}
                        ),
                    }
                ),
                "receiptHandle": "r",
            }
        ],
    }
    result = handler.handler(bad_event, MockLambdaContext())

    assert result == {"batchItemFailures": [{"itemIdentifier": "bad-slug"}]}
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
        json={"ok": True, "appid": 7, "slug": _slug(7), "now": 0},
    )
    handler = _get_module()
    direct_event = {
        "Records": [
            {
                "messageId": "direct-1",
                "body": json.dumps(
                    {"event_type": "report-ready", "appid": 7, "slug": _slug(7)}
                ),
                "receiptHandle": "r",
            }
        ],
    }
    result = handler.handler(direct_event, MockLambdaContext())

    assert result == {"batchItemFailures": []}
    assert len(httpx_mock.get_requests()) == 1
