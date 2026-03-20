"""Tests for SteamPulseConfig."""

import pytest
from library_layer.config import SteamPulseConfig
from pydantic import ValidationError

_ALL_REQUIRED = {
    "DB_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:db",
    "SFN_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:crawl",
    "APP_CRAWL_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/app-crawl",
    "REVIEW_CRAWL_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/review-crawl",
    "STEAM_API_KEY_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:steam-key",
    "ASSETS_BUCKET_NAME": "steampulse-assets-test",
    "STEP_FUNCTIONS_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:crawl",
    "GAME_EVENTS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:game-events",
    "CONTENT_EVENTS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:content-events",
    "SYSTEM_EVENTS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:system-events",
    "LLM_MODEL__CHUNKING": "us.anthropic.claude-haiku-test-v1:0",
    "LLM_MODEL__SUMMARIZER": "us.anthropic.claude-sonnet-test-v1:0",
}


def test_config_accepts_all_required_fields() -> None:
    """SteamPulseConfig constructs successfully when all required fields are present."""
    config = SteamPulseConfig(**_ALL_REQUIRED)
    assert config.GAME_EVENTS_TOPIC_ARN == "arn:aws:sns:us-east-1:123456789012:game-events"
    assert config.CONTENT_EVENTS_TOPIC_ARN == "arn:aws:sns:us-east-1:123456789012:content-events"
    assert config.SYSTEM_EVENTS_TOPIC_ARN == "arn:aws:sns:us-east-1:123456789012:system-events"
    assert config.REVIEW_ELIGIBILITY_THRESHOLD == 500


def test_config_raises_when_required_field_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """SteamPulseConfig raises ValidationError if any required ARN is missing."""
    monkeypatch.delenv("DB_SECRET_ARN", raising=False)
    with pytest.raises(ValidationError):
        SteamPulseConfig(**{k: v for k, v in _ALL_REQUIRED.items() if k != "DB_SECRET_ARN"})


def test_model_for_returns_configured_model() -> None:
    """model_for() returns the correct model ID for a known task."""
    config = SteamPulseConfig(**_ALL_REQUIRED)
    assert config.model_for("chunking") == "us.anthropic.claude-haiku-test-v1:0"
    assert config.model_for("summarizer") == "us.anthropic.claude-sonnet-test-v1:0"


def test_model_for_raises_on_unknown_task() -> None:
    """model_for() raises ValueError with a helpful message for unknown tasks."""
    config = SteamPulseConfig(**_ALL_REQUIRED)
    with pytest.raises(ValueError, match="No model configured for task 'chat'"):
        config.model_for("chat")


def test_model_for_same_model_both_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both tasks can be set to the same model ID (e.g. for quality testing)."""
    monkeypatch.setenv("LLM_MODEL__CHUNKING", "sonnet-model-id")
    monkeypatch.setenv("LLM_MODEL__SUMMARIZER", "sonnet-model-id")
    config = SteamPulseConfig(**_ALL_REQUIRED)
    assert config.model_for("chunking") == config.model_for("summarizer") == "sonnet-model-id"


def test_config_raises_when_llm_model_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """SteamPulseConfig raises ValidationError if LLM_MODEL map is absent entirely."""
    monkeypatch.delenv("LLM_MODEL__CHUNKING", raising=False)
    monkeypatch.delenv("LLM_MODEL__SUMMARIZER", raising=False)
    with pytest.raises(ValidationError):
        SteamPulseConfig(**{k: v for k, v in _ALL_REQUIRED.items()
                            if not k.startswith("LLM_MODEL")})
