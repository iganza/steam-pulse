"""SQS consumer that POSTs /api/revalidate to bust the game-${appid} tag."""

import hashlib
import json
import os

import boto3
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
_DISTRIBUTION_ID: str = get_parameter(  # type: ignore[assignment]
    os.environ["DISTRIBUTION_ID_PARAM"],
)
_FRONTEND_BUCKET: str = os.environ["FRONTEND_BUCKET"]


def _parse_cache_key_prefix(prefix: str) -> tuple[str, str]:
    """Validate "cache/{BUILD_ID}/" and return (prefix, build_id)."""
    if not prefix.startswith("cache/") or not prefix.endswith("/"):
        raise ValueError(
            f"CACHE_BUCKET_KEY_PREFIX must match 'cache/{{BUILD_ID}}/': {prefix!r}"
        )
    build_id = prefix[len("cache/"): -1]
    if not build_id or "/" in build_id:
        raise ValueError(
            f"CACHE_BUCKET_KEY_PREFIX must match 'cache/{{BUILD_ID}}/': {prefix!r}"
        )
    return prefix, build_id


# OpenNext writes pages under cache/{BUILD_ID}/{BUILD_ID}/... — the prefix
# is "cache/{BUILD_ID}/" and the inner BUILD_ID matches after pinning.
_CACHE_KEY_PREFIX, _BUILD_ID = _parse_cache_key_prefix(
    os.environ["CACHE_BUCKET_KEY_PREFIX"]
)
_HTTP_TIMEOUT_SECONDS = 5.0
_s3 = boto3.client("s3")
_cloudfront = boto3.client("cloudfront")

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


def _delete_page_cache(appid: int, slug: str) -> None:
    """Delete the OpenNext S3 page cache file (and .meta) for this game.

    Required workaround: OpenNext doesn't tag dynamic-route page entries
    in DynamoDB, so revalidatePath/revalidateTag don't bust them.
    """
    base_key = f"{_CACHE_KEY_PREFIX}{_BUILD_ID}/games/{appid}/{slug}"
    response = _s3.delete_objects(
        Bucket=_FRONTEND_BUCKET,
        Delete={
            "Objects": [
                {"Key": f"{base_key}.cache"},
                {"Key": f"{base_key}.cache.meta"},
            ]
        },
    )
    # delete_objects returns 200 even when individual keys fail (e.g.,
    # AccessDenied). Surface those so SQS retries / DLQ catches them.
    errors = response.get("Errors") or []
    if errors:
        raise RuntimeError(f"S3 delete_objects errors: {errors}")


def _invalidate_cdn(records: list[tuple[str, int]]) -> None:
    """Issue one CloudFront invalidation covering /games/{appid}/* for the batch."""
    paths = sorted({f"/games/{appid}/*" for _, appid in records})
    # Deterministic CallerReference: same messageId set → same key, so an SQS
    # retry after a successful CreateInvalidation reuses the existing one.
    digest = hashlib.sha256(
        "|".join(sorted(msg_id for msg_id, _ in records)).encode()
    ).hexdigest()[:32]
    _cloudfront.create_invalidation(
        DistributionId=_DISTRIBUTION_ID,
        InvalidationBatch={
            "Paths": {"Quantity": len(paths), "Items": paths},
            "CallerReference": f"revalidate-{digest}",
        },
    )


@logger.inject_lambda_context(clear_state=True)
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, _context: LambdaContext) -> dict:
    batch_item_failures: list[dict[str, str]] = []
    successful_records: list[tuple[str, int]] = []

    for record in event.get("Records", []):
        message_id = record.get("messageId", "")
        try:
            appid, slug = _extract_event(record)
            _post_revalidate(appid, slug)
            _delete_page_cache(appid, slug)
            metrics.add_metric(name="RevalidationsSucceeded", unit=MetricUnit.Count, value=1)
            metrics.add_metric(name="PageCacheBust", unit=MetricUnit.Count, value=1)
            logger.info("Revalidated", extra={"appid": appid, "slug": slug})
            if message_id:
                successful_records.append((message_id, appid))
        except Exception:
            logger.exception("Failed to revalidate", extra={"message_id": message_id})
            metrics.add_metric(name="RevalidationsFailed", unit=MetricUnit.Count, value=1)
            if message_id:
                batch_item_failures.append({"itemIdentifier": message_id})

    if successful_records:
        try:
            _invalidate_cdn(successful_records)
            metrics.add_metric(name="CdnInvalidations", unit=MetricUnit.Count, value=1)
            logger.info(
                "CloudFront invalidation issued",
                extra={"appids": [appid for _, appid in successful_records]},
            )
        except Exception:
            logger.exception("CloudFront invalidation failed")
            metrics.add_metric(name="CdnInvalidationsFailed", unit=MetricUnit.Count, value=1)
            for message_id, _ in successful_records:
                batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}
