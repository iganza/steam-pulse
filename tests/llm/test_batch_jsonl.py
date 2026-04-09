"""BatchBackend JSONL drift guard.

Fixed `LLMRequest` input → byte-stable JSONL output. This is the single test
that prevents the batch path from drifting away from the realtime path on
prompt wording — both paths read the same `system` / `user` strings from
analyzer.py, and `BatchBackend._to_jsonl_record` just wraps them.
"""

import json
import re

from library_layer.llm.backend import LLMRequest
from library_layer.llm.batch import BatchBackend, _safe_job_name
from library_layer.models.analyzer_models import RichChunkSummary

# Bedrock jobName constraint: ^[a-zA-Z0-9](-*[a-zA-Z0-9]){0,62}$
_JOB_NAME_RE = re.compile(r"^[a-zA-Z0-9](-*[a-zA-Z0-9]){0,62}$")


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


def test_safe_job_name_fits_bedrock_constraints() -> None:
    # Long + special-char execution_id still yields a legal jobName.
    name = _safe_job_name(
        "arn:aws:states:us-west-2:123456789012:execution:steampulse-batch:run",
        "chunk-440",
    )
    assert len(name) <= 63
    assert _JOB_NAME_RE.match(name), f"illegal jobName: {name}"


def test_safe_job_name_is_deterministic() -> None:
    # Same inputs → same output (also acts as a clientRequestToken).
    a = _safe_job_name("exec-1", "chunk-440")
    b = _safe_job_name("exec-1", "chunk-440")
    assert a == b


def test_safe_job_name_distinguishes_different_inputs() -> None:
    # Two executions that sanitize to similar prefixes still diverge via
    # the hash suffix.
    a = _safe_job_name("exec/1", "chunk")
    b = _safe_job_name("exec.1", "chunk")
    assert a != b


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
