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

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response,
)
from aws_lambda_powertools.utilities.typing import LambdaContext
from pydantic import TypeAdapter, ValidationError

from library_layer.config import SteamPulseConfig
from library_layer.utils.db import get_conn
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
# Eagerly built at cold start — fails loud if deps are missing.
# Tests inject mocks via module attribute assignment before calling handler.

import boto3  # type: ignore[import-untyped]
import httpx

from library_layer.repositories.catalog_repo import CatalogRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.services.catalog_service import CatalogService
from library_layer.services.crawl_service import CrawlService
from library_layer.steam_source import DirectSteamSource

_conn = get_conn()
_sqs = boto3.client("sqs")
_sns = boto3.client("sns")
_sfn_arn = os.getenv("SFN_ARN") or os.getenv("STEP_FUNCTIONS_ARN")
_sfn = boto3.client("stepfunctions") if _sfn_arn else None
_crawler_config = SteamPulseConfig()

_crawl_service = CrawlService(
    game_repo=GameRepository(_conn),
    review_repo=ReviewRepository(_conn),
    catalog_repo=CatalogRepository(_conn),
    tag_repo=TagRepository(_conn),
    steam=DirectSteamSource(httpx.AsyncClient(timeout=60.0)),
    sqs_client=_sqs,
    review_queue_url=os.getenv("REVIEW_CRAWL_QUEUE_URL", ""),
    sfn_arn=_sfn_arn,
    sfn_client=_sfn,
    sns_client=_sns,
    config=_crawler_config,
)
_catalog_service = CatalogService(
    catalog_repo=CatalogRepository(_conn),
    http_client=httpx.Client(timeout=30.0),
    sqs_client=_sqs,
    app_crawl_queue_url=os.getenv("APP_CRAWL_QUEUE_URL", ""),
    sns_client=_sns,
    config=_crawler_config,
)


# ── SNS envelope unwrapping ───────────────────────────────────────────────────


def _extract_payload(record_body: str) -> dict:
    """Unwrap SNS envelope if present, otherwise return plain SQS body."""
    body = json.loads(record_body)
    if "Type" in body and body["Type"] == "Notification":
        return json.loads(body["Message"])
    return body


# ── SQS record handlers ──────────────────────────────────────────────────────


def _app_crawl_record(record: dict) -> None:
    body = _extract_payload(record["body"])
    appid = int(body["appid"])
    result = asyncio.run(_crawl_service.crawl_app(appid))
    if result:
        metrics.add_metric(name="AppsCrawled", unit=MetricUnit.Count, value=1)


def _review_crawl_record(record: dict) -> None:
    body = _extract_payload(record["body"])
    appid = int(body["appid"])
    count = asyncio.run(_crawl_service.crawl_reviews(appid))
    metrics.add_metric(name="ReviewsUpserted", unit=MetricUnit.Count, value=count)


# ── Main dispatcher ──────────────────────────────────────────────────────────


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    # 1. EventBridge scheduled trigger
    if event.get("source") == "aws.events":
        logger.info("EventBridge trigger — running catalog refresh")
        result = _catalog_service.refresh()
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
                ok = asyncio.run(_crawl_service.crawl_app(req.appid))
                return {"appid": req.appid, "success": ok}
            case CrawlReviewsRequest():
                n = asyncio.run(
                    _crawl_service.crawl_reviews(req.appid, max_reviews=req.max_reviews)
                )
                return {"appid": req.appid, "reviews_upserted": n}
            case CatalogRefreshRequest():
                return _catalog_service.refresh()

    # 3. SQS batch
    if "Records" in event:
        source_arn = event["Records"][0].get("eventSourceARN", "")
        if "app-crawl" in source_arn or "metadata-enrichment" in source_arn:
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
