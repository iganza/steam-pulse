"""End-to-end handler tests for the crawler Lambda.

These tests inject mock CrawlService + CatalogService directly into the
handler's module-level cache, then fire events and assert on service calls.
"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from moto import mock_aws

# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_crawl_service(crawl_app_result: bool = True, reviews_upserted: int = 4) -> MagicMock:
    svc = MagicMock()
    svc.crawl_app = AsyncMock(return_value=crawl_app_result)
    svc.crawl_reviews = AsyncMock(return_value=reviews_upserted)
    return svc


def _make_catalog_service(refresh_result: dict | None = None) -> MagicMock:
    svc = MagicMock()
    svc.refresh = MagicMock(return_value=refresh_result or {
        "apps_fetched": 100,
        "new_rows": 5,
        "enqueued": 5,
    })
    return svc


def _inject_services(mock_crawl: MagicMock, mock_catalog: MagicMock) -> None:
    import lambda_functions.crawler.handler as hm
    hm._crawl_service = mock_crawl
    hm._catalog_service = mock_catalog


def _sqs_app_crawl_event(appids: list[int]) -> dict:
    return {
        "Records": [
            {
                "messageId": f"msg-{appid}",
                "body": json.dumps({"appid": appid}),
                "receiptHandle": "r",
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:app-crawl-queue",
            }
            for appid in appids
        ]
    }


def _sqs_review_crawl_event(appids: list[int]) -> dict:
    return {
        "Records": [
            {
                "messageId": f"msg-r-{appid}",
                "body": json.dumps({"appid": appid}),
                "receiptHandle": "r",
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:review-crawl-queue",
            }
            for appid in appids
        ]
    }


def _eventbridge_event() -> dict:
    return {"source": "aws.events", "detail-type": "Scheduled Event"}


# ── Tests ────────────────────────────────────────────────────────────────────

@mock_aws
def test_handler_sqs_app_crawl(lambda_context: Any) -> None:
    """SQS app-crawl event → CrawlService.crawl_app called with correct appid."""
    mock_crawl = _make_crawl_service(crawl_app_result=True)
    mock_catalog = _make_catalog_service()
    _inject_services(mock_crawl, mock_catalog)

    from lambda_functions.crawler.handler import handler
    result = handler(_sqs_app_crawl_event([440]), lambda_context)

    assert result["batchItemFailures"] == []
    mock_crawl.crawl_app.assert_called_once_with(440)


@mock_aws
def test_handler_sqs_review_crawl(lambda_context: Any) -> None:
    """SQS review-crawl event → CrawlService.crawl_reviews called with correct appid."""
    mock_crawl = _make_crawl_service(reviews_upserted=4)
    mock_catalog = _make_catalog_service()
    _inject_services(mock_crawl, mock_catalog)

    from lambda_functions.crawler.handler import handler
    result = handler(_sqs_review_crawl_event([440]), lambda_context)

    assert result["batchItemFailures"] == []
    mock_crawl.crawl_reviews.assert_called_once_with(440)


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
def test_handler_batch_processes_multiple(lambda_context: Any) -> None:
    """SQS batch of 3 appids → crawl_app called 3 times, all succeed."""
    mock_crawl = _make_crawl_service(crawl_app_result=True)
    mock_catalog = _make_catalog_service()
    _inject_services(mock_crawl, mock_catalog)

    from lambda_functions.crawler.handler import handler
    result = handler(_sqs_app_crawl_event([440, 441, 442]), lambda_context)

    assert result["batchItemFailures"] == []
    assert mock_crawl.crawl_app.call_count == 3
    called_appids = [call.args[0] for call in mock_crawl.crawl_app.call_args_list]
    assert set(called_appids) == {440, 441, 442}
