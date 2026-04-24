"""Trigger Lambda — SQS shell that starts a matview-refresh SFN execution."""

import os
from datetime import datetime, timezone

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


def _execution_name() -> str:
    # Date-based name — duplicate publishes same UTC day collide on ExecutionAlreadyExists (SFN reserves names 90d).
    return f"daily-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict:
    execution_name = _execution_name()

    try:
        resp = _sfn.start_execution(
            stateMachineArn=_get_state_machine_arn(),
            name=execution_name,
            input="{}",
        )
        execution_arn = resp["executionArn"]
    except _sfn.exceptions.ExecutionAlreadyExists:
        logger.info(
            "Matview refresh already ran (or is running) for this UTC day — no-op",
            extra={"execution_name": execution_name},
        )
        return {"execution_name": execution_name, "duplicate": True}

    logger.info(
        "Started matview-refresh SFN execution",
        extra={"execution_arn": execution_arn},
    )
    return {"execution_arn": execution_arn}
