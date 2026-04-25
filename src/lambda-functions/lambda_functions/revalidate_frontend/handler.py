"""SQS consumer that POSTs /api/revalidate to bust the game-${appid} tag."""

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
_HTTP_TIMEOUT_SECONDS = 5.0

# Lazy-init so connections pool across records and warm invocations.
_http_client: httpx.Client | None = None


def _get_http_client() -> httpx.Client:
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS)
    return _http_client


def _extract_appid(record: dict) -> int:
    """Parse the SNS-wrapped ReportReadyEvent body and return the appid."""
    body = json.loads(record["body"])
    inner_raw = body.get("Message", body)
    inner = json.loads(inner_raw) if isinstance(inner_raw, str) else inner_raw
    appid = inner.get("appid")
    if not isinstance(appid, int):
        raise ValueError(f"missing/invalid appid in event: {inner!r}")
    return appid


def _post_revalidate(appid: int) -> None:
    response = _get_http_client().post(
        f"{_FRONTEND_BASE_URL}/api/revalidate",
        headers={
            "x-revalidate-token": _REVALIDATE_TOKEN,
            "content-type": "application/json",
        },
        json={"appid": appid},
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
