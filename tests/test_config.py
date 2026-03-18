"""Tests for SteamPulseConfig."""

import pytest
from pydantic import ValidationError

from library_layer.config import SteamPulseConfig

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
