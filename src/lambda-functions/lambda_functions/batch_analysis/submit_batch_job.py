"""SubmitBatchJob Lambda — create a Bedrock batch inference job.

Input:  {execution_id: str, pass: str, model_id: str, input_s3_uri: str, output_s3_uri: str}
Output: {job_id: str}  — job_id is the full Bedrock job ARN
"""

import hashlib
import os

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger(service="batch-submit-job")
tracer = Tracer(service="batch-submit-job")

_bedrock = boto3.client("bedrock")
_BATCH_ROLE_ARN = os.environ["BEDROCK_BATCH_ROLE_ARN"]


@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    execution_id: str = event["execution_id"]
    pass_name: str = event["pass"]  # "pass1" or "pass2"
    model_id: str = event["model_id"]
    input_s3_uri: str = event["input_s3_uri"]
    output_s3_uri: str = event["output_s3_uri"]

    # Job name: max 63 chars, alphanumeric + hyphens. Hash the full execution_id for uniqueness.
    uid = hashlib.sha256(f"{execution_id}-{pass_name}".encode()).hexdigest()[:12]
    job_name = f"sp-{pass_name}-{uid}"

    logger.info(
        "submitting batch job",
        extra={
            "pass": pass_name,
            "model_id": model_id,
            "input_s3_uri": input_s3_uri,
            "job_name": job_name,
        },
    )

    resp = _bedrock.create_model_invocation_job(
        jobName=job_name,
        roleArn=_BATCH_ROLE_ARN,
        clientRequestToken=f"{execution_id}-{pass_name}",
        modelId=model_id,
        inputDataConfig={"s3InputDataConfig": {"s3Uri": input_s3_uri}},
        outputDataConfig={"s3OutputDataConfig": {"s3Uri": output_s3_uri}},
    )

    job_id: str = resp["jobArn"]
    logger.info("batch job submitted", extra={"job_id": job_id})
    return {"job_id": job_id}
