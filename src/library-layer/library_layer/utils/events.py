"""SNS publish helper for SteamPulse domain events."""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from library_layer.events import BaseEvent

logger = logging.getLogger(__name__)


class EventPublishError(Exception):
    """Raised when event publishing fails."""


def publish_event(
    sns_client: object,
    topic_arn: str,
    event: "BaseEvent",
    extra_attributes: dict[str, str] | None = None,
) -> str:
    """Publish a BaseEvent to an SNS topic.

    - topic_arn is REQUIRED (not optional). If missing, it's a deployment bug —
      SteamPulseConfig validation catches this at cold start.
    - event_type is automatically added as a MessageAttribute for SNS filtering.
    - extra_attributes (e.g. is_eligible) are merged into MessageAttributes.
    - Raises EventPublishError on SNS client errors for visibility.
    """
    if not topic_arn:
        raise EventPublishError(f"Cannot publish {event.event_type}: topic_arn is empty")

    attributes: dict[str, dict[str, str]] = {
        "event_type": {"DataType": "String", "StringValue": event.event_type},
    }
    if extra_attributes:
        for k, v in extra_attributes.items():
            attributes[k] = {"DataType": "String", "StringValue": v}

    try:
        response = sns_client.publish(  # type: ignore[union-attr]
            TopicArn=topic_arn,
            Message=event.model_dump_json(),
            MessageAttributes=attributes,
        )
        logger.info(
            "Published %s to %s (MessageId: %s)",
            event.event_type,
            topic_arn.split(":")[-1],
            response["MessageId"],
        )
        return response["MessageId"]
    except EventPublishError:
        raise
    except Exception as exc:
        logger.error("Failed to publish %s: %s", event.event_type, exc)
        raise EventPublishError(f"Failed to publish {event.event_type} to {topic_arn}") from exc
