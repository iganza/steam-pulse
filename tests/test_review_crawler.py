"""Tests for review_crawler via Lambda handler (updated for service layer)."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from moto import mock_aws


def make_sqs_event(appids: list[int]) -> dict:
    return {
        "Records": [
            {
                "messageId": f"msg-{appid}",
                "body": json.dumps({"appid": appid}),
                "receiptHandle": "r",
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:staging-steampulse-review-crawl",
            }
            for appid in appids
        ]
    }


def _make_mock_crawl_service(reviews_upserted: int = 4) -> MagicMock:
    svc = MagicMock()
    svc.crawl_app = AsyncMock(return_value=True)
    svc.crawl_reviews = AsyncMock(return_value=reviews_upserted)
    return svc


def _make_mock_catalog_service() -> MagicMock:
    svc = MagicMock()
    svc.refresh = MagicMock(return_value={"apps_fetched": 0, "new_rows": 0, "enqueued": 0})
    return svc


@mock_aws
def test_handler_fetches_and_stores_reviews(
    lambda_context: Any,
) -> None:
    """Handler dispatches to CrawlService.crawl_reviews for SQS review-crawl events."""
    mock_crawl = _make_mock_crawl_service(reviews_upserted=4)
    mock_catalog = _make_mock_catalog_service()

    import lambda_functions.crawler.handler as handler_module
    handler_module._crawl_service = mock_crawl
    handler_module._catalog_service = mock_catalog

    from lambda_functions.crawler.handler import handler
    result = handler(make_sqs_event([440]), lambda_context)

    assert result["batchItemFailures"] == []
    mock_crawl.crawl_reviews.assert_called_once_with(440)


@mock_aws
def test_handler_starts_sfn_after_reviews(
    lambda_context: Any,
) -> None:
    """crawl_reviews is responsible for triggering SFN — handler just calls the service."""
    mock_crawl = _make_mock_crawl_service(reviews_upserted=4)
    mock_catalog = _make_mock_catalog_service()

    import lambda_functions.crawler.handler as handler_module
    handler_module._crawl_service = mock_crawl
    handler_module._catalog_service = mock_catalog

    from lambda_functions.crawler.handler import handler
    handler(make_sqs_event([440]), lambda_context)

    mock_crawl.crawl_reviews.assert_called_once_with(440)


@mock_aws
def test_handler_tolerates_empty_reviews(
    lambda_context: Any,
) -> None:
    """When reviews API returns 0 reviews, handler completes without error."""
    mock_crawl = _make_mock_crawl_service(reviews_upserted=0)
    mock_catalog = _make_mock_catalog_service()

    import lambda_functions.crawler.handler as handler_module
    handler_module._crawl_service = mock_crawl
    handler_module._catalog_service = mock_catalog

    from lambda_functions.crawler.handler import handler
    result = handler(make_sqs_event([440]), lambda_context)

    assert result["batchItemFailures"] == []
