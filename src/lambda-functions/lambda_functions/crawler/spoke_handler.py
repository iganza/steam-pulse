"""Spoke crawler — fetch from Steam, hand off to primary via S3 + SQS.

Consumes from a per-spoke SQS queue (event source mapping, max_concurrency=3).
The primary crawler sends SpokeRequest messages to this queue.

All payloads written to S3 (consistent, handles large metadata HTML).
Reviews are fetched one batch (BATCH_SIZE) at a time. The ingest handler
saves the returned cursor and re-queues for continuation.
"""

import gzip
import json
import os
import uuid

import boto3
import httpx
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response,
)
from aws_lambda_powertools.utilities.typing import LambdaContext
from lambda_functions.crawler.events import (
    CrawlTask,
    MetadataSpokeRequest,
    MetadataSpokeResult,
    ReviewSpokeRequest,
    ReviewSpokeResult,
    TagsSpokeRequest,
    TagsSpokeResult,
)
from library_layer.config import SteamPulseConfig
from library_layer.steam_source import DirectSteamSource, SteamAPIError

logger = Logger(service="crawler-spoke")

_config = SteamPulseConfig()
_PRIMARY_REGION = os.environ["PRIMARY_REGION"]
_SPOKE_RESULTS_QUEUE_URL = os.environ["SPOKE_RESULTS_QUEUE_URL"]

BATCH_SIZE = 1000

# Steam API key — resolve cross-region from primary's SSM SecureString.
# Powertools get_parameter doesn't accept region_name, so use raw boto3.
_ssm = boto3.client("ssm", region_name=_PRIMARY_REGION)
_steam_api_key: str = _ssm.get_parameter(
    Name=_config.STEAM_API_KEY_PARAM_NAME, WithDecryption=True
)["Parameter"]["Value"]

_steam = DirectSteamSource(
    httpx.Client(timeout=90.0),
    api_key=_steam_api_key,
)
_sqs = boto3.client("sqs", region_name=_PRIMARY_REGION)
_s3 = boto3.client("s3", region_name=_PRIMARY_REGION)
# Spoke exception: ASSETS_BUCKET_PARAM_NAME holds the actual bucket name (not an SSM path).
# Cross-region spokes can't call SSM in the primary region, so CDK injects the resolved
# value directly. See spoke_stack.py and CLAUDE.md "Spoke exception".
_assets_bucket_name: str = _config.ASSETS_BUCKET_PARAM_NAME

_sqs_processor = BatchProcessor(event_type=EventType.SQS)


# ── Main handler ────────────────────────────────────────────────────────────


def _process_record(record: dict) -> None:
    """Process a single SQS record containing a SpokeRequest."""
    body = json.loads(record["body"])
    task: CrawlTask = body.get("task", "metadata")

    match task:
        case "metadata":
            req = MetadataSpokeRequest.model_validate(body)
            logger.append_keys(appid=req.appid, task=task)
            logger.info("START metadata")
            ok = _process_metadata(req.appid)
            logger.info("metadata_fetched", extra={"appid": req.appid, "ok": ok})

        case "reviews":
            req = ReviewSpokeRequest.model_validate(body)
            logger.append_keys(appid=req.appid, task=task)
            logger.info("START reviews", extra={"cursor": req.cursor, "target": req.target})
            count, _ = _process_reviews(req.appid, req.cursor, req.target, req.started_at)
            logger.info("reviews_fetched", extra={"appid": req.appid, "count": count})

        case "tags":
            req = TagsSpokeRequest.model_validate(body)
            logger.append_keys(appid=req.appid, task=task)
            logger.info("START tags")
            ok = _process_tags(req.appid)
            logger.info("tags_fetched", extra={"appid": req.appid, "ok": ok})

        case _:
            raise ValueError(f"Unknown task: {task}")


def handler(event: dict, context: LambdaContext) -> dict:
    return process_partial_response(
        event=event,
        record_handler=_process_record,
        processor=_sqs_processor,
        context=context,
    )


# ── Steam fetch + S3 handoff ─────────────────────────────────────────────────


def _process_metadata(appid: int) -> bool:
    # Let SteamAPIError propagate — SQS retries the spoke-crawl-queue message.
    details = _steam.get_app_details(appid)

    if not details:
        # Game may be delisted or hidden — not an error, just nothing to crawl.
        logger.warning("Empty details from Steam — skipping", extra={"appid": appid})
        _notify_metadata(appid, success=False, error="empty details from Steam")
        return False

    game_name = details.get("name", "<unknown>")
    logger.info("Fetched app_details", extra={"appid": appid, "game_name": game_name})

    # Let SteamAPIError propagate for retry via SQS.
    summary = _steam.get_review_summary(appid)

    logger.info(
        "Fetched review_summary",
        extra={
            "appid": appid,
            "total_reviews": summary.get("total_reviews_all", summary.get("total_reviews", "?")),
        },
    )

    try:
        deck_compat = _steam.get_deck_compatibility(appid)
    except SteamAPIError as exc:
        logger.warning("Steam deck_compat unavailable", extra={"appid": appid, "error": str(exc)})
        deck_compat = {}

    payload = {"details": details, "summary": summary, "deck_compat": deck_compat}
    uid = uuid.uuid4().hex[:12]
    s3_key = _write_s3(f"spoke-results/metadata/{appid}-{uid}.json.gz", payload)
    _notify_metadata(appid, success=True, s3_key=s3_key, count=1)
    logger.info("DONE metadata", extra={"appid": appid, "game_name": game_name, "s3_key": s3_key})
    return True


def _process_reviews(
    appid: int,
    cursor: str,
    target: int | None,
    started_at: str | None,
) -> tuple[int, str | None]:
    limit = min(target, BATCH_SIZE) if target is not None else BATCH_SIZE
    logger.info("Fetching reviews", extra={"appid": appid, "limit": limit, "cursor": cursor})

    # Let SteamAPIError propagate — SQS retries the spoke-crawl-queue message,
    # and after maxReceiveCount failures it lands in the spoke DLQ.
    reviews, next_cursor = _steam.get_reviews(appid, max_reviews=limit, start_cursor=cursor)

    if not reviews:
        # Legitimate terminal state — game has no (more) reviews.
        # Send success=True so ingest marks reviews complete.
        logger.info("No reviews returned from Steam", extra={"appid": appid, "cursor": cursor})
        _notify_reviews(
            appid,
            success=True,
            count=0,
            next_cursor=None,
            target=target,
            started_at=started_at,
        )
        return 0, None

    exhausted = next_cursor is None
    logger.info(
        "Fetched reviews",
        extra={
            "appid": appid,
            "count": len(reviews),
            "exhausted": exhausted,
            "next_cursor": next_cursor,
        },
    )

    uid = uuid.uuid4().hex[:12]
    s3_key = _write_s3(f"spoke-results/reviews/{appid}-{uid}.json.gz", reviews)
    _notify_reviews(
        appid,
        success=True,
        s3_key=s3_key,
        count=len(reviews),
        next_cursor=next_cursor,
        target=target,
        started_at=started_at,
    )
    logger.info("DONE reviews", extra={"appid": appid, "count": len(reviews), "s3_key": s3_key})
    return len(reviews), next_cursor


def _write_s3(key: str, data: dict | list) -> str:
    payload = gzip.compress(json.dumps(data).encode())
    bucket = _assets_bucket_name
    _s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=payload,
        ContentEncoding="gzip",
        ContentType="application/json",
    )
    logger.info("Wrote to S3", extra={"bytes": len(payload), "bucket": bucket, "key": key})
    return key


def _process_tags(appid: int) -> bool:
    """Fetch player tags from Steam store page, upload to S3, notify ingest via SQS."""
    # Let exceptions propagate for retry via SQS.
    tags = _steam.get_player_tags(appid)

    if not tags:
        logger.warning("No tags found on store page", extra={"appid": appid})
        _notify_tags(appid, success=True, count=0)
        return True

    result_data = {"tags": tags}
    uid = uuid.uuid4().hex[:12]
    s3_key = _write_s3(f"spoke-results/tags/{appid}-{uid}.json.gz", result_data)
    _notify_tags(appid, success=True, s3_key=s3_key, count=len(tags))
    logger.info("DONE tags", extra={"appid": appid, "tag_count": len(tags), "s3_key": s3_key})
    return True


def _notify_tags(
    appid: int,
    *,
    success: bool,
    s3_key: str | None = None,
    count: int = 0,
    error: str | None = None,
) -> None:
    msg = TagsSpokeResult(
        appid=appid,
        success=success,
        s3_key=s3_key,
        count=count,
        spoke_region=os.environ.get("AWS_REGION", "unknown"),
        error=error,
    )
    _sqs.send_message(
        QueueUrl=_SPOKE_RESULTS_QUEUE_URL,
        MessageBody=msg.model_dump_json(),
    )


def _notify_metadata(
    appid: int,
    *,
    success: bool,
    s3_key: str | None = None,
    count: int = 0,
    error: str | None = None,
) -> None:
    msg = MetadataSpokeResult(
        appid=appid,
        success=success,
        s3_key=s3_key,
        count=count,
        spoke_region=os.environ.get("AWS_REGION", "unknown"),
        error=error,
    )
    _sqs.send_message(
        QueueUrl=_SPOKE_RESULTS_QUEUE_URL,
        MessageBody=msg.model_dump_json(),
    )


def _notify_reviews(
    appid: int,
    *,
    success: bool,
    s3_key: str | None = None,
    count: int = 0,
    next_cursor: str | None = None,
    target: int | None = None,
    started_at: str | None = None,
    error: str | None = None,
) -> None:
    msg = ReviewSpokeResult(
        appid=appid,
        success=success,
        s3_key=s3_key,
        count=count,
        spoke_region=os.environ.get("AWS_REGION", "unknown"),
        next_cursor=next_cursor,
        target=target,
        started_at=started_at,
        error=error,
    )
    _sqs.send_message(
        QueueUrl=_SPOKE_RESULTS_QUEUE_URL,
        MessageBody=msg.model_dump_json(),
    )
