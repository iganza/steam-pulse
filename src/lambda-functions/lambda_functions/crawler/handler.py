"""Lambda handler — crawler control plane + spoke dispatcher.

Event types handled:
  1. EventBridge (scheduled)  — source == "aws.events" → CatalogService.refresh()
  2. Direct boto3 invocation  — "action" key present   → dispatch via Pydantic model
  3. SQS (app-crawl / review-crawl) — dispatch to spoke Lambdas cross-region

DB ingest from spoke results is handled by ingest_handler.py (primary region).
"""

import os

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response,
)
from aws_lambda_powertools.utilities.parameters import get_parameter
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.config import SteamPulseConfig
from library_layer.utils.db import get_conn
from library_layer.utils.steam_metrics import make_steam_metrics_callback
from pydantic import TypeAdapter, ValidationError

from .events import (
    CatalogRefreshRequest,
    CrawlAppsRequest,
    CrawlReviewsRequest,
    DirectRequest,
    parse_spoke_request,
)

logger = Logger(service="crawler")
tracer = Tracer(service="crawler")
metrics = Metrics(namespace="SteamPulse", service="crawler")

_direct_adapter = TypeAdapter(DirectRequest)
_sqs_processor = BatchProcessor(event_type=EventType.SQS)

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

_sqs = boto3.client("sqs")
_sns = boto3.client("sns")
_s3 = boto3.client("s3")
_crawler_config = SteamPulseConfig()
metrics.set_default_dimensions(environment=_crawler_config.ENVIRONMENT)
_steam_metrics_callback = make_steam_metrics_callback(_crawler_config.ENVIRONMENT, metrics)

# Resolve SSM parameter names → actual values at cold start
_sfn_arn = get_parameter(_crawler_config.SFN_PARAM_NAME)
_sfn = boto3.client("stepfunctions")
_review_queue_url = get_parameter(_crawler_config.REVIEW_CRAWL_QUEUE_PARAM_NAME)
_app_crawl_queue_url = get_parameter(_crawler_config.APP_CRAWL_QUEUE_PARAM_NAME)
_game_events_topic_arn = get_parameter(_crawler_config.GAME_EVENTS_TOPIC_PARAM_NAME)
_content_events_topic_arn = get_parameter(_crawler_config.CONTENT_EVENTS_TOPIC_PARAM_NAME)
_system_events_topic_arn = get_parameter(_crawler_config.SYSTEM_EVENTS_TOPIC_PARAM_NAME)
_assets_bucket_name = get_parameter(_crawler_config.ASSETS_BUCKET_PARAM_NAME)

# Resolve Steam API key from Secrets Manager at cold start
_sm = boto3.client("secretsmanager")
_steam_api_key: str = _sm.get_secret_value(SecretId=_crawler_config.STEAM_API_KEY_SECRET_NAME)[
    "SecretString"
]

_crawl_service = CrawlService(
    game_repo=GameRepository(get_conn),
    review_repo=ReviewRepository(get_conn),
    catalog_repo=CatalogRepository(get_conn),
    tag_repo=TagRepository(get_conn),
    steam=DirectSteamSource(httpx.Client(timeout=60.0), on_request=_steam_metrics_callback),
    sqs_client=_sqs,
    review_queue_url=_review_queue_url,
    sfn_arn=_sfn_arn,
    sfn_client=_sfn,
    sns_client=_sns,
    config=_crawler_config,
    s3_client=_s3,
    archive_bucket=_assets_bucket_name,
    game_events_topic_arn=_game_events_topic_arn,
    content_events_topic_arn=_content_events_topic_arn,
)
_catalog_service = CatalogService(
    catalog_repo=CatalogRepository(get_conn),
    http_client=httpx.Client(timeout=30.0),
    sqs_client=_sqs,
    app_crawl_queue_url=_app_crawl_queue_url,
    sns_client=_sns,
    config=_crawler_config,
    steam_api_key=_steam_api_key,
    game_events_topic_arn=_game_events_topic_arn,
    system_events_topic_arn=_system_events_topic_arn,
)

# ── Spoke dispatch ──────────────────────────────────────────────────────────
# Each spoke region gets an SQS client + queue URL. Messages are durable —
# the spoke Lambda consumes via event source mapping with backpressure.

_spoke_sqs_targets: list[tuple[str, object]] = []  # [(queue_url, sqs_client), ...]

_regions = _crawler_config.spoke_region_list
_queue_urls = _crawler_config.spoke_crawl_queue_url_list
if len(_regions) != len(_queue_urls):
    raise RuntimeError(
        f"SPOKE_REGIONS has {len(_regions)} entries but SPOKE_CRAWL_QUEUE_URLS has "
        f"{len(_queue_urls)} — they must match 1:1. "
        f"regions={_regions}, queue_urls={_queue_urls}"
    )

for _region, _queue_url in zip(_regions, _queue_urls, strict=True):
    _sqs_spoke = boto3.client("sqs", region_name=_region)
    _spoke_sqs_targets.append((_queue_url, _sqs_spoke))

if not _spoke_sqs_targets and os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    raise RuntimeError(
        "SPOKE_REGIONS / SPOKE_CRAWL_QUEUE_URLS are empty — at least one spoke is required."
    )


def _dispatch_to_spoke(record: dict) -> None:
    """Parse SQS record and send to the per-spoke SQS queue for this appid."""
    if not _spoke_sqs_targets:
        raise RuntimeError("No spoke targets configured — cannot dispatch")

    req = parse_spoke_request(record, review_limit=_crawler_config.REVIEW_LIMIT)
    if req is None:
        logger.info("Skipping dispatch (budget exhausted)", extra={"record": record["messageId"]})
        return

    logger.append_keys(appid=req.appid, task=req.task)
    idx = req.appid % len(_spoke_sqs_targets)
    queue_url, sqs_client = _spoke_sqs_targets[idx]
    logger.info("Dispatching to spoke queue", extra={"queue_url": queue_url})

    sqs_client.send_message(QueueUrl=queue_url, MessageBody=req.model_dump_json())
    metrics.add_metric(name="SpokeDispatched", unit=MetricUnit.Count, value=1)


# ── Main dispatcher ──────────────────────────────────────────────────────────


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    # 1. EventBridge scheduled trigger
    if event.get("source") == "aws.events":
        logger.info("EventBridge trigger — running catalog refresh")
        result = _catalog_service.refresh()
        metrics.add_metric(name="CatalogRefreshRun", unit=MetricUnit.Count, value=1)
        metrics.add_metric(
            name="CatalogAppsDiscovered", unit=MetricUnit.Count, value=result.get("new_rows", 0)
        )
        metrics.add_metric(
            name="CatalogAppsEnqueued", unit=MetricUnit.Count, value=result.get("enqueued", 0)
        )
        return result

    # 2. Direct invocation (from web Lambda or manual)
    if "action" in event:
        try:
            req = _direct_adapter.validate_python(event)
        except ValidationError as exc:
            logger.error("Invalid direct invocation payload", extra={"error": str(exc)})
            raise
        logger.info("Direct invocation", extra={"action": event["action"]})
        match req:
            case CrawlAppsRequest():
                logger.append_keys(appid=req.appid, task="metadata")
                ok = _crawl_service.crawl_app(req.appid)
                logger.info("crawl_app complete", extra={"appid": req.appid, "success": ok})
                metrics.add_metric(
                    name="GamesUpserted", unit=MetricUnit.Count, value=1 if ok else 0
                )
                return {"appid": req.appid, "success": ok}
            case CrawlReviewsRequest():
                logger.append_keys(appid=req.appid, task="reviews")
                n = _crawl_service.crawl_reviews(req.appid, max_reviews=req.max_reviews)
                logger.info("crawl_reviews complete", extra={"appid": req.appid, "upserted": n})
                metrics.add_metric(name="ReviewsUpserted", unit=MetricUnit.Count, value=n)
                return {"appid": req.appid, "reviews_upserted": n}
            case CatalogRefreshRequest():
                result = _catalog_service.refresh()
                logger.info("catalog_refresh complete", extra={**result})
                metrics.add_metric(
                    name="CatalogAppsDiscovered",
                    unit=MetricUnit.Count,
                    value=result.get("new_rows", 0),
                )
                metrics.add_metric(
                    name="CatalogAppsEnqueued",
                    unit=MetricUnit.Count,
                    value=result.get("enqueued", 0),
                )
                return result

    # 3. SQS event (app-crawl / review-crawl) — dispatch to spoke Lambdas
    if "Records" in event:
        logger.info("SQS batch received", extra={"record_count": len(event["Records"])})
        return process_partial_response(
            event=event,
            record_handler=_dispatch_to_spoke,
            processor=_sqs_processor,
            context=context,
        )

    raise ValueError(f"Unrecognised event shape: {list(event.keys())}")
