"""LLM backend abstraction for the three-phase analyzer.

Two distinct seams — don't force batch into a sync shape:

- ConverseBackend.run(requests) -> list[BaseModel]
    Synchronous. Used by the realtime path. Calls instructor+Bedrock
    Converse in a thread pool for chunk fan-out. Honours prompt caching
    (cache_control: ephemeral) on the system prompt.

- BatchBackend (no run()): prepare(), submit(), status(), collect()
    Explicit async lifecycle. Step Functions drives the prepare/submit →
    poll → collect sequence across multiple Lambda invocations. "Job still
    pending" is Step Functions state (Wait/Choice), NEVER an exception.

Each seam has a Bedrock variant (default) and an Anthropic direct API
variant. Use the factory functions ``make_converse_backend`` /
``make_batch_backend`` to get the right class based on config.LLM_BACKEND.

Shared helpers (prompts, chunking, merge hierarchy, synthesis user message,
persistence, Python-computed scores) all live in library_layer/analyzer.py
and are invoked identically by both backends.
"""

from library_layer.config import SteamPulseConfig
from library_layer.llm.anthropic_batch import AnthropicBatchBackend
from library_layer.llm.anthropic_converse import AnthropicConverseBackend
from library_layer.llm.backend import LLMBackend, LLMRequest
from library_layer.llm.batch import BatchBackend
from library_layer.llm.converse import ConverseBackend


def make_converse_backend(
    config: SteamPulseConfig,
    *,
    max_workers: int,
    max_retries: int,
) -> ConverseBackend:
    """Return the right realtime backend based on config.LLM_BACKEND."""
    if config.LLM_BACKEND == "anthropic":
        return AnthropicConverseBackend(
            config,
            max_workers=max_workers,
            max_retries=max_retries,
            api_key=config.ANTHROPIC_API_KEY,
        )
    return ConverseBackend(config, max_workers=max_workers, max_retries=max_retries)


def make_batch_backend(
    config: SteamPulseConfig,
    *,
    execution_id: str,
    batch_bucket_name: str = "",
    batch_role_arn: str = "",
) -> BatchBackend | AnthropicBatchBackend:
    """Return the right batch backend based on config.LLM_BACKEND.

    ``batch_bucket_name`` and ``batch_role_arn`` are only required when
    ``LLM_BACKEND=bedrock``. They default to empty strings so that
    Anthropic-mode callers can omit them.
    """
    if config.LLM_BACKEND == "anthropic":
        return AnthropicBatchBackend(
            config,
            api_key=config.ANTHROPIC_API_KEY,
            execution_id=execution_id,
        )
    return BatchBackend(
        config,
        batch_bucket_name=batch_bucket_name,
        batch_role_arn=batch_role_arn,
        execution_id=execution_id,
    )


__all__ = [
    "AnthropicBatchBackend",
    "AnthropicConverseBackend",
    "BatchBackend",
    "ConverseBackend",
    "LLMBackend",
    "LLMRequest",
    "make_batch_backend",
    "make_converse_backend",
]
