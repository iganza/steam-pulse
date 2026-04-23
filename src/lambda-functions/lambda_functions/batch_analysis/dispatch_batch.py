"""DispatchBatch Lambda — dispatch analysis batches and publish completion events.

Two modes, selected by ``action`` in the event payload:

**Default (no action)** — read top-priority candidates and start a fan-out execution.

    Input (all optional):
        {
            "batch_size": 100,     # override default from config
            "dry_run": true        # return candidates without starting
        }

    Output:
        {
            "dispatched": 100,
            "execution_arn": "arn:aws:states:...",  # omitted on dry_run
            "appids": [440, 730, ...]
        }

**action="post_batch"** — publish BatchAnalysisCompleteEvent after orchestrator fan-out.

    Input (from Step Functions):
        {
            "action": "post_batch",
            "execution_id": "<sfn execution name>",
            "appids_count": 100
        }

    Output:
        {"status": "published", "execution_id": "..."}
"""

import json

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.analyzer import MIN_CHUNKS_FOR_MERGE
from library_layer.config import SteamPulseConfig
from library_layer.events import BatchAnalysisCompleteEvent
from library_layer.utils.db import get_conn
from library_layer.utils.events import publish_event

logger = Logger(service="batch-dispatch")
tracer = Tracer(service="batch-dispatch")

_config = SteamPulseConfig()
_sfn = boto3.client("stepfunctions")
_sns = boto3.client("sns")
# Sized to fit the Lambda's 60s timeout with 3 retry attempts:
# worst-case connect chain = 15 + backoff + 15 + backoff + 15 ≈ 49s.
_BATCH_CONNECT_TIMEOUT = 15
# Filter dispatch to appids with enough reviews to clear MIN_CHUNKS_FOR_MERGE
# at the default chunk size. mv_analysis_candidates itself keeps its ≥200
# review floor (used by other consumers); this narrows the batch path only.
_MIN_REVIEW_COUNT_FOR_BATCH = MIN_CHUNKS_FOR_MERGE * _config.ANALYSIS_CHUNK_SIZE


def _get_orchestrator_arn() -> str:
    ssm = boto3.client("ssm")
    return ssm.get_parameter(
        Name=f"/steampulse/{_config.ENVIRONMENT}/batch/orchestrator-sfn-arn"
    )["Parameter"]["Value"]


def _normalize_batch_size(raw: object, *, default: int) -> int:
    if raw is None or isinstance(raw, bool):
        return default
    try:
        size = int(raw)
    except (TypeError, ValueError):
        return default
    if size <= 0:
        return default
    return size


def _fetch_candidates(*, batch_size: int) -> list[int]:
    conn = get_conn(connect_timeout=_BATCH_CONNECT_TIMEOUT, max_connect_attempts=3)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT appid FROM mv_analysis_candidates "
            "WHERE review_count >= %s "
            "ORDER BY review_count DESC LIMIT %s",
            (_MIN_REVIEW_COUNT_FOR_BATCH, batch_size),
        )
        return [row["appid"] for row in cur.fetchall()]


def _handle_dispatch(event: dict) -> dict:
    """Read top-priority candidates and start a fan-out execution."""
    batch_size = _normalize_batch_size(
        event.get("batch_size"), default=_config.BATCH_DISPATCH_SIZE
    )
    dry_run = event.get("dry_run", False)

    appids = _fetch_candidates(batch_size=batch_size)
    logger.info(
        "Fetched analysis candidates",
        extra={"count": len(appids), "batch_size": batch_size, "dry_run": dry_run},
    )

    if not appids:
        logger.info("No candidates — matview is empty or fully analyzed")
        return {"dispatched": 0, "appids": []}

    if dry_run:
        return {"dispatched": len(appids), "appids": appids, "dry_run": True}

    orchestrator_arn = _get_orchestrator_arn()
    payload = {"appids": appids, "max_concurrency": 20, "start_at": "chunk"}
    resp = _sfn.start_execution(
        stateMachineArn=orchestrator_arn,
        input=json.dumps(payload),
    )
    execution_arn = resp["executionArn"]

    logger.info(
        "Started orchestrator execution",
        extra={"execution_arn": execution_arn, "game_count": len(appids)},
    )

    return {
        "dispatched": len(appids),
        "execution_arn": execution_arn,
        "appids": appids,
    }


def _get_system_events_topic_arn() -> str:
    ssm = boto3.client("ssm")
    return ssm.get_parameter(
        Name=_config.SYSTEM_EVENTS_TOPIC_PARAM_NAME
    )["Parameter"]["Value"]


def _handle_post_batch(event: dict) -> dict:
    """Publish BatchAnalysisCompleteEvent after all games in a batch complete.

    appids_count comes from a Pass state before the DistributedMap (which
    discards per-item results to stay under the 256KB state limit).
    """
    execution_id: str = event["execution_id"]
    appids_count: int = event.get("appids_count", 0)
    topic_arn = _get_system_events_topic_arn()

    evt = BatchAnalysisCompleteEvent(
        execution_id=execution_id,
        appids_total=appids_count,
    )

    publish_event(_sns, topic_arn, evt)

    logger.info(
        "Published batch-analysis-complete",
        extra={"execution_id": execution_id, "appids_count": appids_count},
    )

    return {"status": "published", "execution_id": execution_id}


@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    match event.get("action"):
        case "post_batch":
            return _handle_post_batch(event)
        case _:
            return _handle_dispatch(event)
