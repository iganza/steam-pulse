"""Unit tests for AnthropicBatchBackend — prepare() and collect().

Verifies prompt caching annotations on prepared requests and structured
error handling (errored/expired/validation failure) in collect results.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from library_layer.llm.anthropic_batch import AnthropicBatchBackend
from library_layer.llm.backend import LLMRequest
from pydantic import BaseModel


class _StubModel(BaseModel):
    value: str


def _make_backend() -> AnthropicBatchBackend:
    config = MagicMock()
    config.model_for.return_value = "claude-haiku-4-5-20251001"
    with patch("library_layer.llm.anthropic_batch.anthropic"):
        backend = AnthropicBatchBackend(config, api_key="test-key", execution_id="exec-1")
    return backend


def _make_request(record_id: str = "440-chunk-0") -> LLMRequest:
    return LLMRequest(
        record_id=record_id,
        task="chunking",
        system="You are a game analyst.",
        user="Analyze these reviews.",
        max_tokens=4096,
        response_model=_StubModel,
    )


# ---------------------------------------------------------------------------
# prepare()
# ---------------------------------------------------------------------------


def test_prepare_includes_cache_control_on_system_block() -> None:
    backend = _make_backend()
    prepared = backend.prepare([_make_request()], phase="chunk-440")
    assert len(prepared) == 1
    system_block = prepared[0]["params"]["system"][0]
    assert system_block["cache_control"] == {"type": "ephemeral"}
    assert system_block["type"] == "text"
    assert system_block["text"] == "You are a game analyst."


def test_prepare_includes_temperature_when_set() -> None:
    backend = _make_backend()
    req = _make_request()
    req.temperature = 0.5
    prepared = backend.prepare([req], phase="chunk-440")
    assert prepared[0]["params"]["temperature"] == 0.5


def test_prepare_omits_temperature_when_none() -> None:
    backend = _make_backend()
    prepared = backend.prepare([_make_request()], phase="chunk-440")
    assert "temperature" not in prepared[0]["params"]


def test_prepare_sets_custom_id_from_record_id() -> None:
    backend = _make_backend()
    prepared = backend.prepare([_make_request("my-id-123")], phase="chunk-440")
    assert prepared[0]["custom_id"] == "my-id-123"


def test_prepare_includes_tools_and_tool_choice_from_response_model() -> None:
    backend = _make_backend()
    prepared = backend.prepare([_make_request()], phase="chunk-440")
    params = prepared[0]["params"]
    assert len(params["tools"]) == 1
    tool = params["tools"][0]
    assert tool["name"] == "_StubModel"
    assert "properties" in tool["input_schema"]
    assert "value" in tool["input_schema"]["properties"]
    assert params["tool_choice"] == {"type": "tool", "name": "_StubModel"}


# ---------------------------------------------------------------------------
# collect()
# ---------------------------------------------------------------------------


def _succeeded_entry(record_id: str, value: str) -> SimpleNamespace:
    """Simulate a text-block response (legacy/fallback path)."""
    return SimpleNamespace(
        custom_id=record_id,
        result=SimpleNamespace(
            type="succeeded",
            message=SimpleNamespace(
                content=[SimpleNamespace(type="text", text=f'{{"value": "{value}"}}')],
                usage=SimpleNamespace(
                    input_tokens=100,
                    output_tokens=50,
                    cache_read_input_tokens=80,
                    cache_creation_input_tokens=20,
                ),
            ),
        ),
    )


def _tool_use_entry(record_id: str, value: str) -> SimpleNamespace:
    """Simulate a tool_use block response (expected path with tools/tool_choice)."""
    return SimpleNamespace(
        custom_id=record_id,
        result=SimpleNamespace(
            type="succeeded",
            message=SimpleNamespace(
                content=[SimpleNamespace(type="tool_use", id="tool_1", name="_StubModel", input={"value": value})],
                usage=SimpleNamespace(
                    input_tokens=100,
                    output_tokens=50,
                    cache_read_input_tokens=80,
                    cache_creation_input_tokens=20,
                ),
            ),
        ),
    )


def _errored_entry(record_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        custom_id=record_id,
        result=SimpleNamespace(
            type="errored",
            error=SimpleNamespace(type="invalid_request_error", message="bad input"),
        ),
    )


def _expired_entry(record_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        custom_id=record_id,
        result=SimpleNamespace(type="expired"),
    )


def test_collect_returns_succeeded_results() -> None:
    backend = _make_backend()
    backend._client.messages.batches.results.return_value = [
        _succeeded_entry("r1", "hello"),
    ]
    result = backend.collect("batch-1", default_response_model=_StubModel)
    assert len(result.results) == 1
    assert result.results[0][0] == "r1"
    assert result.results[0][1].value == "hello"
    assert result.failed_ids == []
    assert result.skipped == 0
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.cache_read_tokens == 80
    assert result.cache_write_tokens == 20


def test_collect_parses_tool_use_blocks() -> None:
    backend = _make_backend()
    backend._client.messages.batches.results.return_value = [
        _tool_use_entry("r1", "hello"),
    ]
    result = backend.collect("batch-1", default_response_model=_StubModel)
    assert len(result.results) == 1
    assert result.results[0][0] == "r1"
    assert result.results[0][1].value == "hello"
    assert result.failed_ids == []
    assert result.skipped == 0


def test_collect_tracks_errored_records_in_failed_ids() -> None:
    backend = _make_backend()
    backend._client.messages.batches.results.return_value = [
        _errored_entry("bad-1"),
        _succeeded_entry("good-1", "ok"),
    ]
    result = backend.collect("batch-2", default_response_model=_StubModel)
    assert len(result.results) == 1
    assert result.results[0][0] == "good-1"
    assert "bad-1" in result.failed_ids
    assert result.skipped == 1


def test_collect_tracks_expired_records_in_failed_ids() -> None:
    backend = _make_backend()
    backend._client.messages.batches.results.return_value = [
        _expired_entry("exp-1"),
        _succeeded_entry("good-1", "ok"),
    ]
    result = backend.collect("batch-3", default_response_model=_StubModel)
    assert len(result.results) == 1
    assert "exp-1" in result.failed_ids
    assert result.skipped == 1


def test_collect_tracks_validation_failures_in_failed_ids() -> None:
    backend = _make_backend()
    backend._client.messages.batches.results.return_value = [
        SimpleNamespace(
            custom_id="bad-json",
            result=SimpleNamespace(
                type="succeeded",
                message=SimpleNamespace(
                    content=[SimpleNamespace(type="text", text="not valid json")],
                ),
            ),
        ),
        _succeeded_entry("good-1", "ok"),
    ]
    result = backend.collect("batch-4", default_response_model=_StubModel)
    assert len(result.results) == 1
    assert "bad-json" in result.failed_ids
    assert result.skipped == 1
