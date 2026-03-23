"""Spoke crawler — fetch from Steam, hand off to primary via S3 + SQS.

Invoked directly by the primary handler (cross-region lambda:Invoke).
No event source mappings — work is dispatched from the primary region.

Input payload: MetadataSpokeRequest | ReviewSpokeRequest
Returns:       {"appid": int, "task": str, "success": bool, "count": int}

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
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext
from lambda_functions.crawler.events import (
    CrawlTask,
    MetadataSpokeRequest,
    MetadataSpokeResult,
    ReviewSpokeRequest,
    ReviewSpokeResult,
    SpokeResponse,
)
from library_layer.config import SteamPulseConfig
from library_layer.steam_source import DirectSteamSource, SteamAPIError
from library_layer.utils.steam_metrics import make_steam_metrics_callback

logger = Logger(service="crawler-spoke")
tracer = Tracer(service="crawler-spoke")
metrics = Metrics(namespace="SteamPulse", service="crawler-spoke")

_config = SteamPulseConfig()
metrics.set_default_dimensions(environment=_config.ENVIRONMENT)
_PRIMARY_REGION = os.environ["PRIMARY_REGION"]
_SPOKE_RESULTS_QUEUE_URL = os.environ["SPOKE_RESULTS_QUEUE_URL"]

BATCH_SIZE = 1000

# Steam API key — resolve cross-region from primary's Secrets Manager
_sm = boto3.client("secretsmanager", region_name=_PRIMARY_REGION)
_steam_api_key: str = _sm.get_secret_value(
    SecretId=_config.STEAM_API_KEY_SECRET_NAME
)["SecretString"]

_steam_metrics_callback = make_steam_metrics_callback(_config.ENVIRONMENT, metrics)
_steam = DirectSteamSource(
    httpx.Client(timeout=90.0),
    api_key=_steam_api_key,
    on_request=_steam_metrics_callback,
)
_sqs = boto3.client("sqs", region_name=_PRIMARY_REGION)
_s3 = boto3.client("s3", region_name=_PRIMARY_REGION)
# Spoke exception: ASSETS_BUCKET_PARAM_NAME holds the actual bucket name (not an SSM path).
# Cross-region spokes can't call SSM in the primary region, so CDK injects the resolved
# value directly. See spoke_stack.py and CLAUDE.md "Spoke exception".
_assets_bucket_name: str = _config.ASSETS_BUCKET_PARAM_NAME


# ── Main handler ────────────────────────────────────────────────────────────


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    task: CrawlTask = event.get("task", "metadata")

    if task == "metadata":
        req = MetadataSpokeRequest.model_validate(event)
        logger.info("START metadata appid=%s", req.appid)
        ok = _process_metadata(req.appid)
        metrics.add_metric(name="MetadataFetched", unit=MetricUnit.Count, value=1 if ok else 0)
        return SpokeResponse(appid=req.appid, task=task, success=ok, count=1 if ok else 0).model_dump()

    if task == "reviews":
        req = ReviewSpokeRequest.model_validate(event)
        logger.info(
            "START reviews appid=%s cursor=%s max_reviews=%s",
            req.appid, req.cursor, req.max_reviews,
        )
        count, _ = _process_reviews(req.appid, req.cursor, req.max_reviews)
        metrics.add_metric(name="ReviewsFetched", unit=MetricUnit.Count, value=count)
        return SpokeResponse(appid=req.appid, task=task, success=count > 0, count=count).model_dump()

    raise ValueError(f"Unknown task: {task}")


# ── Steam fetch + S3 handoff ─────────────────────────────────────────────────


def _process_metadata(appid: int) -> bool:
    try:
        details = _steam.get_app_details(appid)
    except SteamAPIError as exc:
        logger.error("Steam app_details error appid=%s: %s", appid, exc)
        _notify_metadata(appid, success=False, error=str(exc))
        return False

    if not details:
        logger.warning("Empty details from Steam appid=%s — skipping", appid)
        _notify_metadata(appid, success=False, error="empty details from Steam")
        return False

    game_name = details.get("name", "<unknown>")
    logger.info("Fetched app_details appid=%s name=%r", appid, game_name)

    try:
        summary = _steam.get_review_summary(appid)
    except SteamAPIError as exc:
        logger.error("Steam review_summary error appid=%s: %s", appid, exc)
        _notify_metadata(appid, success=False, error=str(exc))
        return False

    logger.info(
        "Fetched review_summary appid=%s total_reviews=%s",
        appid, summary.get("total_reviews_all", summary.get("total_reviews", "?")),
    )

    try:
        deck_compat = _steam.get_deck_compatibility(appid)
    except SteamAPIError as exc:
        logger.warning("Steam deck_compat unavailable appid=%s: %s", appid, exc)
        deck_compat = {}

    payload = {"details": details, "summary": summary, "deck_compat": deck_compat}
    uid = uuid.uuid4().hex[:12]
    s3_key = _write_s3(f"spoke-results/metadata/{appid}-{uid}.json.gz", payload)
    _notify_metadata(appid, success=True, s3_key=s3_key, count=1)
    logger.info("DONE metadata appid=%s name=%r → %s", appid, game_name, s3_key)
    return True


def _process_reviews(
    appid: int,
    cursor: str,
    max_reviews: int | None,
) -> tuple[int, str | None]:
    limit = min(max_reviews, BATCH_SIZE) if max_reviews is not None else BATCH_SIZE
    logger.info("Fetching reviews appid=%s limit=%d cursor=%s", appid, limit, cursor)

    try:
        reviews, next_cursor = _steam.get_reviews(appid, max_reviews=limit, start_cursor=cursor)
    except SteamAPIError as exc:
        logger.warning("Steam reviews error appid=%s: %s", appid, exc)
        _notify_reviews(appid, success=False, error=str(exc), next_cursor=None)
        return 0, None

    if not reviews:
        logger.warning("No reviews returned from Steam appid=%s cursor=%s", appid, cursor)
        _notify_reviews(appid, success=False, error="no reviews returned", next_cursor=None)
        return 0, None

    exhausted = next_cursor is None
    logger.info(
        "Fetched %d reviews appid=%s %s",
        len(reviews), appid,
        "— stream exhausted" if exhausted else f"next_cursor={next_cursor}",
    )

    uid = uuid.uuid4().hex[:12]
    s3_key = _write_s3(f"spoke-results/reviews/{appid}-{uid}.json.gz", reviews)
    _notify_reviews(appid, success=True, s3_key=s3_key, count=len(reviews), next_cursor=next_cursor)
    logger.info("DONE reviews appid=%s count=%d → %s", appid, len(reviews), s3_key)
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
    logger.info(
        "Wrote %d bytes to s3://%s/%s",
        len(payload),
        bucket,
        key,
    )
    return key


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
    error: str | None = None,
) -> None:
    msg = ReviewSpokeResult(
        appid=appid,
        success=success,
        s3_key=s3_key,
        count=count,
        spoke_region=os.environ.get("AWS_REGION", "unknown"),
        next_cursor=next_cursor,
        error=error,
    )
    _sqs.send_message(
        QueueUrl=_SPOKE_RESULTS_QUEUE_URL,
        MessageBody=msg.model_dump_json(),
    )
