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
_DISTRIBUTION_ID_PARAM = "/steampulse/test/delivery/distribution-id"
_DISTRIBUTION_ID = "EDFDVBD6EXAMPLE"
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
    os.environ["DISTRIBUTION_ID_PARAM"] = _DISTRIBUTION_ID_PARAM
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
    ssm.put_parameter(
        Name=_DISTRIBUTION_ID_PARAM,
        Value=_DISTRIBUTION_ID,
        Type="String",
        Overwrite=True,
    )
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=_FRONTEND_BUCKET)
    # Materialize the cache/{OUTER}/{INNER}/ CommonPrefix so the module-load
    # _discover_inner_build_ids() call finds the inner build id at import time.
    s3.put_object(
        Bucket=_FRONTEND_BUCKET,
        Key=f"{_CACHE_KEY_PREFIX}{_BUILD_ID}/_init",
        Body=b"",
    )


def _stub_cloudfront(handler: Any) -> list[dict]:
    """Replace handler._cloudfront.create_invalidation with a capturing stub.

    Returns the list that captures kwargs for each call.
    """
    captured: list[dict] = []

    def _capture(**kwargs: Any) -> dict:
        captured.append(kwargs)
        return {
            "Invalidation": {
                "Id": f"I{len(captured)}",
                "Status": "InProgress",
            }
        }

    handler._cloudfront.create_invalidation = _capture  # type: ignore[method-assign]
    return captured


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


def _get_module() -> tuple[Any, list[dict]]:
    """Re-seed SSM, reset the lazy http client, stub CloudFront, return (handler, captured).

    The returned `captured` list accumulates kwargs of every
    `create_invalidation` call made through the stubbed client. Tests that
    don't care about CloudFront can ignore it.
    """
    _seed_ssm_and_bucket()
    import lambda_functions.revalidate_frontend.handler as h

    h._http_client = None
    captured = _stub_cloudfront(h)
    return h, captured


def _slug(appid: int) -> str:
    return f"test-game-{appid}"


def _expected_paths(appids: list[int]) -> list[str]:
    """Per-appid CDN invalidation: HTML + 4 SSR-fanout API paths, sorted."""
    paths: set[str] = set()
    for appid in appids:
        paths.add(f"/games/{appid}/*")
        paths.add(f"/api/games/{appid}/report")
        paths.add(f"/api/games/{appid}/review-stats")
        paths.add(f"/api/games/{appid}/benchmarks")
        paths.add(f"/api/games/{appid}/related-analyzed")
    return sorted(paths)


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
    handler, _ = _get_module()
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
    handler, _ = _get_module()

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
    handler, _ = _get_module()

    def _partial_failure(*_args: object, **_kwargs: object) -> dict:
        return {
            "Deleted": [{"Key": "ok-key"}],
            "Errors": [{"Key": "bad-key", "Code": "AccessDenied"}],
        }

    monkeypatch.setattr(handler._s3, "delete_objects", _partial_failure)
    result = handler.handler(_sns_wrapped_event(2, message_id="s3-partial"), MockLambdaContext())

    assert result == {"batchItemFailures": [{"itemIdentifier": "s3-partial"}]}


@mock_aws
def test_module_load_rejects_malformed_cache_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail fast at cold start if CACHE_BUCKET_KEY_PREFIX is wrong shape."""
    import sys

    # Seed SSM so the token lookup at module load doesn't fail before reaching
    # the prefix validation.
    _seed_ssm_and_bucket()
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
    handler, _ = _get_module()
    result = handler.handler(_sns_wrapped_event(99, message_id="msg-99"), MockLambdaContext())

    assert result == {"batchItemFailures": [{"itemIdentifier": "msg-99"}]}


@mock_aws
def test_missing_appid_returns_batch_item_failure(httpx_mock: HTTPXMock) -> None:
    handler, _ = _get_module()
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
    handler, _ = _get_module()
    bad_event = {
        "Records": [
            {
                "messageId": "bad-slug",
                "body": json.dumps(
                    {
                        "Type": "Notification",
                        "Message": json.dumps({"event_type": "report-ready", "appid": 5}),
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
    handler, _ = _get_module()
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
    handler, _ = _get_module()
    direct_event = {
        "Records": [
            {
                "messageId": "direct-1",
                "body": json.dumps({"event_type": "report-ready", "appid": 7, "slug": _slug(7)}),
                "receiptHandle": "r",
            }
        ],
    }
    result = handler.handler(direct_event, MockLambdaContext())

    assert result == {"batchItemFailures": []}
    assert len(httpx_mock.get_requests()) == 1


@mock_aws
def test_happy_path_creates_cloudfront_invalidation(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{_FRONTEND_BASE_URL}/api/revalidate",
        json={"ok": True, "appid": 12345, "slug": _slug(12345), "now": 0},
    )
    handler, captured = _get_module()
    _put_page_cache(12345, _slug(12345))

    result = handler.handler(_sns_wrapped_event(12345), MockLambdaContext())

    assert result == {"batchItemFailures": []}
    assert len(captured) == 1
    call = captured[0]
    assert call["DistributionId"] == _DISTRIBUTION_ID
    expected = _expected_paths([12345])
    assert call["InvalidationBatch"]["Paths"] == {
        "Quantity": len(expected),
        "Items": expected,
    }
    assert call["InvalidationBatch"]["CallerReference"].startswith("revalidate-")


@mock_aws
def test_batched_invalidation_for_multiple_records(httpx_mock: HTTPXMock) -> None:
    for appid in (10, 20, 30):
        httpx_mock.add_response(
            method="POST",
            url=f"{_FRONTEND_BASE_URL}/api/revalidate",
            json={"ok": True, "appid": appid, "slug": _slug(appid), "now": 0},
        )
    handler, captured = _get_module()
    for appid in (10, 20, 30):
        _put_page_cache(appid, _slug(appid))

    result = handler.handler(
        _multi_record_event([(10, "m-10"), (20, "m-20"), (30, "m-30")]),
        MockLambdaContext(),
    )

    assert result == {"batchItemFailures": []}
    assert len(captured) == 1, "expected ONE invalidation covering all appids"
    paths = captured[0]["InvalidationBatch"]["Paths"]
    expected = _expected_paths([10, 20, 30])
    assert paths["Quantity"] == len(expected)
    assert paths["Items"] == expected


@mock_aws
def test_cloudfront_failure_marks_all_succeeded_records_as_failed(
    httpx_mock: HTTPXMock,
) -> None:
    for appid in (1, 2):
        httpx_mock.add_response(
            method="POST",
            url=f"{_FRONTEND_BASE_URL}/api/revalidate",
            json={"ok": True, "appid": appid, "slug": _slug(appid), "now": 0},
        )
    handler, _ = _get_module()

    def _boom(**_kwargs: Any) -> dict:
        raise RuntimeError("simulated CloudFront outage")

    handler._cloudfront.create_invalidation = _boom  # type: ignore[method-assign]

    for appid in (1, 2):
        _put_page_cache(appid, _slug(appid))

    result = handler.handler(
        _multi_record_event([(1, "ok-1"), (2, "ok-2")]),
        MockLambdaContext(),
    )

    assert result == {
        "batchItemFailures": [
            {"itemIdentifier": "ok-1"},
            {"itemIdentifier": "ok-2"},
        ]
    }


@mock_aws
def test_per_record_failure_does_not_block_invalidation_for_others(
    httpx_mock: HTTPXMock,
) -> None:
    """Records that succeed at /api/revalidate still get invalidated even if a sibling fails."""
    httpx_mock.add_response(
        method="POST",
        url=f"{_FRONTEND_BASE_URL}/api/revalidate",
        json={"ok": True, "appid": 100, "slug": _slug(100), "now": 0},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{_FRONTEND_BASE_URL}/api/revalidate",
        status_code=500,
        json={"ok": False},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{_FRONTEND_BASE_URL}/api/revalidate",
        json={"ok": True, "appid": 300, "slug": _slug(300), "now": 0},
    )
    handler, captured = _get_module()
    _put_page_cache(100, _slug(100))
    _put_page_cache(300, _slug(300))

    result = handler.handler(
        _multi_record_event([(100, "m-100"), (200, "m-200"), (300, "m-300")]),
        MockLambdaContext(),
    )

    assert result == {"batchItemFailures": [{"itemIdentifier": "m-200"}]}
    assert len(captured) == 1
    paths = captured[0]["InvalidationBatch"]["Paths"]
    assert paths["Items"] == _expected_paths([100, 300])


@mock_aws
def test_module_load_requires_distribution_id_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cold start must fail loudly if DISTRIBUTION_ID_PARAM is unset."""
    import sys

    _seed_ssm_and_bucket()
    monkeypatch.delenv("DISTRIBUTION_ID_PARAM", raising=False)
    sys.modules.pop("lambda_functions.revalidate_frontend.handler", None)
    with pytest.raises(KeyError):
        import lambda_functions.revalidate_frontend.handler  # noqa: F401


@mock_aws
def test_caller_reference_is_deterministic_across_retries(
    httpx_mock: HTTPXMock,
) -> None:
    """Same messageId set must produce the same CallerReference so CloudFront dedupes retries."""
    for _ in range(2):
        for appid in (10, 20):
            httpx_mock.add_response(
                method="POST",
                url=f"{_FRONTEND_BASE_URL}/api/revalidate",
                json={"ok": True, "appid": appid, "slug": _slug(appid), "now": 0},
            )
    handler, captured = _get_module()
    for appid in (10, 20):
        _put_page_cache(appid, _slug(appid))

    event = _multi_record_event([(10, "msg-A"), (20, "msg-B")])
    handler.handler(event, MockLambdaContext())
    for appid in (10, 20):
        _put_page_cache(appid, _slug(appid))
    handler.handler(event, MockLambdaContext())

    assert len(captured) == 2
    assert (
        captured[0]["InvalidationBatch"]["CallerReference"]
        == captured[1]["InvalidationBatch"]["CallerReference"]
    )


@mock_aws
def test_caller_reference_differs_across_distinct_batches(
    httpx_mock: HTTPXMock,
) -> None:
    """Distinct messageId sets must produce distinct CallerReferences."""
    for appid in (10, 20):
        httpx_mock.add_response(
            method="POST",
            url=f"{_FRONTEND_BASE_URL}/api/revalidate",
            json={"ok": True, "appid": appid, "slug": _slug(appid), "now": 0},
        )
    handler, captured = _get_module()
    for appid in (10, 20):
        _put_page_cache(appid, _slug(appid))

    handler.handler(_multi_record_event([(10, "msg-A")]), MockLambdaContext())
    handler.handler(_multi_record_event([(20, "msg-B")]), MockLambdaContext())

    assert len(captured) == 2
    assert (
        captured[0]["InvalidationBatch"]["CallerReference"]
        != captured[1]["InvalidationBatch"]["CallerReference"]
    )


@mock_aws
def test_no_records_skips_cloudfront_call(httpx_mock: HTTPXMock) -> None:
    """Empty / all-failed batches must NOT issue an invalidation."""
    handler, captured = _get_module()

    result = handler.handler({"Records": []}, MockLambdaContext())

    assert result == {"batchItemFailures": []}
    assert captured == []
    assert httpx_mock.get_requests() == []


@mock_aws
def test_module_load_discovers_inner_build_id() -> None:
    """Cold start lists cache/{OUTER}/ and populates _INNER_BUILD_IDS from CommonPrefixes."""
    handler, _ = _get_module()
    assert handler._INNER_BUILD_IDS == [_BUILD_ID]


@mock_aws
def test_delete_page_cache_iterates_all_inner_build_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When multiple inner ids are discovered, delete fires .cache + .cache.meta for each."""
    handler, _ = _get_module()
    monkeypatch.setattr(handler, "_INNER_BUILD_IDS", ["inner-a", "inner-b"])

    captured_kwargs: list[dict] = []

    def _capture(**kwargs: Any) -> dict:
        captured_kwargs.append(kwargs)
        return {"Deleted": [{"Key": o["Key"]} for o in kwargs["Delete"]["Objects"]]}

    monkeypatch.setattr(handler._s3, "delete_objects", _capture)

    handler._delete_page_cache(42, "demo-slug")

    assert len(captured_kwargs) == 1
    keys = [o["Key"] for o in captured_kwargs[0]["Delete"]["Objects"]]
    assert keys == [
        f"{_CACHE_KEY_PREFIX}inner-a/games/42/demo-slug.cache",
        f"{_CACHE_KEY_PREFIX}inner-a/games/42/demo-slug.cache.meta",
        f"{_CACHE_KEY_PREFIX}inner-b/games/42/demo-slug.cache",
        f"{_CACHE_KEY_PREFIX}inner-b/games/42/demo-slug.cache.meta",
    ]


@mock_aws
def test_module_load_raises_when_no_inner_build_ids_found() -> None:
    """Empty cache/{OUTER}/ prefix is a broken deploy — must crash loudly."""
    import sys

    ssm = boto3.client("ssm", region_name="us-east-1")
    ssm.put_parameter(Name=_REVALIDATE_TOKEN_PARAM, Value=_TOKEN, Type="String", Overwrite=True)
    ssm.put_parameter(
        Name=_DISTRIBUTION_ID_PARAM, Value=_DISTRIBUTION_ID, Type="String", Overwrite=True
    )
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=_FRONTEND_BUCKET)
    # Note: deliberately no inner-id placeholder object.
    sys.modules.pop("lambda_functions.revalidate_frontend.handler", None)
    with pytest.raises(RuntimeError, match="No inner build IDs found"):
        import lambda_functions.revalidate_frontend.handler  # noqa: F401
