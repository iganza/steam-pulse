"""Tests for SteamPulseConfig."""

import pytest
from library_layer.config import SteamPulseConfig
from pydantic import ValidationError

_ALL_REQUIRED = {
    "DB_SECRET_NAME": "steampulse/test/db-credentials",
    "STEAM_API_KEY_SECRET_NAME": "steampulse/test/steam-api-key",
    "SFN_PARAM_NAME": "/steampulse/test/compute/sfn-arn",
    "STEP_FUNCTIONS_PARAM_NAME": "/steampulse/test/compute/sfn-arn",
    "APP_CRAWL_QUEUE_PARAM_NAME": "/steampulse/test/messaging/app-crawl-queue-url",
    "REVIEW_CRAWL_QUEUE_PARAM_NAME": "/steampulse/test/messaging/review-crawl-queue-url",
    "ASSETS_BUCKET_PARAM_NAME": "/steampulse/test/app/assets-bucket-name",
    "GAME_EVENTS_TOPIC_PARAM_NAME": "/steampulse/test/messaging/game-events-topic-arn",
    "CONTENT_EVENTS_TOPIC_PARAM_NAME": "/steampulse/test/messaging/content-events-topic-arn",
    "SYSTEM_EVENTS_TOPIC_PARAM_NAME": "/steampulse/test/messaging/system-events-topic-arn",
    "LLM_MODEL__CHUNKING": "anthropic.claude-haiku-test-v1:0",
    "LLM_MODEL__SUMMARIZER": "anthropic.claude-sonnet-test-v1:0",
    "LLM_MODEL__GENRE_SYNTHESIS": "anthropic.claude-sonnet-test-v1:0",
}


def test_config_accepts_all_required_fields() -> None:
    """SteamPulseConfig constructs successfully when all required fields are present."""
    config = SteamPulseConfig(**_ALL_REQUIRED)
    assert config.GAME_EVENTS_TOPIC_PARAM_NAME == "/steampulse/test/messaging/game-events-topic-arn"
    assert (
        config.CONTENT_EVENTS_TOPIC_PARAM_NAME
        == "/steampulse/test/messaging/content-events-topic-arn"
    )
    assert (
        config.SYSTEM_EVENTS_TOPIC_PARAM_NAME
        == "/steampulse/test/messaging/system-events-topic-arn"
    )
    assert config.REVIEW_ELIGIBILITY_THRESHOLD == 50


def test_config_raises_when_required_field_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """SteamPulseConfig raises ValidationError if any required ARN is missing."""
    monkeypatch.delenv("DB_SECRET_NAME", raising=False)
    with pytest.raises(ValidationError):
        SteamPulseConfig(**{k: v for k, v in _ALL_REQUIRED.items() if k != "DB_SECRET_NAME"})


def test_model_for_returns_configured_model() -> None:
    """model_for() returns the correct model ID for a known task."""
    config = SteamPulseConfig(**_ALL_REQUIRED)
    assert config.model_for("chunking") == "anthropic.claude-haiku-test-v1:0"
    assert config.model_for("summarizer") == "anthropic.claude-sonnet-test-v1:0"
    assert config.model_for("genre_synthesis") == "anthropic.claude-sonnet-test-v1:0"


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
    monkeypatch.delenv("LLM_MODEL__MERGING", raising=False)
    monkeypatch.delenv("LLM_MODEL__SUMMARIZER", raising=False)
    monkeypatch.delenv("LLM_MODEL__GENRE_SYNTHESIS", raising=False)
    with pytest.raises(ValidationError):
        SteamPulseConfig(
            **{k: v for k, v in _ALL_REQUIRED.items() if not k.startswith("LLM_MODEL")}
        )


def test_to_lambda_env_includes_all_fields() -> None:
    """to_lambda_env() serializes all config fields as flat key=string pairs."""
    config = SteamPulseConfig(**_ALL_REQUIRED)
    env = config.to_lambda_env()
    # Top-level string field
    assert env["DB_SECRET_NAME"] == "steampulse/test/db-credentials"
    # Nested dict flattened with __ delimiter
    assert env["LLM_MODEL__CHUNKING"] == "anthropic.claude-haiku-test-v1:0"
    assert env["LLM_MODEL__SUMMARIZER"] == "anthropic.claude-sonnet-test-v1:0"
    # Int converted to string
    assert env["REVIEW_ELIGIBILITY_THRESHOLD"] == "50"


def test_to_lambda_env_overrides_applied_last() -> None:
    """Overrides passed to to_lambda_env() take precedence over config values."""
    config = SteamPulseConfig(**_ALL_REQUIRED)
    env = config.to_lambda_env(POWERTOOLS_SERVICE_NAME="crawler", ENVIRONMENT="override")
    assert env["POWERTOOLS_SERVICE_NAME"] == "crawler"
    assert env["ENVIRONMENT"] == "override"
