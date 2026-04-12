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

import boto3
from aws_lambda_powertools import Logger
from library_layer.config import SteamPulseConfig
from library_layer.llm.anthropic_batch import AnthropicBatchBackend
from library_layer.llm.anthropic_converse import AnthropicConverseBackend
from library_layer.llm.backend import (
    BatchCollectResult,
    LLMBackend,
    LLMRequest,
    estimate_batch_cost_usd,
)
from library_layer.llm.batch import BatchBackend
from library_layer.llm.converse import ConverseBackend

logger = Logger()

# Module-level cache so repeated factory calls (e.g. warm Lambda invocations)
# don't hit Secrets Manager on every call.
resolved_api_key: str = ""


def resolve_anthropic_api_key(config: SteamPulseConfig) -> str:
    """Return the Anthropic API key, resolving from Secrets Manager if needed.

    Resolution order:
    1. If ``ANTHROPIC_API_KEY`` is set directly (local dev), use it.
    2. If ``ANTHROPIC_API_KEY_SECRET_NAME`` is set, fetch from Secrets Manager.
    3. Fail loudly if neither is available.
    """
    global resolved_api_key
    if resolved_api_key:
        return resolved_api_key

    if config.ANTHROPIC_API_KEY:
        resolved_api_key = config.ANTHROPIC_API_KEY
        return resolved_api_key

    if config.ANTHROPIC_API_KEY_SECRET_NAME:
        sm = boto3.client("secretsmanager")
        resolved_api_key = sm.get_secret_value(
            SecretId=config.ANTHROPIC_API_KEY_SECRET_NAME
        )["SecretString"]
        logger.info(
            "anthropic_api_key_resolved",
            extra={"secret_name": config.ANTHROPIC_API_KEY_SECRET_NAME},
        )
        return resolved_api_key

    raise ValueError(
        "LLM_BACKEND=anthropic but no API key available. "
        "Set ANTHROPIC_API_KEY (local dev) or ANTHROPIC_API_KEY_SECRET_NAME (Lambda)."
    )


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
            api_key=resolve_anthropic_api_key(config),
        )
    return ConverseBackend(config, max_workers=max_workers, max_retries=max_retries)


def make_batch_backend(
    config: SteamPulseConfig,
    *,
    execution_id: str,
    batch_bucket_name: str,
    batch_role_arn: str,
) -> BatchBackend | AnthropicBatchBackend:
    """Return the right batch backend based on config.LLM_BACKEND."""
    if config.LLM_BACKEND == "anthropic":
        return AnthropicBatchBackend(
            config,
            api_key=resolve_anthropic_api_key(config),
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
    "BatchCollectResult",
    "ConverseBackend",
    "LLMBackend",
    "LLMRequest",
    "estimate_batch_cost_usd",
    "make_batch_backend",
    "make_converse_backend",
    "resolve_anthropic_api_key",
]
