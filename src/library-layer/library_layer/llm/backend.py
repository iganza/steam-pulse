"""LLMBackend protocol + LLMRequest model — one seam, two implementations.

The seam between the three-phase analyzer and the actual Bedrock call. All
backend-agnostic logic (prompts, chunking, merge, synthesis, scoring, and
persistence) lives above this interface in analyzer.py.

Only `ConverseBackend` implements `run()`. `BatchBackend` intentionally does
NOT — it exposes prepare/submit/status/collect instead. Forcing batch behind
a single `run()` shape would either block a Lambda for hours or require
control-flow-by-exception to signal "job still pending", both of which are
anti-patterns. Step Functions owns the pending state for batch via its
native Wait/Choice loop.
"""

from collections.abc import Callable
from typing import Literal, Protocol

from pydantic import BaseModel

# Streaming-result callback. Called from inside `ConverseBackend.run()` as
# each per-request future completes — gives callers a hook to persist
# incrementally instead of waiting for the whole fan-out to finish. Args
# are (request_index, parsed_response). Raising from the callback
# propagates up and cancels the remaining work.
LLMResultCallback = Callable[[int, BaseModel], None]

LLMTask = Literal["chunking", "merging", "summarizer"]


class LLMRequest(BaseModel):
    """A typed LLM call — system + user + response schema.

    `task` is used by backends to route to the correct model ID via
    `config.model_for(task)`. `record_id` is a stable identifier used by
    the batch path as the JSONL `recordId`; the realtime path echoes it
    through logs for traceability.
    """

    record_id: str
    task: LLMTask
    system: str
    user: str
    max_tokens: int
    response_model: type[BaseModel]

    model_config = {"arbitrary_types_allowed": True}


class LLMBackend(Protocol):
    """Synchronous backend contract.

    ConverseBackend implements this directly. BatchBackend does NOT — it
    exposes prepare/submit/status/collect instead, because Bedrock Batch
    Inference is inherently asynchronous and the honest way to drive it
    from Lambda is across multiple invocations via Step Functions state.
    """

    mode: Literal["realtime", "batch"]

    def run(
        self,
        requests: list[LLMRequest],
        *,
        on_result: LLMResultCallback | None = None,
    ) -> list[BaseModel]:
        """Return parsed pydantic responses in the same order as requests.

        When `on_result` is supplied, it's invoked for every successful
        response as soon as that response arrives — before the rest of
        the fan-out has finished. Use this to stream persistence and
        make long-running phases crash-tolerant: if request N fails,
        requests 0..N-1 have already been persisted.
        """
        ...
