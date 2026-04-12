"""BatchBackend JSONL drift guard.

Fixed `LLMRequest` input → byte-stable JSONL output. This is the single test
that prevents the batch path from drifting away from the realtime path on
prompt wording — both paths read the same `system` / `user` strings from
analyzer.py, and `BatchBackend._to_jsonl_record` just wraps them.
"""

import json
import re
from unittest.mock import MagicMock

from library_layer.llm.backend import LLMRequest
from library_layer.llm.batch import BatchBackend, _safe_job_name
from library_layer.models.analyzer_models import (
    RichBatchStats,
    RichChunkSummary,
    TopicSignal,
)

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
    assert record["modelInput"]["messages"] == [{"role": "user", "content": "USER MESSAGE"}]
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


def _valid_chunk_summary_json() -> str:
    """A JSON-serialized RichChunkSummary that passes validation."""
    return RichChunkSummary(
        topics=[
            TopicSignal(
                topic="combat",
                category="design_praise",
                sentiment="positive",
                mention_count=1,
                confidence="low",
                summary="good",
            )
        ],
        competitor_refs=[],
        notable_quotes=[],
        batch_stats=RichBatchStats(positive_count=1, negative_count=0),
    ).model_dump_json()


def _batch_backend_with_fake_output(lines: list[str]) -> BatchBackend:
    """Build a real BatchBackend with mock boto clients wired to return
    `lines` as a single .jsonl.out object under the job's output prefix."""
    backend = BatchBackend.__new__(BatchBackend)
    backend._config = MagicMock()  # type: ignore[attr-defined]
    backend._bucket = "test-bucket"  # type: ignore[attr-defined]
    backend._role_arn = "arn:aws:iam::123:role/test"  # type: ignore[attr-defined]
    backend._execution_id = "exec-1"  # type: ignore[attr-defined]

    # Mock Bedrock — get_model_invocation_job returns an output URI.
    backend._bedrock = MagicMock()  # type: ignore[attr-defined]
    backend._bedrock.get_model_invocation_job.return_value = {
        "outputDataConfig": {
            "s3OutputDataConfig": {"s3Uri": "s3://test-bucket/jobs/exec-1/chunk-440/output/"},
        },
    }

    # Mock S3 — paginator returns one .jsonl.out object; get_object returns body.
    body = ("\n".join(lines) + "\n").encode("utf-8")
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "jobs/exec-1/chunk-440/output/0.jsonl.out"}]}
    ]
    backend._s3 = MagicMock()  # type: ignore[attr-defined]
    backend._s3.get_paginator.return_value = paginator
    backend._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=body)),
    }
    return backend


def _good_record(record_id: str) -> str:
    return json.dumps(
        {
            "recordId": record_id,
            "modelOutput": {"content": [{"text": _valid_chunk_summary_json()}]},
        }
    )


def test_collect_skips_malformed_json_line() -> None:
    """A PartiallyCompleted batch job can contain broken lines. Bad JSON
    must be logged and skipped, not crash the whole collect."""
    backend = _batch_backend_with_fake_output(
        [
            "{not valid json at all",
            _good_record("440-chunk-0"),
        ]
    )
    result = backend.collect("arn:job/abc", default_response_model=RichChunkSummary)
    assert len(result.results) == 1
    assert result.results[0][0] == "440-chunk-0"


def test_collect_skips_record_missing_record_id() -> None:
    """A record without `recordId` can't be keyed to a request; drop it."""
    missing_id = json.dumps({"modelOutput": {"content": [{"text": _valid_chunk_summary_json()}]}})
    backend = _batch_backend_with_fake_output([missing_id, _good_record("440-chunk-0")])
    result = backend.collect("arn:job/abc", default_response_model=RichChunkSummary)
    assert len(result.results) == 1
    assert result.results[0][0] == "440-chunk-0"


def test_collect_skips_record_with_empty_content() -> None:
    """A record whose modelOutput.content is empty is dropped."""
    empty = json.dumps({"recordId": "440-chunk-5", "modelOutput": {"content": []}})
    backend = _batch_backend_with_fake_output([empty, _good_record("440-chunk-0")])
    result = backend.collect("arn:job/abc", default_response_model=RichChunkSummary)
    assert len(result.results) == 1
    assert result.results[0][0] == "440-chunk-0"


def test_collect_skips_record_that_fails_pydantic_validation() -> None:
    """A model output whose text can't be parsed as the response_model
    raises ValidationError under normal model_validate_json — the collect
    loop must catch that per-record and keep going."""
    bad_validation = json.dumps(
        {
            "recordId": "440-chunk-1",
            # topics is supposed to be a list, and each TopicSignal needs
            # specific enum values. Pass a plainly-wrong shape.
            "modelOutput": {"content": [{"text": '{"topics": "not a list"}'}]},
        }
    )
    backend = _batch_backend_with_fake_output([bad_validation, _good_record("440-chunk-0")])
    result = backend.collect("arn:job/abc", default_response_model=RichChunkSummary)
    assert len(result.results) == 1
    assert result.results[0][0] == "440-chunk-0"
    assert "440-chunk-1" in result.failed_ids


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
    expected = (
        '{"recordId": "440-synthesis", '
        '"modelInput": {"anthropic_version": "bedrock-2023-05-31", '
        '"max_tokens": 5000, "system": "S", '
        '"messages": [{"role": "user", "content": "U"}]}}'
    )
    assert backend._to_jsonl_record(req) == expected
