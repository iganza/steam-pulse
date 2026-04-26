"""Email Lambda — SQS-triggered handler for transactional emails.

Processes messages from the email queue. Each message is a typed
BaseSqsMessage (defined in library_layer.events). Unknown message types
are logged and dropped — they do not raise, so they are not retried.

DLQ policy: any exception raised here causes the message to be retried
up to the configured maxReceiveCount before landing on the DLQ.
"""

import json

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.parameters import get_parameter
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.config import SteamPulseConfig
from library_layer.events import WaitlistConfirmationMessage
from library_layer.utils.email import ResendEmailSender

logger = Logger(service="email")

_config = SteamPulseConfig()
_resend_api_key: str = get_parameter(  # type: ignore[assignment]
    _config.RESEND_API_KEY_PARAM_NAME, decrypt=True
)
_sender = ResendEmailSender(_resend_api_key)

_FROM_ADDR = "hello@steampulse.io"


def _handle_waitlist_confirmation(email: str) -> None:
    _sender.send(
        to=email,
        subject="You're on the SteamPulse waitlist",
        html=(
            "<p>Thanks for your interest in SteamPulse Pro!</p>"
            "<p>We'll let you know as soon as early access opens.</p>"
            "<hr><p><small>SteamPulse &mdash; steampulse.io</small></p>"
        ),
        from_addr=_FROM_ADDR,
    )
    logger.info("Waitlist confirmation sent", extra={"email": email})


@logger.inject_lambda_context(clear_state=True)
def handler(event: dict, context: LambdaContext) -> dict:
    """Process SQS email queue records with partial-batch failure reporting.

    Returns a batchItemFailures structure so that only records that raise
    exceptions are retried. Unknown message types are dropped without retry.
    """
    batch_item_failures: list[dict[str, str]] = []

    for record in event.get("Records", []):
        try:
            body_raw = json.loads(record["body"])
            msg_type = body_raw.get("message_type", "")

            match msg_type:
                case "waitlist_confirmation":
                    msg = WaitlistConfirmationMessage.model_validate(body_raw)
                    _handle_waitlist_confirmation(msg.email)
                case _:
                    logger.warning(
                        "Unknown SQS message type — dropping",
                        extra={"message_type": msg_type},
                    )
        except Exception:
            logger.exception(
                "Failed to process SQS record",
                extra={"message_id": record.get("messageId")},
            )
            message_id = record.get("messageId")
            if message_id:
                batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}
