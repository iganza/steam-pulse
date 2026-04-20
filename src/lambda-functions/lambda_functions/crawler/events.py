"""Pydantic models for all crawler Lambda event payloads.

CDK / boto3 callers construct these and call .model_dump() as the payload.
The dispatcher validates the raw event dict using TypeAdapter.
"""

import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


def spoke_index_for_appid(appid: int, num_spokes: int) -> int:
    """Hash an appid to a spoke index using MD5 for even distribution.

    Steam appids are biased toward even numbers and round multiples of 10,
    so plain `appid % N` distributes unevenly (every other spoke gets traffic).
    MD5 gives even distribution and is deterministic across processes
    (unlike Python's built-in hash() which is randomized per process).
    """
    import hashlib

    digest = hashlib.md5(str(appid).encode()).digest()
    return int.from_bytes(digest[:4], "big") % num_spokes


class CrawlAppsRequest(BaseModel):
    action: Literal["crawl_apps"]
    appid: int


class CrawlReviewsRequest(BaseModel):
    action: Literal["crawl_reviews"]
    appid: int
    max_reviews: int | None = None  # None = fetch all reviews


class CatalogRefreshRequest(BaseModel):
    action: Literal["catalog_refresh"]


class RefreshMetaRequest(BaseModel):
    action: Literal["refresh_meta"]
    limit: int = 600


class RefreshReviewsRequest(BaseModel):
    action: Literal["refresh_reviews"]
    limit: int = 500


DirectRequest = Annotated[
    CrawlAppsRequest
    | CrawlReviewsRequest
    | CatalogRefreshRequest
    | RefreshMetaRequest
    | RefreshReviewsRequest,
    Field(discriminator="action"),
]


# ── Spoke payload contracts ─────────────────────────────────────────────────

CrawlTask = Literal["metadata", "reviews", "tags"]


# ── Spoke request models (Primary → Spoke) ──────────────────────────────────


class MetadataSpokeRequest(BaseModel):
    """Primary → Spoke: async Lambda invoke payload for metadata crawl."""

    appid: int
    task: CrawlTask = "metadata"


class ReviewSpokeRequest(BaseModel):
    """Primary → Spoke: async Lambda invoke payload for review crawl."""

    appid: int
    task: CrawlTask = "reviews"
    cursor: str = "*"
    target: int | None = None  # remaining reviews to fetch in this chain
    started_at: datetime | None = None  # when this crawl began (observability)


# ── Spoke result models (Spoke → Ingest via SQS) ────────────────────────────


class MetadataSpokeResult(BaseModel):
    """Spoke → Primary: SQS message body for completed metadata fetch."""

    appid: int
    task: CrawlTask = "metadata"
    success: bool
    s3_key: str | None = None
    count: int = 0
    spoke_region: str
    error: str | None = None


class ReviewSpokeResult(BaseModel):
    """Spoke → Primary: SQS message body for completed review batch fetch."""

    appid: int
    task: CrawlTask = "reviews"
    success: bool
    s3_key: str | None = None
    count: int = 0
    spoke_region: str
    next_cursor: str | None = None  # None = Steam exhausted; non-None = more pages remain
    target: int | None = None  # remaining reviews to fetch (pass-through, decremented per hop)
    started_at: datetime | None = None  # Pass-through from ReviewSpokeRequest
    error: str | None = None


class TagsSpokeRequest(BaseModel):
    """Primary → Spoke: async Lambda invoke payload for tags crawl."""

    appid: int
    task: CrawlTask = "tags"


class TagsSpokeResult(BaseModel):
    """Spoke → Primary: SQS message body for completed tags fetch."""

    appid: int
    task: CrawlTask = "tags"
    success: bool
    s3_key: str | None = None
    count: int = 0
    spoke_region: str
    error: str | None = None


# ── SQS record → typed spoke request ────────────────────────────────────────

SpokeRequest = MetadataSpokeRequest | ReviewSpokeRequest | TagsSpokeRequest


def parse_spoke_request(record: dict, *, review_limit: int) -> SpokeRequest | None:
    """Parse an SQS record into a typed spoke request.

    Handles SNS envelope unwrapping, task resolution, and review
    cursor/target normalization.

    Returns None if the message should be skipped (e.g. zero review budget).
    Raises ValueError for unrecognized messages.
    """
    body = json.loads(record["body"])
    if body.get("Type") == "Notification":
        body = json.loads(body["Message"])

    appid = int(body["appid"])

    # Direct SQS messages carry an explicit "task" field.
    # SNS-routed domain events (game-discovered, game-metadata-ready) don't —
    # infer from the queue that delivered them. Fail if neither is available.
    if "task" in body:
        task: str = body["task"]
    elif "review-crawl" in record.get("eventSourceARN", ""):
        task = "reviews"
    elif "app-crawl" in record.get("eventSourceARN", ""):
        task = "metadata"
    else:
        raise ValueError(
            f"Cannot determine task: no 'task' field in body and "
            f"unrecognized queue ARN {record.get('eventSourceARN', '<missing>')}"
        )

    match task:
        case "tags":
            return TagsSpokeRequest(appid=appid)
        case "reviews":
            cursor = body.get("cursor") or "*"
            started_at = body.get("started_at") or datetime.now(tz=UTC).isoformat()
            target_raw = body.get("target")
            if target_raw is None:
                target = review_limit
            elif target_raw <= 0:
                return None
            else:
                target = target_raw
            return ReviewSpokeRequest(
                appid=appid,
                cursor=cursor,
                target=target,
                started_at=started_at,
            )
        case "metadata":
            return MetadataSpokeRequest(appid=appid)
        case _:
            raise ValueError(f"Unknown task: {task!r} for appid={appid}")
