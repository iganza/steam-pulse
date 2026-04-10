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

Shared helpers (prompts, chunking, merge hierarchy, synthesis user message,
persistence, Python-computed scores) all live in library_layer/analyzer.py
and are invoked identically by both backends.
"""

from library_layer.llm.backend import LLMBackend, LLMRequest
from library_layer.llm.batch import BatchBackend
from library_layer.llm.converse import ConverseBackend

__all__ = ["BatchBackend", "ConverseBackend", "LLMBackend", "LLMRequest"]
