"""Email sending abstraction — provider-agnostic interface.

The only Resend import in the codebase lives in ResendEmailSender.
Swapping providers means writing a new implementation class — no call site changes.
"""

from typing import Protocol

from aws_lambda_powertools import Logger

logger = Logger()


class EmailSender(Protocol):
    """Protocol for sending transactional emails."""

    def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        from_addr: str,
        reply_to: str | None = None,
    ) -> None: ...


class ResendEmailSender:
    """EmailSender implementation backed by Resend."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        from_addr: str,
        reply_to: str | None = None,
    ) -> None:
        import resend  # type: ignore[import-untyped]

        resend.api_key = self._api_key
        payload: dict[str, object] = {
            "from": from_addr,
            "to": [to],
            "subject": subject,
            "html": html,
        }
        if reply_to:
            payload["reply_to"] = reply_to
        resend.Emails.send(payload)


def send_email_safe(
    sender: EmailSender,
    *,
    to: str,
    subject: str,
    html: str,
    from_addr: str,
    reply_to: str | None = None,
) -> None:
    """Fire-and-forget wrapper — logs warning on failure, never raises."""
    try:
        sender.send(to=to, subject=subject, html=html, from_addr=from_addr, reply_to=reply_to)
    except Exception as exc:
        logger.warning("Email send failed", extra={"to": to, "subject": subject, "error": str(exc)})
