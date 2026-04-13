"""AnthropicBatchBackend — Anthropic Message Batches API.

Drop-in replacement for BatchBackend that uses the direct Anthropic
Messages Batches API instead of Bedrock Batch Inference + S3. Same
four-method lifecycle (prepare/submit/status/collect), same caller
contract, no S3 or IAM role required.
"""

from typing import Literal

import anthropic
from aws_lambda_powertools import Logger
from library_layer.config import SteamPulseConfig
from library_layer.llm.backend import BatchCollectResult, LLMRequest, LLMTask
from library_layer.llm.batch import BatchStatus
from pydantic import BaseModel, ValidationError

logger = Logger()


class AnthropicBatchBackend:
    """Anthropic Message Batches API driver — explicit lifecycle, no run()."""

    mode: Literal["realtime", "batch"] = "batch"

    def __init__(
        self,
        config: SteamPulseConfig,
        *,
        api_key: str,
        execution_id: str,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required for AnthropicBatchBackend")
        self._config = config
        self._client = anthropic.Anthropic(api_key=api_key)
        self._execution_id = execution_id

    # ------------------------------------------------------------------
    # Phase 1: prepare request dicts (no S3 needed)
    # ------------------------------------------------------------------
    def prepare(self, requests: list[LLMRequest], *, phase: str) -> list[dict]:
        """Build the in-memory request list for the Anthropic batch API.

        Returns a list of dicts ready to pass to ``submit()``. No S3 upload —
        the Anthropic batch API accepts the full request array inline.
        """
        if not requests:
            raise ValueError("AnthropicBatchBackend.prepare called with no requests")
        prepared = []
        for req in requests:
            params: dict[str, object] = {
                "model": self._config.model_for(req.task),
                "max_tokens": req.max_tokens,
                "system": [
                    {
                        "type": "text",
                        "text": req.system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "messages": [{"role": "user", "content": req.user}],
            }
            if req.temperature is not None:
                params["temperature"] = req.temperature
            prepared.append({"custom_id": req.record_id, "params": params})
        logger.info(
            "batch_prepare",
            extra={"phase": phase, "records": len(prepared), "execution_id": self._execution_id},
        )
        return prepared

    # ------------------------------------------------------------------
    # Phase 2: submit the batch
    # ------------------------------------------------------------------
    def submit(self, prepared: list[dict], task: LLMTask, *, phase: str) -> str:
        """Create an Anthropic message batch. Returns the batch ID."""
        batch = self._client.messages.batches.create(requests=prepared)
        logger.info(
            "batch_submit",
            extra={
                "phase": phase,
                "batch_id": batch.id,
                "model": self._config.model_for(task),
                "execution_id": self._execution_id,
            },
        )
        return batch.id

    # ------------------------------------------------------------------
    # Phase 3: poll status
    # ------------------------------------------------------------------
    def status(self, batch_id: str) -> BatchStatus:
        """Map Anthropic batch processing_status to our three-state enum."""
        batch = self._client.messages.batches.retrieve(batch_id)
        match batch.processing_status:
            case "in_progress":
                return "running"
            case "ended":
                return "completed"
            case "canceling" | "canceled" | "expired":
                logger.warning(
                    "batch_job_terminal",
                    extra={"batch_id": batch_id, "status": batch.processing_status},
                )
                return "failed"
            case _:
                logger.warning(
                    "batch_job_unknown_status",
                    extra={"batch_id": batch_id, "status": batch.processing_status},
                )
                return "failed"

    # ------------------------------------------------------------------
    # Phase 4: collect parsed responses
    # ------------------------------------------------------------------
    def collect(
        self,
        batch_id: str,
        response_models: dict[str, type[BaseModel]] | None = None,
        *,
        default_response_model: type[BaseModel] | None = None,
    ) -> BatchCollectResult:
        """Iterate batch results and return structured results.

        Same error-tolerance pattern as ``BatchBackend.collect``: skip
        errored/expired entries with a warning log, never crash the whole
        collection on a single bad record.
        """
        response_models = response_models or {}
        results: list[tuple[str, BaseModel]] = []
        failed_ids: list[str] = []
        skipped = 0
        total_input = 0
        total_output = 0
        total_cache_read = 0
        total_cache_write = 0

        for entry in self._client.messages.batches.results(batch_id):
            record_id = entry.custom_id

            if entry.result.type == "errored":
                error = entry.result.error
                logger.warning(
                    "batch_record_errored",
                    extra={
                        "record_id": record_id,
                        "batch_id": batch_id,
                        "error_type": getattr(error, "type", "unknown"),
                        "error_message": getattr(error, "message", ""),
                    },
                )
                failed_ids.append(record_id)
                skipped += 1
                continue

            if entry.result.type != "succeeded":
                logger.warning(
                    "batch_record_terminal",
                    extra={
                        "record_id": record_id,
                        "batch_id": batch_id,
                        "result_type": entry.result.type,
                    },
                )
                failed_ids.append(record_id)
                skipped += 1
                continue

            message = entry.result.message
            usage = getattr(message, "usage", None)
            if usage:
                total_input += getattr(usage, "input_tokens", 0)
                total_output += getattr(usage, "output_tokens", 0)
                total_cache_read += getattr(usage, "cache_read_input_tokens", 0)
                total_cache_write += getattr(usage, "cache_creation_input_tokens", 0)

            content = message.content
            if not content:
                logger.warning(
                    "batch_record_no_content",
                    extra={"record_id": record_id, "batch_id": batch_id},
                )
                failed_ids.append(record_id)
                skipped += 1
                continue

            response_cls = response_models.get(record_id) or default_response_model
            if response_cls is None:
                logger.warning(
                    "batch_record_unknown",
                    extra={"record_id": record_id, "batch_id": batch_id},
                )
                failed_ids.append(record_id)
                skipped += 1
                continue

            # Anthropic batch results use tool_use blocks for structured output
            # (same shape instructor would produce). The `input` field on a
            # ToolUseBlock is already a dict — use model_validate, not
            # model_validate_json.
            block = content[0]
            try:
                if block.type == "tool_use":
                    parsed_obj = response_cls.model_validate(block.input)
                else:
                    # Fallback for text blocks — parse the JSON string.
                    # Strip markdown code fences if the model wrapped the
                    # JSON in ```json ... ``` instead of returning raw JSON.
                    text = block.text.strip()
                    if text.startswith("```"):
                        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                        if text.endswith("```"):
                            text = text[:-3].strip()
                    parsed_obj = response_cls.model_validate_json(text)
            except (ValidationError, AttributeError) as exc:
                logger.warning(
                    "batch_record_validation_error",
                    extra={
                        "record_id": record_id,
                        "batch_id": batch_id,
                        "error": str(exc),
                    },
                )
                failed_ids.append(record_id)
                skipped += 1
                continue

            results.append((record_id, parsed_obj))

        logger.info(
            "batch_collect",
            extra={
                "batch_id": batch_id,
                "records": len(results),
                "skipped": skipped,
                "failed_ids_count": len(failed_ids),
                "failed_ids_sample": failed_ids[:10],
                "input_tokens": total_input,
                "output_tokens": total_output,
                "cache_read_tokens": total_cache_read,
                "cache_write_tokens": total_cache_write,
            },
        )
        return BatchCollectResult(
            results=results,
            failed_ids=failed_ids,
            skipped=skipped,
            input_tokens=total_input,
            output_tokens=total_output,
            cache_read_tokens=total_cache_read,
            cache_write_tokens=total_cache_write,
        )
