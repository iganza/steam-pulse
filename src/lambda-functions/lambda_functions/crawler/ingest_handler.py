"""Spoke ingest handler — reads S3, routes to CrawlService, writes to RDS.

Pure data acquisition: fetch from S3 → upsert to DB → done.
LLM analysis is a separate scheduled concern — NOT triggered from here.

Triggered by: spoke_results_queue (SQS, primary region only)
Routes on message["task"]:
  "metadata" → crawl_service.ingest_spoke_metadata()
  "reviews"  → crawl_service.ingest_spoke_reviews() + cursor persistence + re-queue
"""

from __future__ import annotations

import gzip
import json

import boto3
import httpx
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response,
)
from aws_lambda_powertools.utilities.parameters import get_parameter
from aws_lambda_powertools.utilities.typing import LambdaContext
from lambda_functions.crawler.events import MetadataSpokeResult, ReviewSpokeResult
from library_layer.config import SteamPulseConfig
from library_layer.repositories.catalog_repo import CatalogRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.services.crawl_service import CrawlService
from library_layer.steam_source import DirectSteamSource
from library_layer.utils.db import get_conn

from library_layer.utils.steam_metrics import make_steam_metrics_callback


logger = Logger(service="spoke-ingest")
tracer = Tracer(service="spoke-ingest")
metrics = Metrics(namespace="SteamPulse", service="spoke-ingest")

ingest_processor = BatchProcessor(event_type=EventType.SQS)

_conn = get_conn()
_sqs = boto3.client("sqs")
_sns = boto3.client("sns")
_s3 = boto3.client("s3")
_config = SteamPulseConfig()
metrics.set_default_dimensions(environment=_config.ENVIRONMENT)
_steam_metrics_callback = make_steam_metrics_callback(_config.ENVIRONMENT)

# Resolve SSM params — ingest runs in primary region, SSM works normally
_review_crawl_queue_url = get_parameter(_config.REVIEW_CRAWL_QUEUE_PARAM_NAME)
_assets_bucket_name = get_parameter(_config.ASSETS_BUCKET_PARAM_NAME)
_game_events_topic_arn = get_parameter(_config.GAME_EVENTS_TOPIC_PARAM_NAME)
_content_events_topic_arn = get_parameter(_config.CONTENT_EVENTS_TOPIC_PARAM_NAME)

_catalog_repo = CatalogRepository(_conn)
_review_repo = ReviewRepository(_conn)

_crawl_service = CrawlService(
    game_repo=GameRepository(_conn),
    review_repo=_review_repo,
    catalog_repo=_catalog_repo,
    tag_repo=TagRepository(_conn),
    steam=DirectSteamSource(httpx.Client(timeout=60.0), on_request=_steam_metrics_callback),
    sqs_client=_sqs,
    review_queue_url=_review_crawl_queue_url,
    sns_client=_sns,
    config=_config,
    game_events_topic_arn=_game_events_topic_arn,
    content_events_topic_arn=_content_events_topic_arn,
    s3_client=_s3,
    archive_bucket=_assets_bucket_name,
)


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    return process_partial_response(
        event=event,
        record_handler=_ingest_record,
        processor=ingest_processor,
        context=context,
    )


def _ingest_record(record: dict) -> None:
    body = json.loads(record["body"])
    task = body.get("task", "metadata")

    if task == "metadata":
        msg = MetadataSpokeResult.model_validate(body)
        _handle_metadata(msg)
    elif task == "reviews":
        msg = ReviewSpokeResult.model_validate(body)
        _handle_reviews(msg)
    else:
        raise ValueError(f"Unknown task: {task}")


def _handle_metadata(msg: MetadataSpokeResult) -> None:
    if not msg.success:
        logger.info(
            "Spoke reported failure: task=metadata appid=%s error=%s",
            msg.appid, msg.error,
        )
        return

    appid = msg.appid
    s3_key = msg.s3_key

    if not s3_key:
        raise ValueError(f"success=True but s3_key missing: task=metadata appid={appid}")

    response = _s3.get_object(Bucket=_assets_bucket_name, Key=s3_key)
    data = json.loads(gzip.decompress(response["Body"].read()))

    success = _crawl_service.ingest_spoke_metadata(appid, data)
    if not success:
        raise RuntimeError(f"Metadata ingest failed for appid={appid}")
    logger.info("Ingested metadata appid=%s", appid)
    metrics.add_metric(name="GamesUpserted", unit=MetricUnit.Count, value=1)

    _s3.delete_object(Bucket=_assets_bucket_name, Key=s3_key)


def _handle_reviews(msg: ReviewSpokeResult) -> None:
    if not msg.success:
        logger.info(
            "Spoke reported failure: task=reviews appid=%s error=%s",
            msg.appid, msg.error,
        )
        return

    appid = msg.appid
    s3_key = msg.s3_key

    if not s3_key:
        raise ValueError(f"success=True but s3_key missing: task=reviews appid={appid}")

    response = _s3.get_object(Bucket=_assets_bucket_name, Key=s3_key)
    data = json.loads(gzip.decompress(response["Body"].read()))

    upserted = _crawl_service.ingest_spoke_reviews(appid, data)
    logger.info("Ingested %d reviews for appid=%s", upserted, appid)
    metrics.add_metric(name="ReviewsUpserted", unit=MetricUnit.Count, value=upserted)

    _s3.delete_object(Bucket=_assets_bucket_name, Key=s3_key)

    # Cursor management + re-queue logic
    total_fetched = _review_repo.count_by_appid(appid)
    target = _catalog_repo.get_reviews_target(appid)
    target_hit = target is not None and total_fetched >= target
    exhausted = msg.next_cursor is None

    if exhausted:
        _catalog_repo.clear_review_cursor(appid)
        logger.info("Reviews exhausted for appid=%s total=%d", appid, total_fetched)
    elif target_hit:
        _catalog_repo.save_review_cursor(appid, msg.next_cursor)
        logger.info(
            "Reviews target hit for appid=%s total=%d target=%d — stopping",
            appid, total_fetched, target,
        )
    else:
        # More to fetch — save cursor and re-queue
        _catalog_repo.save_review_cursor(appid, msg.next_cursor)
        _sqs.send_message(
            QueueUrl=_review_crawl_queue_url,
            MessageBody=json.dumps({"appid": appid}),
        )
        logger.info(
            "Re-queued appid=%s for next batch, total so far=%d",
            appid, total_fetched,
        )
