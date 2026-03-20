"""Spoke crawler — fetch from Steam, hand off to primary via S3 + SQS.

No DB access. Task type inferred from which SQS queue triggered the Lambda.
Routing (same pattern as primary handler.py):
  "app-crawl" or "metadata" in eventSourceARN → task = metadata
  "review-crawl" in eventSourceARN             → task = reviews

All payloads written to S3 (consistent, handles large metadata HTML).
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os

import boto3
import httpx
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response,
)
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.config import SteamPulseConfig
from library_layer.steam_source import DirectSteamSource, SteamAPIError

logger = Logger(service="crawler-spoke")
tracer = Tracer(service="crawler-spoke")
metrics = Metrics(namespace="SteamPulse", service="crawler-spoke")

app_crawl_processor = BatchProcessor(event_type=EventType.SQS)
review_crawl_processor = BatchProcessor(event_type=EventType.SQS)

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
    result = asyncio.run(_process_metadata(appid))
    if result:
        metrics.add_metric(name="AppsCrawled", unit=MetricUnit.Count, value=1)


def _review_crawl_record(record: dict) -> None:
    body = _extract_payload(record["body"])
    appid = int(body["appid"])
    count = asyncio.run(_process_reviews(appid))
    metrics.add_metric(name="ReviewsCrawled", unit=MetricUnit.Count, value=count)


# ── Main dispatcher ──────────────────────────────────────────────────────────


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    source_arn = event["Records"][0].get("eventSourceARN", "")
    if "review-crawl" in source_arn:
        return process_partial_response(
            event=event,
            record_handler=_review_crawl_record,
            processor=review_crawl_processor,
            context=context,
        )
    if "app-crawl" in source_arn or "metadata" in source_arn:
        return process_partial_response(
            event=event,
            record_handler=_app_crawl_record,
            processor=app_crawl_processor,
            context=context,
        )
    raise ValueError(f"Unrecognised queue ARN: {source_arn}")


# ── Steam fetch + S3 handoff ─────────────────────────────────────────────────


async def _process_metadata(appid: int) -> bool:
    try:
        details = await _steam.get_app_details(appid)
    except SteamAPIError as exc:
        logger.warning("Steam metadata error appid=%s: %s", appid, exc)
        _notify(appid, task="metadata", s3_key=None, count=0)
        return False

    if not details:
        _notify(appid, task="metadata", s3_key=None, count=0)
        return False

    summary = await _steam.get_review_summary(appid)
    deck_compat = await _steam.get_deck_compatibility(appid)

    payload = {"details": details, "summary": summary, "deck_compat": deck_compat}
    s3_key = _write_s3(f"spoke-results/metadata/{appid}.json.gz", payload)
    _notify(appid, task="metadata", s3_key=s3_key, count=1)
    return True


async def _process_reviews(appid: int) -> int:
    try:
        reviews = await _steam.get_reviews(appid, max_reviews=None)
    except SteamAPIError as exc:
        logger.warning("Steam reviews error appid=%s: %s", appid, exc)
        _notify(appid, task="reviews", s3_key=None, count=0)
        return 0

    if not reviews:
        _notify(appid, task="reviews", s3_key=None, count=0)
        return 0

    s3_key = _write_s3(f"spoke-results/reviews/{appid}.json.gz", reviews)
    _notify(appid, task="reviews", s3_key=s3_key, count=len(reviews))
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


def _notify(appid: int, task: str, s3_key: str | None, count: int) -> None:
    _sqs.send_message(
        QueueUrl=_SPOKE_RESULTS_QUEUE_URL,
        MessageBody=json.dumps({
            "appid": appid,
            "task": task,
            "s3_key": s3_key,
            "count": count,
            "spoke_region": os.environ.get("AWS_REGION", "unknown"),
        }),
    )
