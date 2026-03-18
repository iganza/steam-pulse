"""Tests for SNS publish helper (tests 17-22 from spec)."""

import json
import logging
from unittest.mock import MagicMock

import pytest

from library_layer.events import GameDiscoveredEvent
from library_layer.utils.events import EventPublishError, publish_event

TOPIC_ARN = "arn:aws:sns:us-west-2:000000000000:test-game-events"


def _mock_sns(message_id: str = "msg-123") -> MagicMock:
    client = MagicMock()
    client.publish.return_value = {"MessageId": message_id}
    return client


# 17. publish_event calls SNS with correct TopicArn and Message
def test_publish_event_calls_sns() -> None:
    sns = _mock_sns()
    event = GameDiscoveredEvent(appid=440)
    publish_event(sns, TOPIC_ARN, event)

    sns.publish.assert_called_once()
    call_kwargs = sns.publish.call_args.kwargs
    assert call_kwargs["TopicArn"] == TOPIC_ARN
    body = json.loads(call_kwargs["Message"])
    assert body["appid"] == 440
    assert body["event_type"] == "game-discovered"


# 18. event_type always in MessageAttributes
def test_publish_event_includes_event_type_attribute() -> None:
    sns = _mock_sns()
    event = GameDiscoveredEvent(appid=440)
    publish_event(sns, TOPIC_ARN, event)

    attrs = sns.publish.call_args.kwargs["MessageAttributes"]
    assert "event_type" in attrs
    assert attrs["event_type"]["StringValue"] == "game-discovered"
    assert attrs["event_type"]["DataType"] == "String"


# 19. extra_attributes merged alongside event_type
def test_publish_event_with_extra_attributes() -> None:
    sns = _mock_sns()
    event = GameDiscoveredEvent(appid=440)
    publish_event(sns, TOPIC_ARN, event, extra_attributes={"is_eligible": "true"})

    attrs = sns.publish.call_args.kwargs["MessageAttributes"]
    assert "event_type" in attrs
    assert "is_eligible" in attrs
    assert attrs["is_eligible"]["StringValue"] == "true"


# 20. Message is valid JSON matching the model
def test_publish_event_serializes_pydantic() -> None:
    sns = _mock_sns()
    event = GameDiscoveredEvent(appid=440)
    publish_event(sns, TOPIC_ARN, event)

    raw = sns.publish.call_args.kwargs["Message"]
    data = json.loads(raw)
    restored = GameDiscoveredEvent.model_validate(data)
    assert restored == event


# 21. SNS client error → EventPublishError
def test_publish_event_raises_on_sns_error() -> None:
    sns = MagicMock()
    sns.publish.side_effect = Exception("SNS is down")
    event = GameDiscoveredEvent(appid=440)

    with pytest.raises(EventPublishError, match="Failed to publish"):
        publish_event(sns, TOPIC_ARN, event)


# 22. INFO-level log on success
def test_publish_event_logs_success(caplog: pytest.LogCaptureFixture) -> None:
    sns = _mock_sns(message_id="abc-123")
    event = GameDiscoveredEvent(appid=440)

    with caplog.at_level(logging.INFO, logger="library_layer.utils.events"):
        publish_event(sns, TOPIC_ARN, event)

    assert any("game-discovered" in msg and "abc-123" in msg for msg in caplog.messages)


# Extra: empty topic_arn raises EventPublishError
def test_publish_event_raises_on_empty_arn() -> None:
    sns = _mock_sns()
    event = GameDiscoveredEvent(appid=440)

    with pytest.raises(EventPublishError, match="topic_arn is empty"):
        publish_event(sns, "", event)
