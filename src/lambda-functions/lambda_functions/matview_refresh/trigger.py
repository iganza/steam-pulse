"""Trigger Lambda — SQS shell that starts a matview-refresh SFN execution."""

import hashlib
import json
import os

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger(service="matview-refresh-trigger")

_sfn = boto3.client("stepfunctions")
_ssm = boto3.client("ssm")

_cached_arn = ""


def _get_state_machine_arn() -> str:
    global _cached_arn
    if _cached_arn:
        return _cached_arn
    param_name = os.environ["MATVIEW_REFRESH_SFN_ARN_PARAM_NAME"]
    _cached_arn = _ssm.get_parameter(Name=param_name)["Parameter"]["Value"]
    return _cached_arn


def _execution_name(event: dict) -> str:
    """Derive a deterministic SFN execution name from the SQS batch (idempotent on retry)."""
    ids = [r.get("messageId", "") for r in event.get("Records", []) if isinstance(r, dict)]
    if ids and all(ids):
        # Sort — SQS/Lambda doesn't guarantee record order across retries.
        key = ",".join(sorted(ids))
    else:
        key = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
    return f"sqs-{hashlib.sha256(key.encode()).hexdigest()[:32]}"


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict:
    execution_name = _execution_name(event)

    try:
        resp = _sfn.start_execution(
            stateMachineArn=_get_state_machine_arn(),
            name=execution_name,
            input="{}",
        )
        execution_arn = resp["executionArn"]
    except _sfn.exceptions.ExecutionAlreadyExists:
        # Lambda retry after a successful StartExecution — same execution_name, so no-op.
        logger.info(
            "SFN execution already exists for this SQS batch — retry no-op",
            extra={"execution_name": execution_name},
        )
        return {"execution_name": execution_name, "duplicate": True}

    logger.info(
        "Started matview-refresh SFN execution",
        extra={"execution_arn": execution_arn},
    )
    return {"execution_arn": execution_arn}
