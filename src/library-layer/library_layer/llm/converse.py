"""ConverseBackend — synchronous Bedrock Converse via instructor.

Used by the realtime path. Fans out multiple requests in a small thread
pool so chunk Phase 1 runs concurrently over warm HTTPS connections.
psycopg2 / instructor / boto3 are all sync, so there is no asyncio here.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal

import anthropic
import instructor
from aws_lambda_powertools import Logger
from library_layer.config import SteamPulseConfig
from library_layer.llm.backend import LLMRequest, LLMResultCallback, LLMUsage
from pydantic import BaseModel

logger = Logger()


class ConverseBackend:
    """Instructor + AnthropicBedrock wrapped behind the LLMBackend protocol.

    `max_workers` is a REQUIRED constructor argument — no default. Callers
    must pass `SteamPulseConfig.ANALYSIS_CONVERSE_MAX_WORKERS` (or an
    override) so the fan-out bound is visible at the call site, not
    buried as a module-level constant.
    """

    mode: Literal["realtime", "batch"] = "realtime"

    def __init__(
        self,
        config: SteamPulseConfig,
        *,
        max_workers: int,
        max_retries: int,
    ) -> None:
        if max_workers <= 0:
            raise ValueError(f"max_workers must be positive, got {max_workers}")
        if max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {max_retries}")
        self._config = config
        self._max_workers = max_workers
        # `max_retries` is instructor's in-band repair loop. Set to 0
        # when the caller owns an idempotent outer retry (e.g.
        # `scripts/dev/run_phase.py` re-runs via the chunk_hash cache)
        # — instructor's Bedrock retry path has a long-standing bug
        # where it round-trips the failed assistant tool_use block with
        # `caller=None` and the Anthropic Bedrock API 400s on it.
        self._max_retries = max_retries
        self._client = instructor.from_anthropic(anthropic.AnthropicBedrock())

    def run(
        self,
        requests: list[LLMRequest],
        *,
        on_result: LLMResultCallback | None = None,
    ) -> list[BaseModel]:
        if not requests:
            return []
        if len(requests) == 1:
            result, usage = self._execute_one(requests[0])
            if on_result is not None:
                on_result(0, result, usage)
            return [result]

        # Thread pool for chunk fan-out. Order is preserved via index map.
        # We iterate with `as_completed` so that a single failing request
        # interrupts the whole run instead of blocking on an earlier slow
        # future — and we immediately cancel any futures that haven't
        # started yet so we stop paying LLM cost on a known-bad run.
        # When `on_result` is supplied we invoke it here, inside the
        # as_completed loop, so callers can stream-persist each result
        # as it arrives rather than waiting for the whole batch.
        results: list[BaseModel | None] = [None] * len(requests)
        with ThreadPoolExecutor(max_workers=min(self._max_workers, len(requests))) as pool:
            future_to_idx = {
                pool.submit(self._execute_one, req): i for i, req in enumerate(requests)
            }
            try:
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    try:
                        result, usage = future.result()
                    except Exception as exc:
                        logger.error(
                            "llm_call_failed",
                            extra={
                                "record_id": requests[idx].record_id,
                                "task": requests[idx].task,
                                "error": str(exc),
                            },
                        )
                        raise
                    results[idx] = result
                    if on_result is not None:
                        # Callback exceptions also propagate and cancel
                        # pending work — callers that raise here are
                        # signalling "abort the phase, you've got enough
                        # partial progress persisted already".
                        on_result(idx, result, usage)
            except Exception:
                # Cancel anything not yet started so we stop spending on
                # a run we already know is going to fail.
                for pending in future_to_idx:
                    pending.cancel()
                raise
        # `LLMBackend.run()`'s contract is one response per request in the
        # same order as input. If a slot is still None here, something
        # silently dropped a response — fail loudly with the offending
        # indexes instead of returning a shorter list and corrupting
        # downstream indexing.
        missing = [i for i, r in enumerate(results) if r is None]
        if missing:
            raise RuntimeError(
                f"ConverseBackend.run() produced no result for request "
                f"indexes {missing} (record_ids: "
                f"{[requests[i].record_id for i in missing]})"
            )
        return results  # type: ignore[return-value]

    def _execute_one(self, request: LLMRequest) -> tuple[BaseModel, LLMUsage]:
        model_id = self._config.model_for(request.task)
        logger.info(
            "llm_call",
            extra={
                "record_id": request.record_id,
                "task": request.task,
                "model": model_id,
            },
        )
        t0 = time.monotonic()
        response, completion = self._client.messages.create_with_completion(
            model=model_id,
            max_tokens=request.max_tokens,
            response_model=request.response_model,
            max_retries=self._max_retries,
            system=[
                {
                    "type": "text",
                    "text": request.system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": request.user}],
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        u = completion.usage
        usage = LLMUsage(
            input_tokens=int(u.input_tokens or 0),
            output_tokens=int(u.output_tokens or 0),
            cache_read_tokens=int(getattr(u, "cache_read_input_tokens", 0) or 0),
            cache_write_tokens=int(getattr(u, "cache_creation_input_tokens", 0) or 0),
            latency_ms=latency_ms,
        )
        return response, usage
