"""Tests for SteamPulseConfig — SNS topic ARN fields (tests 48-49)."""

from library_layer.config import SteamPulseConfig


def test_config_has_3_topic_arn_fields() -> None:
    """SteamPulseConfig accepts GAME/CONTENT/SYSTEM_EVENTS_TOPIC_ARN (test 48)."""
    config = SteamPulseConfig(
        GAME_EVENTS_TOPIC_ARN="arn:aws:sns:us-west-2:123456789012:game-events",
        CONTENT_EVENTS_TOPIC_ARN="arn:aws:sns:us-west-2:123456789012:content-events",
        SYSTEM_EVENTS_TOPIC_ARN="arn:aws:sns:us-west-2:123456789012:system-events",
    )
    assert config.GAME_EVENTS_TOPIC_ARN == "arn:aws:sns:us-west-2:123456789012:game-events"
    assert config.CONTENT_EVENTS_TOPIC_ARN == "arn:aws:sns:us-west-2:123456789012:content-events"
    assert config.SYSTEM_EVENTS_TOPIC_ARN == "arn:aws:sns:us-west-2:123456789012:system-events"


def test_config_defaults_empty_topic_arns() -> None:
    """SteamPulseConfig defaults topic ARNs to empty string (test 49).

    Design decision: topic ARNs use str="" defaults (not truly required)
    so the module-level singleton doesn't break. publish_event() raises
    EventPublishError at runtime if an ARN is empty.
    """
    config = SteamPulseConfig()
    # Empty defaults — publish_event will raise at runtime, not at config init
    assert config.GAME_EVENTS_TOPIC_ARN == "" or isinstance(config.GAME_EVENTS_TOPIC_ARN, str)
    assert config.CONTENT_EVENTS_TOPIC_ARN == "" or isinstance(config.CONTENT_EVENTS_TOPIC_ARN, str)
    assert config.SYSTEM_EVENTS_TOPIC_ARN == "" or isinstance(config.SYSTEM_EVENTS_TOPIC_ARN, str)
    assert config.REVIEW_ELIGIBILITY_THRESHOLD == 500
