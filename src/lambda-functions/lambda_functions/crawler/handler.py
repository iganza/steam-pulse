"""Lambda handler — crawler control plane + spoke dispatcher.

Event types handled:
  1. EventBridge (scheduled)  — source == "aws.events" → CatalogService.refresh()
  2. Direct boto3 invocation  — "action" key present   → dispatch via Pydantic model
  3. SQS (app-crawl / review-crawl) — dispatch to spoke Lambdas cross-region

DB ingest from spoke results is handled by ingest_handler.py (primary region).
"""

import json
import os
from datetime import UTC, datetime

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
    BackfillTagsRequest,
    CatalogRefreshRequest,
    CrawlAppsRequest,
    CrawlReviewsRequest,
    CrawlTask,
    DirectRequest,
    MetadataSpokeRequest,
    ReviewSpokeRequest,
    TagsSpokeRequest,
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

_conn = get_conn()
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
_steam_api_key: str = _sm.get_secret_value(
    SecretId=_crawler_config.STEAM_API_KEY_SECRET_NAME
)["SecretString"]

_crawl_service = CrawlService(
    game_repo=GameRepository(_conn),
    review_repo=ReviewRepository(_conn),
    catalog_repo=CatalogRepository(_conn),
    tag_repo=TagRepository(_conn),
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
    catalog_repo=CatalogRepository(_conn),
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
# Each spoke region gets a Lambda client + deterministic function name.
# Invoke by name — no ARN construction, no STS call needed.

_spoke_targets: list[tuple[str, object]] = []  # [(fn_name, lambda_client), ...]

for _region in _crawler_config.spoke_region_list:
    _fn_name = f"steampulse-spoke-crawler-{_region}-{_crawler_config.ENVIRONMENT}"
    _client = boto3.client("lambda", region_name=_region)
    _spoke_targets.append((_fn_name, _client))

if not _spoke_targets and os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    raise RuntimeError(
        "SPOKE_REGIONS is empty — at least one spoke region is required. "
        "Set SPOKE_REGIONS in the environment (e.g. 'us-west-2,us-east-1')."
    )


def _extract_payload(record_body: str) -> dict:
    """Unwrap SNS envelope if present, otherwise return plain SQS body."""
    body = json.loads(record_body)
    if "Type" in body and body["Type"] == "Notification":
        return json.loads(body["Message"])
    return body


def _get_backfill_appids(limit: int | None) -> list[int]:
    """Fetch all game appids ordered by review count (most reviewed first)."""
    sql = "SELECT appid FROM games WHERE type = 'game' ORDER BY review_count DESC NULLS LAST"
    if limit:
        sql += f" LIMIT {limit}"
    with _conn.cursor() as cur:
        cur.execute(sql)
        return [row[0] for row in cur.fetchall()]


def _enqueue_tags_backfill(appids: list[int]) -> int:
    """Send tag backfill messages to app-crawl-queue in batches of 10."""
    sent = 0
    for i in range(0, len(appids), 10):
        batch = appids[i : i + 10]
        entries = [
            {
                "Id": str(j),
                "MessageBody": json.dumps({"appid": appid, "task": "tags"}),
            }
            for j, appid in enumerate(batch)
        ]
        resp = _sqs.send_message_batch(QueueUrl=_app_crawl_queue_url, Entries=entries)
        failed = resp.get("Failed", [])
        if failed:
            logger.warning("SQS batch send failed", extra={"failed": len(failed), "offset": i})
        sent += len(batch) - len(failed)
    return sent


def _dispatch_to_spoke(record: dict) -> None:
    """Parse SQS record and invoke the spoke Lambda assigned to this appid."""

    if not _spoke_targets:
        raise RuntimeError("No spoke targets configured — cannot dispatch")

    body = _extract_payload(record["body"])
    appid = int(body["appid"])

    # Task routing: explicit "task" field in body takes priority (used by backfill),
    # otherwise infer from which SQS queue the message came from.
    source_arn = record.get("eventSourceARN", "")
    if "task" in body:
        task: CrawlTask = body["task"]
    elif "review-crawl" in source_arn:
        task = "reviews"
    else:
        task = "metadata"
    logger.append_keys(appid=appid, task=task)

    if task == "tags":
        req: MetadataSpokeRequest | ReviewSpokeRequest | TagsSpokeRequest = TagsSpokeRequest(appid=appid)
    elif task == "reviews":
        # Cursor and target travel in the SQS message body — no DB reads needed.
        # Fresh-start messages (from SNS/game-metadata-ready) have no cursor field; default to "*".
        # Re-queue messages from ingest carry cursor, target, and started_at explicitly.
        # Normalize cursor: treat missing, null, and empty string all as fresh start.
        cursor: str = body.get("cursor") or "*"
        started_at: str | datetime = body.get("started_at") or datetime.now(tz=UTC)

        target_raw: int | None = body.get("target")
        if target_raw is None:
            # Fresh-start or missing target — apply configured default limit.
            target: int = _crawler_config.REVIEW_LIMIT
        elif target_raw <= 0:
            # Remaining budget is zero — nothing left to fetch; skip dispatch.
            logger.info("review crawl budget exhausted — skipping dispatch", extra={"appid": appid})
            return
        else:
            target = target_raw

        if cursor == "*":
            logger.info("reviews fresh start", extra={"appid": appid, "target": target})
        else:
            logger.info("reviews continuing", extra={"appid": appid, "cursor": cursor, "target": target})

        req = ReviewSpokeRequest(
            appid=appid,
            cursor=cursor,
            target=target,
            started_at=started_at,
        )
    else:
        req = MetadataSpokeRequest(appid=appid)

    # Deterministic: same appid always hits the same spoke, spreading load
    # evenly and ensuring retries go to the same region.
    idx = appid % len(_spoke_targets)
    fn_name, client = _spoke_targets[idx]

    logger.info("Dispatching to spoke", extra={"appid": appid, "task": task, "fn_name": fn_name})

    # Async invoke — returns 202 immediately, spoke runs independently.
    # Spoke results flow back via S3 + spoke_results_queue → ingest_handler.
    # Spoke failures: Lambda auto-retries async invocations (2 attempts),
    # then routes to the spoke's DLQ (SpokeCrawlerDlq in CrawlSpokeStack).
    # Spoke also sends success=False on Steam API errors so ingest_handler logs the skip.
    response = client.invoke(
        FunctionName=fn_name,
        InvocationType="Event",
        Payload=req.model_dump_json().encode(),
    )
    status = response["StatusCode"]
    if status != 202:
        raise RuntimeError(
            f"Spoke async invoke failed for appid={appid}: HTTP {status}"
        )

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
        metrics.add_metric(name="CatalogAppsDiscovered", unit=MetricUnit.Count, value=result.get("new_rows", 0))
        metrics.add_metric(name="CatalogAppsEnqueued", unit=MetricUnit.Count, value=result.get("enqueued", 0))
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
                metrics.add_metric(name="GamesUpserted", unit=MetricUnit.Count, value=1 if ok else 0)
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
                metrics.add_metric(name="CatalogAppsDiscovered", unit=MetricUnit.Count, value=result.get("new_rows", 0))
                metrics.add_metric(name="CatalogAppsEnqueued", unit=MetricUnit.Count, value=result.get("enqueued", 0))
                return result
            case BackfillTagsRequest():
                appids = _get_backfill_appids(req.limit)
                logger.info("Backfill tags starting", extra={"count": len(appids), "limit": req.limit})
                sent = _enqueue_tags_backfill(appids)
                metrics.add_metric(name="TagsBackfillDispatched", unit=MetricUnit.Count, value=sent)
                return {"queued": sent}

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
