"""ConverseBackend — synchronous Bedrock Converse via instructor.

Used by the realtime path. Fans out multiple requests in a small thread
pool so chunk Phase 1 runs concurrently over warm HTTPS connections.
psycopg2 / instructor / boto3 are all sync, so there is no asyncio here.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Literal

import anthropic
import instructor
from aws_lambda_powertools import Logger
from library_layer.config import SteamPulseConfig
from library_layer.llm.backend import LLMRequest
from pydantic import BaseModel

logger = Logger()

# Conservative default — Bedrock per-account concurrency is the real cap,
# and chunk phase already spans many reviews per call. Overridable via
# env var if we ever want to tune.
_DEFAULT_MAX_WORKERS = 8


class ConverseBackend:
    """Instructor + AnthropicBedrock wrapped behind the LLMBackend protocol."""

    mode: Literal["realtime", "batch"] = "realtime"

    def __init__(
        self,
        config: SteamPulseConfig,
        *,
        max_workers: int = _DEFAULT_MAX_WORKERS,
    ) -> None:
        self._config = config
        self._max_workers = max_workers
        self._client = instructor.from_anthropic(anthropic.AnthropicBedrock())

    def run(self, requests: list[LLMRequest]) -> list[BaseModel]:
        if not requests:
            return []
        if len(requests) == 1:
            return [self._execute_one(requests[0])]

        # Thread pool for chunk fan-out. Order is preserved via index map.
        results: list[BaseModel | None] = [None] * len(requests)
        with ThreadPoolExecutor(max_workers=min(self._max_workers, len(requests))) as pool:
            future_to_idx = {
                pool.submit(self._execute_one, req): i for i, req in enumerate(requests)
            }
            for future in future_to_idx:
                idx = future_to_idx[future]
                results[idx] = future.result()
        return [r for r in results if r is not None]

    def _execute_one(self, request: LLMRequest) -> BaseModel:
        model_id = self._config.model_for(request.task)
        logger.info(
            "llm_call",
            extra={
                "record_id": request.record_id,
                "task": request.task,
                "model": model_id,
            },
        )
        response, _ = self._client.messages.create_with_completion(
            model=model_id,
            max_tokens=request.max_tokens,
            response_model=request.response_model,
            max_retries=2,
            system=[
                {
                    "type": "text",
                    "text": request.system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": request.user}],
        )
        return response
