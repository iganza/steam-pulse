"""Spoke ingest handler — reads S3, routes to CrawlService, writes to RDS.

Pure data acquisition: fetch from S3 → upsert to DB → done.
LLM analysis is a separate scheduled concern — NOT triggered from here.

Triggered by: spoke_results_queue (SQS, primary region only)
Routes on message["task"]:
  "metadata" → crawl_service.ingest_spoke_metadata()
  "reviews"  → crawl_service.ingest_spoke_reviews() + cursor persistence + re-queue
"""

import gzip
import json
import os
from datetime import UTC, datetime

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
from lambda_functions.crawler.events import (
    MetadataSpokeResult,
    ReviewSpokeRequest,
    ReviewSpokeResult,
    TagsSpokeResult,
    spoke_index_for_appid,
)
from library_layer.config import SteamPulseConfig
from library_layer.repositories.catalog_repo import CatalogRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.services.crawl_service import CrawlService
from library_layer.steam_source import DirectSteamSource
from library_layer.utils.db import get_conn, transaction
from library_layer.utils.steam_metrics import make_steam_metrics_callback

logger = Logger(service="spoke-ingest")
tracer = Tracer(service="spoke-ingest")
metrics = Metrics(namespace="SteamPulse", service="spoke-ingest")

ingest_processor = BatchProcessor(event_type=EventType.SQS)

_sqs = boto3.client("sqs")
_sns = boto3.client("sns")
_s3 = boto3.client("s3")
_config = SteamPulseConfig()
metrics.set_default_dimensions(environment=_config.ENVIRONMENT)
_steam_metrics_callback = make_steam_metrics_callback(_config.ENVIRONMENT, metrics)

# Resolve SSM params — ingest runs in primary region, SSM works normally
_review_crawl_queue_url = get_parameter(_config.REVIEW_CRAWL_QUEUE_PARAM_NAME)
_assets_bucket_name = get_parameter(_config.ASSETS_BUCKET_PARAM_NAME)
_game_events_topic_arn = get_parameter(_config.GAME_EVENTS_TOPIC_PARAM_NAME)
_content_events_topic_arn = get_parameter(_config.CONTENT_EVENTS_TOPIC_PARAM_NAME)

_catalog_repo = CatalogRepository(get_conn)
_review_repo = ReviewRepository(get_conn)
_tag_repo = TagRepository(get_conn)

# Per-spoke SQS targets — for direct re-queue of review pagination.
# Eliminates the round-trip through the primary crawler dispatcher.
_spoke_sqs_targets: list[tuple[str, object]] = []
_regions = _config.spoke_region_list
_queue_urls = _config.spoke_crawl_queue_url_list
if len(_regions) != len(_queue_urls):
    raise RuntimeError(
        f"SPOKE_REGIONS has {len(_regions)} entries but SPOKE_CRAWL_QUEUE_URLS has "
        f"{len(_queue_urls)} — they must match 1:1. "
        f"regions={_regions}, queue_urls={_queue_urls}"
    )
for _region, _queue_url in zip(_regions, _queue_urls, strict=True):
    _spoke_sqs_targets.append((_queue_url, boto3.client("sqs", region_name=_region)))

if not _spoke_sqs_targets and os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    raise RuntimeError(
        "SPOKE_REGIONS / SPOKE_CRAWL_QUEUE_URLS are empty — at least one spoke is required "
        "for review pagination re-queue."
    )

_crawl_service = CrawlService(
    game_repo=GameRepository(get_conn),
    review_repo=_review_repo,
    catalog_repo=_catalog_repo,
    tag_repo=TagRepository(get_conn),
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
    appid = body.get("appid", "?")
    success = body.get("success", False)
    logger.append_keys(appid=appid, task=task)
    logger.info("Received spoke result", extra={"success": success})

    try:
        if task == "metadata":
            msg = MetadataSpokeResult.model_validate(body)
            _handle_metadata(msg)
        elif task == "reviews":
            msg = ReviewSpokeResult.model_validate(body)
            _handle_reviews(msg)
        elif task == "tags":
            msg = TagsSpokeResult.model_validate(body)
            _handle_tags(msg)
        else:
            raise ValueError(f"Unknown task: {task}")
    except Exception:
        logger.exception("Record processing failed", extra={"appid": appid, "task": task})
        raise


def _handle_metadata(msg: MetadataSpokeResult) -> None:
    if not msg.success:
        # Permanent failure (e.g. game delisted) — log and skip, don't retry.
        logger.warning("Spoke reported metadata failure", extra={"appid": msg.appid, "error": msg.error})
        with transaction(get_conn()):
            _catalog_repo.set_meta_status(msg.appid, "failed")
        return

    appid = msg.appid
    s3_key = msg.s3_key

    if not s3_key:
        raise ValueError(f"success=True but s3_key missing: task=metadata appid={appid}")

    try:
        response = _s3.get_object(Bucket=_assets_bucket_name, Key=s3_key)
    except _s3.exceptions.NoSuchKey:
        # Record is a duplicate redelivery — the prior delivery completed all
        # side effects (DB upsert, SQS re-queue, S3 delete). Silently succeed.
        logger.info("Skipping already-processed record", extra={"appid": appid, "s3_key": s3_key})
        return
    data = json.loads(gzip.decompress(response["Body"].read()))

    # ingest_spoke_metadata owns its own narrow transaction internally.
    success = _crawl_service.ingest_spoke_metadata(appid, data)
    if not success:
        raise RuntimeError(f"Metadata ingest failed for appid={appid}")
    logger.info("Ingested metadata", extra={"appid": appid})
    metrics.add_metric(name="GamesUpserted", unit=MetricUnit.Count, value=1)

    _s3.delete_object(Bucket=_assets_bucket_name, Key=s3_key)


def _handle_tags(msg: TagsSpokeResult) -> None:
    if not msg.success:
        # Spoke should not send success=False for tags anymore (transient errors
        # propagate as exceptions in the spoke). This is a safety net.
        logger.warning("Spoke reported tags failure", extra={"appid": msg.appid, "error": msg.error})
        return

    if not msg.s3_key:
        logger.info("No tag data available", extra={"appid": msg.appid})
        with transaction(get_conn()):
            _catalog_repo.mark_tags_crawled(msg.appid)
        return

    try:
        response = _s3.get_object(Bucket=_assets_bucket_name, Key=msg.s3_key)
    except _s3.exceptions.NoSuchKey:
        logger.info(
            "Skipping already-processed record",
            extra={"appid": msg.appid, "s3_key": msg.s3_key},
        )
        return
    data = json.loads(gzip.decompress(response["Body"].read()))

    tags = data.get("tags") or []
    if tags:
        with transaction(get_conn()):
            _tag_repo.upsert_tags(
                [
                    {
                        "appid": msg.appid,
                        "name": t["name"],
                        "votes": t["votes"],
                        "tagid": t.get("tagid"),
                    }
                    for t in tags
                ]
            )
            _catalog_repo.mark_tags_crawled(msg.appid)
        logger.info("Tags upserted", extra={"appid": msg.appid, "count": len(tags)})

    metrics.add_metric(name="TagsIngested", unit=MetricUnit.Count, value=len(tags))
    _s3.delete_object(Bucket=_assets_bucket_name, Key=msg.s3_key)


def _handle_reviews(msg: ReviewSpokeResult) -> None:
    if not msg.success:
        # Spoke should not send success=False for reviews anymore (transient errors
        # propagate as exceptions in the spoke). This is a safety net.
        logger.warning("Spoke reported review failure", extra={"appid": msg.appid, "error": msg.error})
        return

    appid = msg.appid
    s3_key = msg.s3_key
    logger.info(
        "Ingesting reviews",
        extra={"appid": appid, "count": msg.count, "next_cursor": msg.next_cursor},
    )

    if not s3_key:
        # Spoke sends success=True with no s3_key when Steam returns zero
        # reviews for the game. Mark crawled and move on — same pattern as tags.
        logger.info("No review data available", extra={"appid": appid})
        with transaction(get_conn()):
            _catalog_repo.mark_reviews_crawled(appid)
        return

    try:
        response = _s3.get_object(Bucket=_assets_bucket_name, Key=s3_key)
    except _s3.exceptions.NoSuchKey:
        logger.info("Skipping already-processed record", extra={"appid": appid, "s3_key": s3_key})
        return
    data = json.loads(gzip.decompress(response["Body"].read()))

    # One DB unit-of-work: upsert reviews + flip catalog watermarks together.
    # Success logs + metrics emit AFTER commit so a rollback doesn't leave
    # inaccurate "Reviews ingested/complete" signals in logs/CloudWatch.
    # SQS re-queue (else branch) and S3 delete also stay outside the tx.
    with transaction(get_conn()):
        upserted = _crawl_service.ingest_spoke_reviews(appid, data)

        # Early-stop: on re-crawls (reviews_completed_at IS NOT NULL), Steam returns
        # newest reviews first. Once min(batch.timestamp_created) predates our last
        # completed crawl we've covered the entire gap of new reviews — stop early.
        reviews_completed_at = _catalog_repo.get_reviews_completed_at(appid)
        min_batch_ts = min((r.get("timestamp_created", 0) for r in data), default=0)
        early_stop = (
            reviews_completed_at is not None
            and min_batch_ts > 0
            and datetime.fromtimestamp(min_batch_ts, tz=UTC) < reviews_completed_at
        )

        # `target` means "remaining reviews to fetch in this chain" — decremented by batch count
        # each hop so the spoke can limit its final batch to exactly what's left.
        # target_hit fires when this batch consumed the last of the budget.
        target_hit = msg.target is not None and msg.target <= msg.count
        exhausted = msg.next_cursor is None

        if exhausted or early_stop:
            # On early-stop, use the batch boundary as the watermark so that reviews
            # posted *during* this crawl are not skipped on the next re-crawl.
            # On exhaustion, pass None → mark_reviews_complete defaults to NOW() (correct:
            # we have every review up to this moment).
            boundary = datetime.fromtimestamp(min_batch_ts, tz=UTC) if early_stop else None
            _catalog_repo.mark_reviews_complete(appid, completed_at=boundary)
            _catalog_repo.mark_reviews_crawled(appid)
        elif target_hit:
            # Budget exhausted — mark complete so early-stop on re-crawls picks up only new reviews.
            _catalog_repo.mark_reviews_complete(appid, completed_at=None)
            _catalog_repo.mark_reviews_crawled(appid)

    # Commit done. Emit success signals + side effects below.
    logger.info("Reviews ingested", extra={"appid": appid, "upserted": upserted})
    metrics.add_metric(name="ReviewsUpserted", unit=MetricUnit.Count, value=upserted)

    if exhausted or early_stop:
        if early_stop:
            logger.info(
                "Reviews complete",
                extra={
                    "appid": appid,
                    "reason": "early_stop",
                    "batch_count": msg.count,
                    "min_batch_ts": datetime.fromtimestamp(
                        min_batch_ts, tz=UTC
                    ).isoformat()
                    if min_batch_ts
                    else None,
                    "watermark": reviews_completed_at.isoformat() if reviews_completed_at else None,
                },
            )
        else:
            logger.info(
                "Reviews complete",
                extra={
                    "appid": appid,
                    "reason": "exhausted",
                    "batch_count": msg.count,
                },
            )
    elif target_hit:
        logger.info(
            "Reviews complete",
            extra={
                "appid": appid,
                "reason": "target_hit",
                "batch_count": msg.count,
                "target": msg.target,
            },
        )
    else:
        # More to fetch — re-queue directly to the spoke's SQS queue,
        # bypassing the primary crawler dispatcher entirely.
        new_remaining = msg.target - msg.count if msg.target is not None else None
        idx = spoke_index_for_appid(appid, len(_spoke_sqs_targets))
        queue_url, spoke_sqs = _spoke_sqs_targets[idx]
        req = ReviewSpokeRequest(
            appid=appid,
            cursor=msg.next_cursor,
            target=new_remaining,
            started_at=msg.started_at,
        )
        spoke_sqs.send_message(QueueUrl=queue_url, MessageBody=req.model_dump_json())
        logger.info(
            "Re-queued for next batch",
            extra={
                "appid": appid,
                "remaining": new_remaining,
                "cursor": msg.next_cursor,
                "queue_url": queue_url,
            },
        )

    _s3.delete_object(Bucket=_assets_bucket_name, Key=s3_key)
