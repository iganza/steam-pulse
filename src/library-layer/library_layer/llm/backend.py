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

from typing import Literal, Protocol

from pydantic import BaseModel

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

    def run(self, requests: list[LLMRequest]) -> list[BaseModel]:
        """Return parsed pydantic responses in the same order as requests."""
        ...
