"""CheckBatchStatus Lambda — poll Bedrock batch job status.

Input:  {job_id: str}
Output: {status: "Running"|"Completed"|"Failed", message: str}
"""

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger(service="batch-check-status")
tracer = Tracer(service="batch-check-status")

_bedrock = boto3.client("bedrock")

_STATUS_MAP = {
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


@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    job_id: str = event["job_id"]

    resp = _bedrock.get_model_invocation_job(jobIdentifier=job_id)
    raw_status: str = resp.get("status", "Unknown")
    mapped_status = _STATUS_MAP.get(raw_status, "Running")
    message = resp.get("message", raw_status)

    logger.info("batch job status", extra={"job_id": job_id, "raw": raw_status, "mapped": mapped_status})
    return {"status": mapped_status, "message": message}
