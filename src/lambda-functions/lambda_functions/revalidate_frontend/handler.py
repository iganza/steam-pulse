"""SQS consumer that POSTs /api/revalidate to bust the game-${appid} tag."""

import json
import os

import httpx
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.parameters import get_parameter
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.config import SteamPulseConfig

_config = SteamPulseConfig()

logger = Logger(service="revalidate-frontend")
metrics = Metrics(namespace="SteamPulse", service="revalidate-frontend")
metrics.set_default_dimensions(environment=_config.ENVIRONMENT)

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


def _extract_event(record: dict) -> tuple[int, str]:
    """Parse the SNS-wrapped ReportReadyEvent body; return (appid, slug)."""
    body = json.loads(record["body"])
    inner_raw = body.get("Message", body)
    inner = json.loads(inner_raw) if isinstance(inner_raw, str) else inner_raw
    appid = inner.get("appid")
    slug = inner.get("slug")
    if not isinstance(appid, int):
        raise ValueError(f"missing/invalid appid in event: {inner!r}")
    if not isinstance(slug, str) or not slug:
        raise ValueError(f"missing/invalid slug in event: {inner!r}")
    return appid, slug


def _post_revalidate(appid: int, slug: str) -> None:
    response = _get_http_client().post(
        f"{_FRONTEND_BASE_URL}/api/revalidate",
        headers={
            "x-revalidate-token": _REVALIDATE_TOKEN,
            "content-type": "application/json",
        },
        json={"appid": appid, "slug": slug},
    )
    response.raise_for_status()


@logger.inject_lambda_context(clear_state=True)
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, _context: LambdaContext) -> dict:
    batch_item_failures: list[dict[str, str]] = []

    for record in event.get("Records", []):
        message_id = record.get("messageId", "")
        try:
            appid, slug = _extract_event(record)
            _post_revalidate(appid, slug)
            metrics.add_metric(name="RevalidationsSucceeded", unit=MetricUnit.Count, value=1)
            logger.info("Revalidated", extra={"appid": appid, "slug": slug})
        except Exception:
            logger.exception("Failed to revalidate", extra={"message_id": message_id})
            metrics.add_metric(name="RevalidationsFailed", unit=MetricUnit.Count, value=1)
            if message_id:
                batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}
