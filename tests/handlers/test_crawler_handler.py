"""End-to-end handler tests for the crawler Lambda (control plane + dispatcher).

These tests inject mock CrawlService + CatalogService directly into the
handler's module-level cache, then fire events and assert on service calls.
"""

import json
from typing import Any
from unittest.mock import MagicMock

import boto3
import pytest
from lambda_functions.crawler.events import (
    MetadataSpokeRequest,
    ReviewSpokeRequest,
    TagsSpokeRequest,
    parse_spoke_request,
)
from moto import mock_aws

# ── SSM seed — required before handler import (module-level get_parameter) ───

_SSM_PARAMS = {
    "/steampulse/test/compute/sfn-arn": "arn:aws:states:us-east-1:123456789012:stateMachine:crawl",
    "/steampulse/test/messaging/review-crawl-queue-url": "https://sqs.us-east-1.amazonaws.com/123456789012/review-crawl",
    "/steampulse/test/messaging/app-crawl-queue-url": "https://sqs.us-east-1.amazonaws.com/123456789012/app-crawl",
    "/steampulse/test/messaging/game-events-topic-arn": "arn:aws:sns:us-east-1:123456789012:game-events",
    "/steampulse/test/messaging/content-events-topic-arn": "arn:aws:sns:us-east-1:123456789012:content-events",
    "/steampulse/test/messaging/system-events-topic-arn": "arn:aws:sns:us-east-1:123456789012:system-events",
    "/steampulse/test/data/assets-bucket-name": "test-assets-bucket",
}


def _seed_ssm() -> None:
    """Create SSM parameters and secrets in moto so handler's module-level init works."""
    ssm = boto3.client("ssm", region_name="us-east-1")
    for name, value in _SSM_PARAMS.items():
        ssm.put_parameter(Name=name, Value=value, Type="String", Overwrite=True)
    # Seed Steam API key secret (Secrets Manager)
    sm = boto3.client("secretsmanager", region_name="us-east-1")
    try:
        sm.create_secret(Name="steampulse/test/steam-api-key", SecretString="test-steam-key")
    except sm.exceptions.ResourceExistsException:
        pass


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_crawl_service(crawl_app_result: bool = True, reviews_upserted: int = 4) -> MagicMock:
    svc = MagicMock()
    svc.crawl_app = MagicMock(return_value=crawl_app_result)
    svc.crawl_reviews = MagicMock(return_value=reviews_upserted)
    return svc


def _make_catalog_service(refresh_result: dict | None = None) -> MagicMock:
    svc = MagicMock()
    svc.refresh = MagicMock(
        return_value=refresh_result
        or {
            "apps_fetched": 100,
            "new_rows": 5,
            "enqueued": 5,
        }
    )
    return svc


def _inject_services(mock_crawl: MagicMock, mock_catalog: MagicMock) -> None:
    _seed_ssm()
    import lambda_functions.crawler.handler as hm

    hm._crawl_service = mock_crawl
    hm._catalog_service = mock_catalog


def _eventbridge_event() -> dict:
    return {"source": "aws.events", "detail-type": "Scheduled Event"}


# ── Tests ────────────────────────────────────────────────────────────────────


@mock_aws
def test_handler_catalog_refresh(lambda_context: Any) -> None:
    """EventBridge event → CatalogService.refresh() called, result returned."""
    mock_crawl = _make_crawl_service()
    mock_catalog = _make_catalog_service({"apps_fetched": 170000, "new_rows": 50, "enqueued": 50})
    _inject_services(mock_crawl, mock_catalog)

    from lambda_functions.crawler.handler import handler

    result = handler(_eventbridge_event(), lambda_context)

    mock_catalog.refresh.assert_called_once()
    assert result["apps_fetched"] == 170000
    assert result["new_rows"] == 50


@mock_aws
def test_handler_direct_crawl_apps(lambda_context: Any) -> None:
    """Direct action=crawl_apps invocation → CrawlService.crawl_app called."""
    mock_crawl = _make_crawl_service(crawl_app_result=True)
    mock_catalog = _make_catalog_service()
    _inject_services(mock_crawl, mock_catalog)

    from lambda_functions.crawler.handler import handler

    result = handler({"action": "crawl_apps", "appid": 440}, lambda_context)

    mock_crawl.crawl_app.assert_called_once_with(440)
    assert result["appid"] == 440
    assert result["success"] is True


@mock_aws
def test_handler_dispatches_sqs_to_spoke(lambda_context: Any) -> None:
    """SQS app-crawl event → dispatches to a spoke SQS queue."""
    mock_crawl = _make_crawl_service()
    mock_catalog = _make_catalog_service()
    _inject_services(mock_crawl, mock_catalog)

    import lambda_functions.crawler.handler as hm

    # Inject mock spoke targets so dispatch has targets
    mock_sqs_client = MagicMock()
    hm._spoke_sqs_targets = [
        ("https://sqs.us-east-1.amazonaws.com/123/test-spoke-queue", mock_sqs_client)
    ]

    from lambda_functions.crawler.handler import handler

    event = {
        "Records": [
            {
                "messageId": "m1",
                "body": json.dumps({"appid": 440, "task": "metadata"}),
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:steampulse-staging-app-crawl",
            }
        ],
    }
    handler(event, lambda_context)

    mock_sqs_client.send_message.assert_called_once()
    call_kwargs = mock_sqs_client.send_message.call_args[1]
    assert call_kwargs["QueueUrl"] == "https://sqs.us-east-1.amazonaws.com/123/test-spoke-queue"
    payload = MetadataSpokeRequest.model_validate_json(call_kwargs["MessageBody"])
    assert payload.appid == 440
    assert payload.task == "metadata"


@mock_aws
def test_handler_dispatches_review_crawl_to_spoke(lambda_context: Any) -> None:
    """SQS review-crawl event → dispatches to spoke queue with task=reviews."""
    mock_crawl = _make_crawl_service()
    mock_catalog = _make_catalog_service()
    _inject_services(mock_crawl, mock_catalog)

    import lambda_functions.crawler.handler as hm

    mock_sqs_client = MagicMock()
    hm._spoke_sqs_targets = [
        ("https://sqs.us-east-1.amazonaws.com/123/test-spoke-queue", mock_sqs_client)
    ]

    from lambda_functions.crawler.handler import handler

    event = {
        "Records": [
            {
                "messageId": "m2",
                "body": json.dumps({"appid": 730, "task": "reviews"}),
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:steampulse-staging-review-crawl",
            }
        ],
    }
    handler(event, lambda_context)

    mock_sqs_client.send_message.assert_called_once()
    call_kwargs = mock_sqs_client.send_message.call_args[1]
    payload = ReviewSpokeRequest.model_validate_json(call_kwargs["MessageBody"])
    assert payload.appid == 730
    assert payload.task == "reviews"
    assert payload.cursor == "*"
    assert payload.started_at is not None  # set on fresh start


@mock_aws
def test_handler_dispatches_sns_wrapped_body(lambda_context: Any) -> None:
    """SQS record with SNS envelope → _extract_payload unwraps, dispatch succeeds."""
    mock_crawl = _make_crawl_service()
    mock_catalog = _make_catalog_service()
    _inject_services(mock_crawl, mock_catalog)

    import lambda_functions.crawler.handler as hm

    mock_sqs_client = MagicMock()
    hm._spoke_sqs_targets = [
        ("https://sqs.us-east-1.amazonaws.com/123/test-spoke-queue", mock_sqs_client)
    ]

    from lambda_functions.crawler.handler import handler

    sns_envelope = {
        "Type": "Notification",
        "MessageId": "abc-123",
        "TopicArn": "arn:aws:sns:us-east-1:123456789012:game-events",
        "Message": json.dumps({"appid": 570, "task": "metadata"}),
        "Timestamp": "2026-03-20T00:00:00.000Z",
    }
    event = {
        "Records": [
            {
                "messageId": "m3",
                "body": json.dumps(sns_envelope),
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:steampulse-staging-app-crawl",
            }
        ],
    }
    handler(event, lambda_context)

    mock_sqs_client.send_message.assert_called_once()
    call_kwargs = mock_sqs_client.send_message.call_args[1]
    payload = MetadataSpokeRequest.model_validate_json(call_kwargs["MessageBody"])
    assert payload.appid == 570
    assert payload.task == "metadata"


@mock_aws
def test_review_dispatch_normalizes_null_cursor_to_fresh_start(lambda_context: Any) -> None:
    """cursor: null in message body → treated as fresh start (cursor becomes '*')."""
    mock_crawl = _make_crawl_service()
    mock_catalog = _make_catalog_service()
    _inject_services(mock_crawl, mock_catalog)

    import lambda_functions.crawler.handler as hm

    mock_sqs_client = MagicMock()
    hm._spoke_sqs_targets = [
        ("https://sqs.us-east-1.amazonaws.com/123/test-spoke-queue", mock_sqs_client)
    ]

    from lambda_functions.crawler.handler import handler

    event = {
        "Records": [
            {
                "messageId": "m4",
                "body": json.dumps(
                    {"appid": 730, "task": "reviews", "cursor": None, "target": 5000}
                ),
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:steampulse-staging-review-crawl",
            }
        ],
    }
    handler(event, lambda_context)

    call_kwargs = mock_sqs_client.send_message.call_args[1]
    payload = ReviewSpokeRequest.model_validate_json(call_kwargs["MessageBody"])
    assert payload.cursor == "*"
    assert payload.target == 5000


@mock_aws
def test_review_dispatch_defaults_target_when_missing(lambda_context: Any) -> None:
    """Continuing message without target → falls back to REVIEW_LIMIT (never unbounded)."""
    mock_crawl = _make_crawl_service()
    mock_catalog = _make_catalog_service()
    _inject_services(mock_crawl, mock_catalog)

    import lambda_functions.crawler.handler as hm

    mock_sqs_client = MagicMock()
    hm._spoke_sqs_targets = [
        ("https://sqs.us-east-1.amazonaws.com/123/test-spoke-queue", mock_sqs_client)
    ]

    from lambda_functions.crawler.handler import handler

    # Continuing message (has cursor) but no target field
    event = {
        "Records": [
            {
                "messageId": "m5",
                "body": json.dumps({"appid": 730, "task": "reviews", "cursor": "AoJ4sometoken"}),
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:steampulse-staging-review-crawl",
            }
        ],
    }
    handler(event, lambda_context)

    call_kwargs = mock_sqs_client.send_message.call_args[1]
    payload = ReviewSpokeRequest.model_validate_json(call_kwargs["MessageBody"])
    assert payload.cursor == "AoJ4sometoken"
    assert payload.target == hm._crawler_config.REVIEW_LIMIT


@mock_aws
def test_review_dispatch_skips_zero_target(lambda_context: Any) -> None:
    """Message with target=0 → budget exhausted, no message sent to spoke."""
    mock_crawl = _make_crawl_service()
    mock_catalog = _make_catalog_service()
    _inject_services(mock_crawl, mock_catalog)

    import lambda_functions.crawler.handler as hm

    mock_sqs_client = MagicMock()
    hm._spoke_sqs_targets = [
        ("https://sqs.us-east-1.amazonaws.com/123/test-spoke-queue", mock_sqs_client)
    ]

    from lambda_functions.crawler.handler import handler

    event = {
        "Records": [
            {
                "messageId": "m6",
                "body": json.dumps(
                    {"appid": 730, "task": "reviews", "cursor": "AoJ4sometoken", "target": 0}
                ),
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:steampulse-staging-review-crawl",
            }
        ],
    }
    handler(event, lambda_context)

    mock_sqs_client.send_message.assert_not_called()


@mock_aws
def test_handler_dispatches_tags_to_spoke(lambda_context: Any) -> None:
    """SQS message with task=tags → dispatches TagsSpokeRequest to spoke."""
    mock_crawl = _make_crawl_service()
    mock_catalog = _make_catalog_service()
    _inject_services(mock_crawl, mock_catalog)

    import lambda_functions.crawler.handler as hm

    mock_sqs_client = MagicMock()
    hm._spoke_sqs_targets = [
        ("https://sqs.us-east-1.amazonaws.com/123/test-spoke-queue", mock_sqs_client)
    ]

    from lambda_functions.crawler.handler import handler

    event = {
        "Records": [
            {
                "messageId": "m7",
                "body": json.dumps({"appid": 440, "task": "tags"}),
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:steampulse-staging-app-crawl",
            }
        ],
    }
    handler(event, lambda_context)

    mock_sqs_client.send_message.assert_called_once()
    call_kwargs = mock_sqs_client.send_message.call_args[1]
    payload = TagsSpokeRequest.model_validate_json(call_kwargs["MessageBody"])
    assert payload.appid == 440
    assert payload.task == "tags"


@mock_aws
def test_handler_infers_task_from_arn_when_missing(lambda_context: Any) -> None:
    """SNS-routed domain event without task field → infers metadata from app-crawl ARN."""
    mock_crawl = _make_crawl_service()
    mock_catalog = _make_catalog_service()
    _inject_services(mock_crawl, mock_catalog)

    import lambda_functions.crawler.handler as hm

    mock_sqs_client = MagicMock()
    hm._spoke_sqs_targets = [
        ("https://sqs.us-east-1.amazonaws.com/123/test-spoke-queue", mock_sqs_client)
    ]

    from lambda_functions.crawler.handler import handler

    # SNS-wrapped game-discovered event — no "task" field
    sns_envelope = {
        "Type": "Notification",
        "MessageId": "abc-456",
        "TopicArn": "arn:aws:sns:us-east-1:123456789012:game-events",
        "Message": json.dumps({"event_type": "game-discovered", "appid": 999}),
        "Timestamp": "2026-03-20T00:00:00.000Z",
    }
    event = {
        "Records": [
            {
                "messageId": "m8",
                "body": json.dumps(sns_envelope),
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:steampulse-staging-app-crawl",
            }
        ],
    }
    handler(event, lambda_context)

    call_kwargs = mock_sqs_client.send_message.call_args[1]
    payload = MetadataSpokeRequest.model_validate_json(call_kwargs["MessageBody"])
    assert payload.appid == 999
    assert payload.task == "metadata"


@mock_aws
def test_handler_infers_reviews_from_review_crawl_arn(lambda_context: Any) -> None:
    """SNS-routed event on review-crawl queue without task field → infers reviews."""
    mock_crawl = _make_crawl_service()
    mock_catalog = _make_catalog_service()
    _inject_services(mock_crawl, mock_catalog)

    import lambda_functions.crawler.handler as hm

    mock_sqs_client = MagicMock()
    hm._spoke_sqs_targets = [
        ("https://sqs.us-east-1.amazonaws.com/123/test-spoke-queue", mock_sqs_client)
    ]

    from lambda_functions.crawler.handler import handler

    # SNS-wrapped game-metadata-ready event — no "task" field
    sns_envelope = {
        "Type": "Notification",
        "MessageId": "abc-789",
        "TopicArn": "arn:aws:sns:us-east-1:123456789012:game-events",
        "Message": json.dumps(
            {
                "event_type": "game-metadata-ready",
                "appid": 888,
                "review_count": 500,
                "is_eligible": True,
            }
        ),
        "Timestamp": "2026-03-20T00:00:00.000Z",
    }
    event = {
        "Records": [
            {
                "messageId": "m9",
                "body": json.dumps(sns_envelope),
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:steampulse-staging-review-crawl",
            }
        ],
    }
    handler(event, lambda_context)

    call_kwargs = mock_sqs_client.send_message.call_args[1]
    payload = ReviewSpokeRequest.model_validate_json(call_kwargs["MessageBody"])
    assert payload.appid == 888
    assert payload.task == "reviews"


# ── parse_spoke_request unit tests ───────────────────────────────────────────


def _sqs_record(
    body: dict, arn: str = "arn:aws:sqs:us-east-1:123:steampulse-staging-app-crawl"
) -> dict:
    return {"messageId": "test", "body": json.dumps(body), "eventSourceARN": arn}


def _sns_record(inner: dict, arn: str) -> dict:
    envelope = {
        "Type": "Notification",
        "MessageId": "sns-test",
        "TopicArn": "arn:aws:sns:us-east-1:123:game-events",
        "Message": json.dumps(inner),
        "Timestamp": "2026-01-01T00:00:00.000Z",
    }
    return {"messageId": "test", "body": json.dumps(envelope), "eventSourceARN": arn}


def test_parse_explicit_metadata_task() -> None:
    req = parse_spoke_request(_sqs_record({"appid": 440, "task": "metadata"}), review_limit=5000)
    assert req is not None
    assert req.appid == 440
    assert req.task == "metadata"


def test_parse_explicit_tags_task() -> None:
    req = parse_spoke_request(_sqs_record({"appid": 440, "task": "tags"}), review_limit=5000)
    assert req is not None
    assert req.appid == 440
    assert req.task == "tags"


def test_parse_explicit_reviews_with_target() -> None:
    req = parse_spoke_request(
        _sqs_record({"appid": 730, "task": "reviews", "cursor": "abc", "target": 3000}),
        review_limit=5000,
    )
    assert req is not None
    assert req.task == "reviews"
    assert req.cursor == "abc"
    assert req.target == 3000


def test_parse_reviews_defaults_target_to_limit() -> None:
    req = parse_spoke_request(
        _sqs_record({"appid": 730, "task": "reviews"}),
        review_limit=5000,
    )
    assert req is not None
    assert req.target == 5000


def test_parse_reviews_zero_target_returns_none() -> None:
    req = parse_spoke_request(
        _sqs_record({"appid": 730, "task": "reviews", "target": 0}),
        review_limit=5000,
    )
    assert req is None


def test_parse_sns_app_crawl_infers_metadata() -> None:
    arn = "arn:aws:sqs:us-east-1:123:steampulse-staging-app-crawl"
    req = parse_spoke_request(
        _sns_record({"event_type": "game-discovered", "appid": 999}, arn=arn),
        review_limit=5000,
    )
    assert req is not None
    assert req.task == "metadata"
    assert req.appid == 999


def test_parse_sns_review_crawl_infers_reviews() -> None:
    arn = "arn:aws:sqs:us-east-1:123:steampulse-staging-review-crawl"
    req = parse_spoke_request(
        _sns_record(
            {
                "event_type": "game-metadata-ready",
                "appid": 888,
                "review_count": 500,
                "is_eligible": True,
            },
            arn=arn,
        ),
        review_limit=5000,
    )
    assert req is not None
    assert req.task == "reviews"


def test_parse_unknown_arn_no_task_raises() -> None:
    with pytest.raises(ValueError, match="Cannot determine task"):
        parse_spoke_request(
            _sqs_record({"appid": 440}, arn="arn:aws:sqs:us-east-1:123:unknown-queue"),
            review_limit=5000,
        )


def test_parse_unknown_task_raises() -> None:
    with pytest.raises(ValueError, match="Unknown task"):
        parse_spoke_request(
            _sqs_record({"appid": 440, "task": "bogus"}),
            review_limit=5000,
        )
