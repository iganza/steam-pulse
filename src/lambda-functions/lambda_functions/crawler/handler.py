"""Lambda handler — unified crawler dispatcher.

Event types handled:
  1. EventBridge (scheduled)  — source == "aws.events" → catalog_refresh.run()
  2. Direct boto3 invocation  — "action" key present   → dispatch via Pydantic model
  3. SQS batch               — "Records" key present   → app_crawl or review_crawl
"""
from __future__ import annotations

import asyncio
import json

from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, process_partial_response
from aws_lambda_powertools.utilities.typing import LambdaContext
from pydantic import TypeAdapter, ValidationError

from . import app_crawl, review_crawl, catalog_refresh
from ._db import get_conn
from .events import (
    CrawlAppsRequest,
    CrawlReviewsRequest,
    CatalogRefreshRequest,
    DirectRequest,
)

logger = Logger(service="crawler")
tracer = Tracer(service="crawler")
metrics = Metrics(namespace="SteamPulse", service="crawler")

app_crawl_processor = BatchProcessor(event_type=EventType.SQS)
review_crawl_processor = BatchProcessor(event_type=EventType.SQS)

_direct_adapter = TypeAdapter(DirectRequest)


# ── SQS record handlers ──────────────────────────────────────────────────────

def _app_crawl_record(record: dict) -> None:
    body = json.loads(record["body"])
    req = CrawlAppsRequest(action="crawl_apps", appid=int(body["appid"]))
    result = asyncio.run(app_crawl.run(req, get_conn()))
    if result["success"]:
        metrics.add_metric(name="AppsCrawled", unit=MetricUnit.Count, value=1)


def _review_crawl_record(record: dict) -> None:
    body = json.loads(record["body"])
    req = CrawlReviewsRequest(action="crawl_reviews", appid=int(body["appid"]))
    result = asyncio.run(review_crawl.run(req, get_conn()))
    metrics.add_metric(name="ReviewsUpserted", unit=MetricUnit.Count, value=result["reviews_upserted"])


# ── Main dispatcher ──────────────────────────────────────────────────────────

@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    # 1. EventBridge scheduled trigger
    if event.get("source") == "aws.events":
        logger.info("EventBridge trigger — running catalog refresh")
        result = catalog_refresh.run(get_conn(), context)
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
                return asyncio.run(app_crawl.run(req, get_conn()))
            case CrawlReviewsRequest():
                return asyncio.run(review_crawl.run(req, get_conn()))
            case CatalogRefreshRequest():
                return catalog_refresh.run(get_conn(), context)

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
