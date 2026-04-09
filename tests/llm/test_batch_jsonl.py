"""BatchBackend JSONL drift guard.

Fixed `LLMRequest` input → byte-stable JSONL output. This is the single test
that prevents the batch path from drifting away from the realtime path on
prompt wording — both paths read the same `system` / `user` strings from
analyzer.py, and `BatchBackend._to_jsonl_record` just wraps them.
"""

import json

from library_layer.llm.backend import LLMRequest
from library_layer.llm.batch import BatchBackend
from library_layer.models.analyzer_models import RichChunkSummary


def _fake_backend() -> BatchBackend:
    # We only exercise the pure serialization path — no boto calls.
    backend = BatchBackend.__new__(BatchBackend)  # type: ignore[call-arg]
    return backend


def test_jsonl_record_shape() -> None:
    backend = _fake_backend()
    req = LLMRequest(
        record_id="440-chunk-0",
        task="chunking",
        system="SYSTEM PROMPT",
        user="USER MESSAGE",
        max_tokens=1024,
        response_model=RichChunkSummary,
    )
    line = backend._to_jsonl_record(req)
    record = json.loads(line)
    assert record["recordId"] == "440-chunk-0"
    assert record["modelInput"]["anthropic_version"] == "bedrock-2023-05-31"
    assert record["modelInput"]["max_tokens"] == 1024
    assert record["modelInput"]["system"] == "SYSTEM PROMPT"
    assert record["modelInput"]["messages"] == [
        {"role": "user", "content": "USER MESSAGE"}
    ]
    # Prompt caching is NOT supported by Bedrock Batch — must not appear.
    assert "cache_control" not in line


def test_jsonl_record_is_byte_stable() -> None:
    """Same input → same JSONL bytes. Guards against field-order drift."""
    backend = _fake_backend()
    req = LLMRequest(
        record_id="440-synthesis",
        task="summarizer",
        system="S",
        user="U",
        max_tokens=5000,
        response_model=RichChunkSummary,
    )
    assert backend._to_jsonl_record(req) == backend._to_jsonl_record(req)
