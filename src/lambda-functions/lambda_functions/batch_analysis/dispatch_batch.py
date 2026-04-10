"""DispatchBatch Lambda — read top-priority candidates and start a fan-out execution.

Reads from mv_analysis_candidates (games needing analysis, ordered by review_count
DESC) and starts the batch orchestrator with the top N appids.

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
"""

import json

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.config import SteamPulseConfig
from library_layer.utils.db import get_conn

logger = Logger(service="batch-dispatch")
tracer = Tracer(service="batch-dispatch")

_config = SteamPulseConfig()
_sfn = boto3.client("stepfunctions")


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
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT appid FROM mv_analysis_candidates ORDER BY review_count DESC LIMIT %s",
            (batch_size,),
        )
        return [row[0] for row in cur.fetchall()]


@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
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
    payload = {"appids": appids, "max_concurrency": 20}
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
