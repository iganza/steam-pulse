"""SQS batch send helper."""

import json
import logging

logger = logging.getLogger(__name__)

_BATCH_SIZE = 10


def send_sqs_batch(client: object, queue_url: str, messages: list[dict]) -> None:
    """Send messages to SQS in batches of 10.

    Args:
        client: A boto3 SQS client.
        queue_url: The SQS queue URL.
        messages: List of message dicts, each with an "appid" key (or arbitrary data).
                  Each dict is JSON-serialised as the message body.

    Raises:
        RuntimeError: If any batch has failed messages.
    """
    for i in range(0, len(messages), _BATCH_SIZE):
        batch = messages[i : i + _BATCH_SIZE]
        entries = [
            {"Id": str(idx), "MessageBody": json.dumps(msg)} for idx, msg in enumerate(batch)
        ]
        resp = client.send_message_batch(QueueUrl=queue_url, Entries=entries)  # type: ignore[union-attr]
        if resp.get("Failed"):
            failed_ids = [f["Id"] for f in resp["Failed"]]
            raise RuntimeError(f"SQS batch had {len(failed_ids)} failed messages: {failed_ids}")
    logger.debug("Sent %d messages to %s", len(messages), queue_url)
