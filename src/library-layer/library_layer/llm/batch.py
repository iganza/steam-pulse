"""BatchBackend — explicit prepare/submit/status/collect lifecycle.

Bedrock Batch Inference is asynchronous and can take hours to complete.
The honest way to drive it from Lambda is across multiple invocations via
Step Functions state, not by blocking or tunnelling "job pending" through
Python exceptions. This backend therefore does NOT implement
`LLMBackend.run()`. It exposes four primitives:

    prepare(requests) -> s3_uri         # writes JSONL to S3
    submit(s3_uri, task) -> job_id      # creates the Bedrock invocation job
    status(job_id) -> "running"|"completed"|"failed"
    collect(job_id, response_models) -> list[BaseModel]

The Step Functions state machine composes these across separate Lambda
invocations and owns the Wait/Choice polling loop. The ONLY place the
JSONL wire format lives is this file.
"""

import hashlib
import json
import re
from typing import Literal
from urllib.parse import urlparse

import boto3
from aws_lambda_powertools import Logger
from library_layer.config import SteamPulseConfig
from library_layer.llm.backend import LLMRequest, LLMTask
from pydantic import BaseModel

logger = Logger()


BatchStatus = Literal["running", "completed", "failed"]

# Bedrock's jobName allows [a-zA-Z0-9] plus single '-' separators, total
# length <=63 chars. Our execution_ids can be anything (Step Functions
# execution names include ':' and other special chars), so we sanitize
# and hash-truncate to guarantee a legal, deterministic name.
_JOB_NAME_MAX = 63
_JOB_NAME_INVALID = re.compile(r"[^a-zA-Z0-9]+")


def _safe_job_name(execution_id: str, phase: str) -> str:
    """Deterministic, Bedrock-legal jobName from execution_id + phase.

    Always includes an 8-char hash suffix of the raw inputs so that two
    executions whose sanitized prefixes happen to collide still map to
    distinct job names. Deterministic inputs always produce the same
    output — this also serves as a `clientRequestToken` for idempotency.
    """
    raw = f"sp-{execution_id}-{phase}"
    sanitized = _JOB_NAME_INVALID.sub("-", raw).strip("-") or "sp"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    # Reserve room for "-{digest}" (9 chars) plus leave a little headroom.
    prefix_budget = _JOB_NAME_MAX - len(digest) - 1
    prefix = sanitized[:prefix_budget].rstrip("-") or "sp"
    return f"{prefix}-{digest}"


class BatchBackend:
    """Bedrock Batch Inference driver — explicit lifecycle, no run()."""

    mode: Literal["realtime", "batch"] = "batch"

    def __init__(
        self,
        config: SteamPulseConfig,
        *,
        batch_bucket_name: str,
        batch_role_arn: str,
        execution_id: str,
        s3_client: object | None = None,
        bedrock_client: object | None = None,
    ) -> None:
        self._config = config
        self._bucket = batch_bucket_name
        self._role_arn = batch_role_arn
        self._execution_id = execution_id
        self._s3 = s3_client or boto3.client("s3")
        self._bedrock = bedrock_client or boto3.client("bedrock")

    # ------------------------------------------------------------------
    # Phase 1: prepare JSONL and upload to S3
    # ------------------------------------------------------------------
    def prepare(self, requests: list[LLMRequest], *, phase: str) -> str:
        """Write JSONL for a batch of requests. Returns the input S3 URI.

        `phase` is a label like "chunk", "merge_l1", "synthesis" used to
        segment S3 keys so multiple jobs for the same execution don't
        collide.
        """
        if not requests:
            raise ValueError("BatchBackend.prepare called with no requests")
        key = f"jobs/{self._execution_id}/{phase}/input.jsonl"
        body = "\n".join(self._to_jsonl_record(r) for r in requests) + "\n"
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/jsonl",
        )
        uri = f"s3://{self._bucket}/{key}"
        logger.info("batch_prepare", extra={"phase": phase, "records": len(requests), "uri": uri})
        return uri

    def _to_jsonl_record(self, request: LLMRequest) -> str:
        """Serialize an LLMRequest as a Bedrock Batch Inference JSONL line.

        NOTE: No `cache_control` in batch JSONL — prompt caching is a
        Converse-only feature.
        """
        record = {
            "recordId": request.record_id,
            "modelInput": {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": request.max_tokens,
                "system": request.system,
                "messages": [{"role": "user", "content": request.user}],
            },
        }
        return json.dumps(record, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Phase 2: submit the Bedrock job
    # ------------------------------------------------------------------
    def submit(self, input_s3_uri: str, task: LLMTask, *, phase: str) -> str:
        """Create a Bedrock model invocation job. Returns the jobArn.

        `jobName` is deterministically derived from `execution_id` + `phase`
        and hash-truncated to fit Bedrock's 63-character /
        `[a-zA-Z0-9](-*[a-zA-Z0-9]){0,62}` constraint. The same
        deterministic value is passed as `clientRequestToken` so retries
        from Step Functions are idempotent — Bedrock will return the
        existing job instead of creating a duplicate.
        """
        output_s3_uri = f"s3://{self._bucket}/jobs/{self._execution_id}/{phase}/output/"
        model_id = self._config.model_for(task)
        job_name = _safe_job_name(self._execution_id, phase)
        resp = self._bedrock.create_model_invocation_job(
            jobName=job_name,
            clientRequestToken=job_name,
            roleArn=self._role_arn,
            modelId=model_id,
            inputDataConfig={
                "s3InputDataConfig": {
                    "s3InputFormat": "JSONL",
                    "s3Uri": input_s3_uri,
                }
            },
            outputDataConfig={
                "s3OutputDataConfig": {
                    "s3Uri": output_s3_uri,
                }
            },
        )
        job_id = resp["jobArn"]
        logger.info(
            "batch_submit",
            extra={"phase": phase, "job_id": job_id, "model": model_id, "job_name": job_name},
        )
        return job_id

    # ------------------------------------------------------------------
    # Phase 3: poll status (Step Functions calls this, not us)
    # ------------------------------------------------------------------
    def status(self, job_id: str) -> BatchStatus:
        resp = self._bedrock.get_model_invocation_job(jobIdentifier=job_id)
        raw = resp.get("status", "")
        if raw in ("Submitted", "InProgress", "Stopping"):
            return "running"
        if raw == "Completed":
            return "completed"
        # Failed, Stopped, anything unexpected → treat as failed and log.
        logger.warning("batch_job_terminal", extra={"job_id": job_id, "raw_status": raw})
        return "failed"

    # ------------------------------------------------------------------
    # Phase 4: collect parsed responses
    # ------------------------------------------------------------------
    def collect(
        self,
        job_id: str,
        response_models: dict[str, type[BaseModel]] | None = None,
        *,
        default_response_model: type[BaseModel] | None = None,
    ) -> list[tuple[str, BaseModel]]:
        """Read a completed job's output JSONL and return (record_id, parsed).

        `response_models` maps `record_id` → the pydantic class to validate
        against, for jobs that mix multiple schemas. Most phases in this
        pipeline submit records of a single schema — pass
        `default_response_model=MyModel` to apply it to every returned
        record without building a per-record map.
        """
        response_models = response_models or {}
        resp = self._bedrock.get_model_invocation_job(jobIdentifier=job_id)
        output_uri = resp["outputDataConfig"]["s3OutputDataConfig"]["s3Uri"]
        parsed = urlparse(output_uri)
        bucket = parsed.netloc
        prefix = parsed.path.lstrip("/")

        # List objects under the output prefix — Bedrock writes one .out file per input.
        listed = self._s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        results: list[tuple[str, BaseModel]] = []
        for obj in listed.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".jsonl.out"):
                continue
            body = self._s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
            for line in body.splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                record_id = record.get("recordId")
                model_output = record.get("modelOutput", {})
                content = model_output.get("content") or []
                if not content:
                    logger.warning("batch_record_no_content", extra={"record_id": record_id})
                    continue
                text = content[0].get("text", "")
                response_cls = response_models.get(record_id) or default_response_model
                if response_cls is None:
                    logger.warning(
                        "batch_record_unknown",
                        extra={"record_id": record_id, "job_id": job_id},
                    )
                    continue
                parsed_obj = response_cls.model_validate_json(text)
                results.append((record_id, parsed_obj))
        logger.info(
            "batch_collect",
            extra={"job_id": job_id, "records": len(results)},
        )
        return results
