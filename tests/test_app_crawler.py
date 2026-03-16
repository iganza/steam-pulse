"""Tests for app_crawler via Lambda handler (updated for service layer)."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from moto import mock_aws
from pytest_httpx import HTTPXMock

REVIEW_SUMMARY = {
    "success": 1,
    "query_summary": {
        "total_positive": 182000,
        "total_negative": 6000,
        "total_reviews": 188000,
        "review_score": 9,
        "review_score_desc": "Overwhelmingly Positive",
    },
    "reviews": [],
}


def make_sqs_event(appids: list[int]) -> dict:
    return {
        "Records": [
            {
                "messageId": f"msg-{appid}",
                "body": json.dumps({"appid": appid}),
                "receiptHandle": "receipt",
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:staging-steampulse-app-crawl",
            }
            for appid in appids
        ]
    }


def _make_mock_crawl_service(crawl_app_result: bool = True) -> MagicMock:
    svc = MagicMock()
    svc.crawl_app = AsyncMock(return_value=crawl_app_result)
    svc.crawl_reviews = AsyncMock(return_value=0)
    return svc


def _make_mock_catalog_service() -> MagicMock:
    svc = MagicMock()
    svc.refresh = MagicMock(return_value={"apps_fetched": 0, "new_rows": 0, "enqueued": 0})
    return svc


@mock_aws
def test_handler_processes_single_appid(
    httpx_mock: HTTPXMock,
    steam_appdetails_440: dict,
    lambda_context: Any,
) -> None:
    """Handler dispatches to CrawlService.crawl_app for SQS app-crawl events."""
    mock_crawl = _make_mock_crawl_service(crawl_app_result=True)
    mock_catalog = _make_mock_catalog_service()

    import lambda_functions.crawler.handler as handler_module
    # Reset module-level cache so _get_services() returns our mocks
    handler_module._crawl_service = mock_crawl
    handler_module._catalog_service = mock_catalog

    from lambda_functions.crawler.handler import handler
    result = handler(make_sqs_event([440]), lambda_context)

    assert result["batchItemFailures"] == []
    mock_crawl.crawl_app.assert_called_once_with(440)


@mock_aws
def test_handler_skips_on_steam_api_failure(
    lambda_context: Any,
) -> None:
    """When crawl_app returns False (Steam error), handler completes without batch failure."""
    mock_crawl = _make_mock_crawl_service(crawl_app_result=False)
    mock_catalog = _make_mock_catalog_service()

    import lambda_functions.crawler.handler as handler_module
    handler_module._crawl_service = mock_crawl
    handler_module._catalog_service = mock_catalog

    from lambda_functions.crawler.handler import handler
    result = handler(make_sqs_event([440]), lambda_context)

    assert result["batchItemFailures"] == []
    mock_crawl.crawl_app.assert_called_once_with(440)


@mock_aws
def test_handler_processes_batch(
    lambda_context: Any,
) -> None:
    """Batch of 3 appids: crawl_app called 3 times."""
    mock_crawl = _make_mock_crawl_service(crawl_app_result=True)
    mock_catalog = _make_mock_catalog_service()

    import lambda_functions.crawler.handler as handler_module
    handler_module._crawl_service = mock_crawl
    handler_module._catalog_service = mock_catalog

    from lambda_functions.crawler.handler import handler
    result = handler(make_sqs_event([440, 441, 442]), lambda_context)

    assert result["batchItemFailures"] == []
    assert mock_crawl.crawl_app.call_count == 3
