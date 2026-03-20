"""Spoke crawler — fetch from Steam, hand off to primary via S3 + SQS.

Invoked directly by the primary handler (cross-region lambda:Invoke).
No event source mappings — work is dispatched from the primary region.

Input payload: {"appid": int, "task": "metadata"|"reviews"}
Returns:       {"appid": int, "task": str, "success": bool, "count": int}

All payloads written to S3 (consistent, handles large metadata HTML).
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import uuid

import boto3
import httpx
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext
from lambda_functions.crawler.events import CrawlTask, SpokeRequest, SpokeResponse, SpokeResult
from library_layer.config import SteamPulseConfig
from library_layer.steam_source import DirectSteamSource, SteamAPIError

logger = Logger(service="crawler-spoke")
tracer = Tracer(service="crawler-spoke")
metrics = Metrics(namespace="SteamPulse", service="crawler-spoke")

_config = SteamPulseConfig()
_PRIMARY_REGION = os.environ["PRIMARY_REGION"]
_SPOKE_RESULTS_QUEUE_URL = os.environ["SPOKE_RESULTS_QUEUE_URL"]

# Steam API key — resolve cross-region from primary's Secrets Manager
_sm = boto3.client("secretsmanager", region_name=_PRIMARY_REGION)
_steam_api_key: str = _sm.get_secret_value(
    SecretId=_config.STEAM_API_KEY_SECRET_NAME
)["SecretString"]

_http = httpx.AsyncClient(timeout=90.0)
_steam = DirectSteamSource(_http, api_key=_steam_api_key)
_sqs = boto3.client("sqs", region_name=_PRIMARY_REGION)
_s3 = boto3.client("s3")


# ── Main handler ────────────────────────────────────────────────────────────


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    req = SpokeRequest.model_validate(event)
    appid = req.appid
    task = req.task

    if task == "metadata":
        ok = asyncio.run(_process_metadata(appid))
        metrics.add_metric(name="AppsCrawled", unit=MetricUnit.Count, value=1 if ok else 0)
        return SpokeResponse(appid=appid, task=task, success=ok, count=1 if ok else 0).model_dump()

    if task == "reviews":
        count = asyncio.run(_process_reviews(appid))
        metrics.add_metric(name="ReviewsCrawled", unit=MetricUnit.Count, value=count)
        return SpokeResponse(appid=appid, task=task, success=count > 0, count=count).model_dump()

    raise ValueError(f"Unknown task: {task}")


# ── Steam fetch + S3 handoff ─────────────────────────────────────────────────


async def _process_metadata(appid: int) -> bool:
    try:
        details = await _steam.get_app_details(appid)
    except SteamAPIError as exc:
        logger.warning("Steam metadata error appid=%s: %s", appid, exc)
        _notify(appid, task="metadata", success=False, error=str(exc))
        return False

    if not details:
        _notify(appid, task="metadata", success=False, error="empty details from Steam")
        return False

    summary = await _steam.get_review_summary(appid)
    deck_compat = await _steam.get_deck_compatibility(appid)

    payload = {"details": details, "summary": summary, "deck_compat": deck_compat}
    uid = uuid.uuid4().hex[:12]
    s3_key = _write_s3(f"spoke-results/metadata/{appid}-{uid}.json.gz", payload)
    _notify(appid, task="metadata", success=True, s3_key=s3_key, count=1)
    return True


async def _process_reviews(appid: int) -> int:
    try:
        reviews = await _steam.get_reviews(appid, max_reviews=None)
    except SteamAPIError as exc:
        logger.warning("Steam reviews error appid=%s: %s", appid, exc)
        _notify(appid, task="reviews", success=False, error=str(exc))
        return 0

    if not reviews:
        _notify(appid, task="reviews", success=False, error="no reviews returned")
        return 0

    uid = uuid.uuid4().hex[:12]
    s3_key = _write_s3(f"spoke-results/reviews/{appid}-{uid}.json.gz", reviews)
    _notify(appid, task="reviews", success=True, s3_key=s3_key, count=len(reviews))
    return len(reviews)


def _write_s3(key: str, data: dict | list) -> str:
    payload = gzip.compress(json.dumps(data).encode())
    _s3.put_object(
        Bucket=_config.ASSETS_BUCKET_PARAM_NAME,
        Key=key,
        Body=payload,
        ContentEncoding="gzip",
        ContentType="application/json",
    )
    logger.info(
        "Wrote %d bytes to s3://%s/%s",
        len(payload),
        _config.ASSETS_BUCKET_PARAM_NAME,
        key,
    )
    return key


def _notify(
    appid: int,
    task: CrawlTask,
    *,
    success: bool,
    s3_key: str | None = None,
    count: int = 0,
    error: str | None = None,
) -> None:
    msg = SpokeResult(
        appid=appid,
        task=task,
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
