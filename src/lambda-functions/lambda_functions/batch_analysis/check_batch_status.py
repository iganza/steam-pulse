"""CheckBatchStatus Lambda — poll batch job status.

Supports both Bedrock Batch Inference and Anthropic Message Batches,
selected by the LLM_BACKEND config flag.

Input:  {job_id: str}
Output: {status: "Running"|"Completed"|"Failed", message: str}
"""

import anthropic
import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.config import SteamPulseConfig
from library_layer.llm import resolve_anthropic_api_key

logger = Logger(service="batch-check-status")
tracer = Tracer(service="batch-check-status")

_config = SteamPulseConfig()

# ── Bedrock path ─────────────────────────────────────────────────────────────
_BEDROCK_STATUS_MAP = {
    "Submitted": "Running",
    "InProgress": "Running",
    "Stopping": "Running",
    "Completed": "Completed",
    "Failed": "Failed",
    "Stopped": "Failed",
    "PartiallyCompleted": "Completed",
    "Expired": "Failed",
    "Validating": "Running",
    "Scheduled": "Running",
}

# ── Anthropic path ───────────────────────────────────────────────────────────
_ANTHROPIC_STATUS_MAP = {
    "in_progress": "Running",
    "ended": "Completed",
    "canceling": "Failed",
    "canceled": "Failed",
    "expired": "Failed",
}


def _check_bedrock(job_id: str) -> dict:
    bedrock = boto3.client("bedrock")
    resp = bedrock.get_model_invocation_job(jobIdentifier=job_id)
    raw_status: str = resp.get("status", "Unknown")
    mapped_status = _BEDROCK_STATUS_MAP.get(raw_status, "Failed")
    message = resp.get("message", raw_status)
    return {"status": mapped_status, "message": message, "raw": raw_status}


def _check_anthropic(job_id: str) -> dict:
    client = anthropic.Anthropic(api_key=resolve_anthropic_api_key(_config))
    batch = client.messages.batches.retrieve(job_id)
    raw_status = batch.processing_status
    mapped_status = _ANTHROPIC_STATUS_MAP.get(raw_status, "Failed")
    return {"status": mapped_status, "message": raw_status, "raw": raw_status}


@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    job_id: str = event["job_id"]

    if _config.LLM_BACKEND == "anthropic":
        result = _check_anthropic(job_id)
    else:
        result = _check_bedrock(job_id)

    logger.info(
        "batch job status",
        extra={"job_id": job_id, "raw": result["raw"], "mapped": result["status"]},
    )
    return {"status": result["status"], "message": result["message"]}
