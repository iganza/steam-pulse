"""Revalidate-Frontend Lambda — SQS → POST /api/revalidate.

Drains frontend_revalidation_queue (SNS-wrapped ReportReadyEvent), calls
the Next.js /api/revalidate route on the frontend Lambda's Function URL.
That route runs `revalidateTag(`game-${appid}`, 'max')`, which busts the
shared cache tag covering getGameReport / getReviewStats / getBenchmarks
in one shot.

Idempotent — re-delivering the same message just calls revalidateTag
again, which is a cheap no-op when nothing is cached. Failures raise so
SQS retries; persistent failures land on the DLQ.
"""

import json
import os

import httpx
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.parameters import get_parameter
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger(service="revalidate-frontend")
metrics = Metrics(namespace="SteamPulse", service="revalidate-frontend")

_FRONTEND_BASE_URL: str = os.environ["FRONTEND_BASE_URL"].rstrip("/")
_REVALIDATE_TOKEN: str = get_parameter(  # type: ignore[assignment]
    os.environ["REVALIDATE_TOKEN_PARAM"],
    decrypt=True,
)
_HTTP_TIMEOUT_SECONDS = 10.0


def _extract_appid(record: dict) -> int:
    """Parse SNS-wrapped ReportReadyEvent body and return the appid."""
    body = json.loads(record["body"])
    inner_raw = body.get("Message", body)
    inner = json.loads(inner_raw) if isinstance(inner_raw, str) else inner_raw
    appid = inner.get("appid")
    if not isinstance(appid, int):
        raise ValueError(f"missing/invalid appid in event: {inner!r}")
    return appid


def _post_revalidate(appid: int) -> None:
    response = httpx.post(
        f"{_FRONTEND_BASE_URL}/api/revalidate",
        headers={
            "x-revalidate-token": _REVALIDATE_TOKEN,
            "content-type": "application/json",
        },
        json={"appid": appid},
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


@logger.inject_lambda_context(clear_state=True)
@metrics.log_metrics
def handler(event: dict, _context: LambdaContext) -> dict:
    batch_item_failures: list[dict[str, str]] = []

    for record in event.get("Records", []):
        message_id = record.get("messageId", "")
        try:
            appid = _extract_appid(record)
            _post_revalidate(appid)
            metrics.add_metric(name="RevalidationsSucceeded", unit=MetricUnit.Count, value=1)
            logger.info("Revalidated", extra={"appid": appid})
        except Exception:
            logger.exception("Failed to revalidate", extra={"message_id": message_id})
            metrics.add_metric(name="RevalidationsFailed", unit=MetricUnit.Count, value=1)
            if message_id:
                batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}
