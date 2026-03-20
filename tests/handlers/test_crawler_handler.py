"""End-to-end handler tests for the crawler Lambda (control plane only).

These tests inject mock CrawlService + CatalogService directly into the
handler's module-level cache, then fire events and assert on service calls.

SQS event processing has moved to spoke_handler.py — tested separately.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import boto3
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
    svc.crawl_app = AsyncMock(return_value=crawl_app_result)
    svc.crawl_reviews = AsyncMock(return_value=reviews_upserted)
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
def test_handler_rejects_sqs_events(lambda_context: Any) -> None:
    """Handler no longer processes SQS events — raises ValueError."""
    mock_crawl = _make_crawl_service()
    mock_catalog = _make_catalog_service()
    _inject_services(mock_crawl, mock_catalog)

    import pytest
    from lambda_functions.crawler.handler import handler
    with pytest.raises(ValueError, match="Unrecognised event shape"):
        handler({"Records": [{"messageId": "m1", "body": '{"appid": 440}'}]}, lambda_context)
