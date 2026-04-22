"""Trigger Lambda — SQS shell that starts a matview refresh SFN execution.

Bridges the `cache_invalidation_queue` SQS event source to the Step
Functions state machine. Preserves the force-refresh detection rule
(SNS messages with `event_type == "batch-analysis-complete"` bypass
debounce). Not VPC-attached — no DB access, only calls sfn:StartExecution.

Debounce happens inside the Start step, not here, so the Lambda stays
idempotent and the state machine has the single source of truth.
"""

import json
import os
import uuid

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


def _is_force_refresh(event: dict) -> bool:
    """Check if any SQS record contains a batch-analysis-complete event."""
    for record in event.get("Records", []):
        try:
            body = json.loads(record.get("body", "{}"))
            message = body.get("Message", body)
            if isinstance(message, str):
                message = json.loads(message)
            if (
                isinstance(message, dict)
                and message.get("event_type") == "batch-analysis-complete"
            ):
                return True
        except (json.JSONDecodeError, TypeError, AttributeError):
            logger.warning(
                "Skipping malformed refresh event record",
                extra={
                    "messageId": record.get("messageId") if isinstance(record, dict) else None
                },
            )
            continue
    return False


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict:
    force = _is_force_refresh(event)
    execution_name = f"sqs-{uuid.uuid4().hex[:16]}"

    resp = _sfn.start_execution(
        stateMachineArn=_get_state_machine_arn(),
        name=execution_name,
        input=json.dumps({"force": force}),
    )
    logger.info(
        "Started matview-refresh SFN execution",
        extra={"execution_arn": resp["executionArn"], "force": force},
    )
    return {"execution_arn": resp["executionArn"], "force": force}
