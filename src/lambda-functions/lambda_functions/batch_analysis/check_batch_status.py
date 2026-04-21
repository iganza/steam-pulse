"""CheckBatchStatus Lambda — poll batch job status.

Supports both Bedrock Batch Inference and Anthropic Message Batches,
selected by the LLM_BACKEND config flag.

Input:  {job_id: str}
Output: {status: "Running"|"Completed"|"Failed", message: str}
"""

import anthropic
import boto3
import psycopg2.extensions
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.config import SteamPulseConfig
from library_layer.llm import resolve_anthropic_api_key
from library_layer.repositories.batch_execution_repo import BatchExecutionRepository
from library_layer.utils.db import get_conn, transaction

logger = Logger(service="batch-check-status")
tracer = Tracer(service="batch-check-status")

_config = SteamPulseConfig()
_BATCH_CONNECT_TIMEOUT = 60  # cold-start burst tolerance


def _get_batch_conn() -> psycopg2.extensions.connection:
    return get_conn(connect_timeout=_BATCH_CONNECT_TIMEOUT, max_connect_attempts=3)


_batch_exec_repo = BatchExecutionRepository(_get_batch_conn)

# Module-level clients — reused across warm Lambda invocations.
_bedrock_client = boto3.client("bedrock") if _config.LLM_BACKEND != "anthropic" else None
_anthropic_client: anthropic.Anthropic | None = (
    anthropic.Anthropic(api_key=resolve_anthropic_api_key(_config))
    if _config.LLM_BACKEND == "anthropic"
    else None
)

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
    if _bedrock_client is None:
        raise RuntimeError("Bedrock client not initialized — LLM_BACKEND is 'anthropic'")
    resp = _bedrock_client.get_model_invocation_job(jobIdentifier=job_id)
    raw_status: str = resp.get("status", "Unknown")
    mapped_status = _BEDROCK_STATUS_MAP.get(raw_status, "Failed")
    message = resp.get("message", raw_status)
    return {"status": mapped_status, "message": message, "raw": raw_status}


def _check_anthropic(job_id: str) -> dict:
    if _anthropic_client is None:
        raise RuntimeError("Anthropic client not initialized — LLM_BACKEND is not 'anthropic'")
    batch = _anthropic_client.messages.batches.retrieve(job_id)
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

    # Update tracking table on status transitions. Best-effort — must not
    # fail the polling loop if Postgres is unavailable.
    try:
        if result["status"] == "Running":
            with transaction(_get_batch_conn()):
                _batch_exec_repo.mark_running(job_id)
        elif result["status"] == "Failed":
            with transaction(_get_batch_conn()):
                _batch_exec_repo.mark_failed(
                    job_id, failure_reason=result["message"] or result["raw"] or "unknown"
                )
    except Exception:
        logger.exception(
            "batch_execution_tracking_update_failed",
            extra={"job_id": job_id, "raw": result["raw"], "mapped": result["status"]},
        )

    return {"status": result["status"], "message": result["message"]}
