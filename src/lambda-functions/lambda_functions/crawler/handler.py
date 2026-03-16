"""Lambda handler — unified crawler dispatcher.

Event types handled:
  1. EventBridge (scheduled)  — source == "aws.events" → CatalogService.refresh()
  2. Direct boto3 invocation  — "action" key present   → dispatch via Pydantic model
  3. SQS batch               — "Records" key present   → CrawlService methods
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response,
)
from aws_lambda_powertools.utilities.typing import LambdaContext
from pydantic import TypeAdapter, ValidationError

from ._db import get_conn
from .events import (
    CatalogRefreshRequest,
    CrawlAppsRequest,
    CrawlReviewsRequest,
    DirectRequest,
)

logger = Logger(service="crawler")
tracer = Tracer(service="crawler")
metrics = Metrics(namespace="SteamPulse", service="crawler")

app_crawl_processor = BatchProcessor(event_type=EventType.SQS)
review_crawl_processor = BatchProcessor(event_type=EventType.SQS)

_direct_adapter = TypeAdapter(DirectRequest)

# ── Module-level service singletons ─────────────────────────────────────────
# Built lazily so tests can inject mocks before first use.

_crawl_service: Any = None
_catalog_service: Any = None


def _get_services() -> tuple[Any, Any]:
    """Build (and cache) CrawlService + CatalogService on first call."""
    global _crawl_service, _catalog_service
    if _crawl_service is not None and _catalog_service is not None:
        return _crawl_service, _catalog_service

    import boto3
    import httpx
    from library_layer.repositories.catalog_repo import CatalogRepository
    from library_layer.repositories.game_repo import GameRepository
    from library_layer.repositories.review_repo import ReviewRepository
    from library_layer.repositories.tag_repo import TagRepository
    from library_layer.services.catalog_service import CatalogService
    from library_layer.services.crawl_service import CrawlService
    from library_layer.steam_source import DirectSteamSource

    conn = get_conn()
    sqs = boto3.client("sqs")
    sfn_arn = os.getenv("SFN_ARN") or os.getenv("STEP_FUNCTIONS_ARN")
    sfn = boto3.client("stepfunctions") if sfn_arn else None

    game_repo = GameRepository(conn)
    review_repo = ReviewRepository(conn)
    catalog_repo = CatalogRepository(conn)
    tag_repo = TagRepository(conn)

    http_async = httpx.AsyncClient(timeout=60.0)
    steam = DirectSteamSource(http_async)

    _crawl_service = CrawlService(
        game_repo=game_repo,
        review_repo=review_repo,
        catalog_repo=catalog_repo,
        tag_repo=tag_repo,
        steam=steam,
        sqs_client=sqs,
        review_queue_url=os.getenv("REVIEW_CRAWL_QUEUE_URL", ""),
        sfn_arn=sfn_arn,
        sfn_client=sfn,
    )

    http_sync = httpx.Client(timeout=30.0)
    _catalog_service = CatalogService(
        catalog_repo=catalog_repo,
        http_client=http_sync,
        sqs_client=sqs,
        app_crawl_queue_url=os.getenv("APP_CRAWL_QUEUE_URL", ""),
    )

    return _crawl_service, _catalog_service


# ── SQS record handlers ──────────────────────────────────────────────────────

def _app_crawl_record(record: dict) -> None:
    crawl_svc, _ = _get_services()
    body = json.loads(record["body"])
    appid = int(body["appid"])
    result = asyncio.run(crawl_svc.crawl_app(appid))
    if result:
        metrics.add_metric(name="AppsCrawled", unit=MetricUnit.Count, value=1)


def _review_crawl_record(record: dict) -> None:
    crawl_svc, _ = _get_services()
    body = json.loads(record["body"])
    appid = int(body["appid"])
    count = asyncio.run(crawl_svc.crawl_reviews(appid))
    metrics.add_metric(name="ReviewsUpserted", unit=MetricUnit.Count, value=count)


# ── Main dispatcher ──────────────────────────────────────────────────────────

@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    crawl_svc, catalog_svc = _get_services()

    # 1. EventBridge scheduled trigger
    if event.get("source") == "aws.events":
        logger.info("EventBridge trigger — running catalog refresh")
        result = catalog_svc.refresh()
        metrics.add_metric(name="CatalogRefreshRun", unit=MetricUnit.Count, value=1)
        return result

    # 2. Direct invocation (from web Lambda or manual)
    if "action" in event:
        try:
            req = _direct_adapter.validate_python(event)
        except ValidationError as exc:
            logger.error("Invalid direct invocation payload: %s", exc)
            raise
        logger.info("Direct invocation: action=%s", event["action"])
        match req:
            case CrawlAppsRequest():
                ok = asyncio.run(crawl_svc.crawl_app(req.appid))
                return {"appid": req.appid, "success": ok}
            case CrawlReviewsRequest():
                n = asyncio.run(crawl_svc.crawl_reviews(req.appid, max_reviews=req.max_reviews))
                return {"appid": req.appid, "reviews_upserted": n}
            case CatalogRefreshRequest():
                return catalog_svc.refresh()

    # 3. SQS batch
    if "Records" in event:
        source_arn = event["Records"][0].get("eventSourceARN", "")
        if "app-crawl" in source_arn:
            return process_partial_response(
                event=event,
                record_handler=_app_crawl_record,
                processor=app_crawl_processor,
                context=context,
            )
        if "review-crawl" in source_arn:
            return process_partial_response(
                event=event,
                record_handler=_review_crawl_record,
                processor=review_crawl_processor,
                context=context,
            )

    raise ValueError(f"Unrecognised event shape: {list(event.keys())}")
