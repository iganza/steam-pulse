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


# Non-force event types that propagate as `trigger_event`. `batch-analysis-complete`
# is handled separately below because it also escalates force=True.
_NON_FORCE_EVENT_TYPES = frozenset({"report-ready", "catalog-refresh-complete"})


def _classify(event: dict) -> tuple[bool, str]:
    """Inspect SQS records and return (force, trigger_event).

    `batch-analysis-complete` wins over other events in a mixed batch and
    escalates force=True. Other recognised events propagate as `trigger_event`
    with force=False. Unknown or malformed batches return (False, "").
    """
    trigger_event = ""
    for record in event.get("Records", []):
        try:
            body = json.loads(record.get("body", "{}"))
            message = body.get("Message", body)
            if isinstance(message, str):
                message = json.loads(message)
            if not isinstance(message, dict):
                continue
            event_type = message.get("event_type", "")
            if event_type == "batch-analysis-complete":
                return True, "batch-analysis-complete"
            if not trigger_event and event_type in _NON_FORCE_EVENT_TYPES:
                trigger_event = event_type
        except (json.JSONDecodeError, TypeError, AttributeError):
            logger.warning(
                "Skipping malformed refresh event record",
                extra={
                    "messageId": record.get("messageId") if isinstance(record, dict) else None
                },
            )
            continue
    return False, trigger_event


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
    force, trigger_event = _classify(event)
    execution_name = _execution_name(event)

    try:
        resp = _sfn.start_execution(
            stateMachineArn=_get_state_machine_arn(),
            name=execution_name,
            input=json.dumps({"force": force, "trigger_event": trigger_event}),
        )
        execution_arn = resp["executionArn"]
    except _sfn.exceptions.ExecutionAlreadyExists:
        # Lambda retry after a successful StartExecution — same execution_name, so no-op.
        logger.info(
            "SFN execution already exists for this SQS batch — retry no-op",
            extra={
                "execution_name": execution_name,
                "force": force,
                "trigger_event": trigger_event,
            },
        )
        return {
            "execution_name": execution_name,
            "force": force,
            "trigger_event": trigger_event,
            "duplicate": True,
        }

    logger.info(
        "Started matview-refresh SFN execution",
        extra={
            "execution_arn": execution_arn,
            "force": force,
            "trigger_event": trigger_event,
        },
    )
    return {
        "execution_arn": execution_arn,
        "force": force,
        "trigger_event": trigger_event,
    }
