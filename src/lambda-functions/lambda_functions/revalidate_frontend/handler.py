"""SQS consumer that refreshes frontend game pages end-to-end.

POSTs /api/revalidate to bust the game-${appid} tag, deletes the
corresponding OpenNext S3 page-cache objects, and issues a CloudFront
invalidation so stale HTML is not served at the edge.
"""

import hashlib
import json
import os

import boto3
import httpx
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.parameters import get_parameter
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.config import SteamPulseConfig

_config = SteamPulseConfig()

logger = Logger(service="revalidate-frontend")


def _require_param(name: str, value: object) -> str:
    """get_parameter typing is loose — fail loudly at cold start if it returns falsy."""
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"SSM parameter {name!r} resolved to empty/non-string: {value!r}")
    return value


_FRONTEND_BASE_URL: str = os.environ["FRONTEND_BASE_URL"].rstrip("/")
_REVALIDATE_TOKEN: str = _require_param(
    os.environ["REVALIDATE_TOKEN_PARAM"],
    get_parameter(os.environ["REVALIDATE_TOKEN_PARAM"], decrypt=True),
)
_DISTRIBUTION_ID: str = _require_param(
    os.environ["DISTRIBUTION_ID_PARAM"],
    get_parameter(os.environ["DISTRIBUTION_ID_PARAM"]),
)
_FRONTEND_BUCKET: str = os.environ["FRONTEND_BUCKET"]


def _validate_cache_key_prefix(prefix: str) -> str:
    """Fail loud if CACHE_BUCKET_KEY_PREFIX is malformed."""
    if not prefix.startswith("cache/") or not prefix.endswith("/"):
        raise ValueError(f"CACHE_BUCKET_KEY_PREFIX must match 'cache/{{BUILD_ID}}/': {prefix!r}")
    outer = prefix[len("cache/") : -1]
    if not outer or "/" in outer:
        raise ValueError(f"CACHE_BUCKET_KEY_PREFIX must match 'cache/{{BUILD_ID}}/': {prefix!r}")
    return prefix


_CACHE_KEY_PREFIX = _validate_cache_key_prefix(os.environ["CACHE_BUCKET_KEY_PREFIX"])
_HTTP_TIMEOUT_SECONDS = 5.0
_s3 = boto3.client("s3")
_cloudfront = boto3.client("cloudfront")


def _discover_inner_build_ids() -> list[str]:
    """List subdirs of cache/{OUTER}/ to find OpenNext's inner build ID(s)."""
    response = _s3.list_objects_v2(
        Bucket=_FRONTEND_BUCKET,
        Prefix=_CACHE_KEY_PREFIX,
        Delimiter="/",
    )
    common = response.get("CommonPrefixes") or []
    inner_ids = [p["Prefix"][len(_CACHE_KEY_PREFIX) : -1] for p in common]
    inner_ids = [i for i in inner_ids if i]
    if not inner_ids:
        raise RuntimeError(
            f"No inner build IDs found under s3://{_FRONTEND_BUCKET}/{_CACHE_KEY_PREFIX} "
            "frontend deploy may be incomplete."
        )
    return inner_ids


# OpenNext writes pages to cache/{OUTER}/{INNER}/... where OUTER comes from
# CACHE_BUCKET_KEY_PREFIX and INNER is OpenNext's own build id; the two do
# not always match, so discover INNER from S3 instead of assuming.
_INNER_BUILD_IDS = _discover_inner_build_ids()

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
    """Delete OpenNext S3 page-cache files for this game across all inner build IDs.

    Required workaround: OpenNext doesn't tag dynamic-route page entries
    in DynamoDB, so revalidatePath/revalidateTag don't bust them.
    """
    objects: list[dict[str, str]] = []
    for inner in _INNER_BUILD_IDS:
        base = f"{_CACHE_KEY_PREFIX}{inner}/games/{appid}/{slug}"
        objects.append({"Key": f"{base}.cache"})
        objects.append({"Key": f"{base}.cache.meta"})
    response = _s3.delete_objects(
        Bucket=_FRONTEND_BUCKET,
        Delete={"Objects": objects},
    )
    # delete_objects returns 200 even when individual keys fail (e.g.,
    # AccessDenied). Surface those so SQS retries / DLQ catches them.
    errors = response.get("Errors") or []
    if errors:
        raise RuntimeError(f"S3 delete_objects errors: {errors}")


def _invalidate_cdn(records: list[tuple[str, int]]) -> None:
    """Issue one CloudFront invalidation covering the game page + its 4 SSR-fanout API paths."""
    paths: set[str] = set()
    for _, appid in records:
        paths.add(f"/games/{appid}/*")
        # API paths are edge-cached (s-maxage=86400) — must invalidate alongside HTML
        # or fresh analyses serve stale data for up to 24 h.
        paths.add(f"/api/games/{appid}/report")
        paths.add(f"/api/games/{appid}/review-stats")
        paths.add(f"/api/games/{appid}/benchmarks")
        paths.add(f"/api/games/{appid}/related-analyzed")
    sorted_paths = sorted(paths)
    # Deterministic CallerReference: same messageId set → same key, so an SQS
    # retry after a successful CreateInvalidation reuses the existing one.
    digest = hashlib.sha256("|".join(sorted(msg_id for msg_id, _ in records)).encode()).hexdigest()[
        :32
    ]
    _cloudfront.create_invalidation(
        DistributionId=_DISTRIBUTION_ID,
        InvalidationBatch={
            "Paths": {"Quantity": len(sorted_paths), "Items": sorted_paths},
            "CallerReference": f"revalidate-{digest}",
        },
    )


@logger.inject_lambda_context(clear_state=True)
def handler(event: dict, _context: LambdaContext) -> dict:
    batch_item_failures: list[dict[str, str]] = []
    successful_records: list[tuple[str, int]] = []

    for record in event.get("Records", []):
        message_id = record.get("messageId", "")
        try:
            appid, slug = _extract_event(record)
            _post_revalidate(appid, slug)
            _delete_page_cache(appid, slug)
            logger.info("Revalidated", extra={"appid": appid, "slug": slug})
            if message_id:
                successful_records.append((message_id, appid))
        except Exception:
            logger.exception("Failed to revalidate", extra={"message_id": message_id})
            if message_id:
                batch_item_failures.append({"itemIdentifier": message_id})

    if successful_records:
        try:
            _invalidate_cdn(successful_records)
            logger.info(
                "CloudFront invalidation issued",
                extra={"appids": [appid for _, appid in successful_records]},
            )
        except Exception:
            logger.exception("CloudFront invalidation failed")
            for message_id, _ in successful_records:
                batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}
