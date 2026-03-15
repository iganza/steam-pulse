"""Lambda handler — crawls reviews and triggers Step Functions analysis.

Triggered by SQS review-crawl-queue. Each message body: {"appid": <int>}
Writes to: reviews.
Triggers: Step Functions state machine for LLM analysis.
"""

import asyncio
import json
import os
from datetime import datetime, timezone

import httpx
import psycopg2
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, process_partial_response
from aws_lambda_powertools.utilities.typing import LambdaContext

from library_layer.steam_source import DirectSteamSource, SteamAPIError

logger = Logger(service="review-crawler")
tracer = Tracer(service="review-crawler")
metrics = Metrics(namespace="SteamPulse", service="review-crawler")
processor = BatchProcessor(event_type=EventType.SQS)

MAX_REVIEWS = 3000


# ---------------------------------------------------------------------------
# Helpers (duplicated from app_crawler to keep Lambdas self-contained)
# ---------------------------------------------------------------------------


def _get_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    secret_arn = os.getenv("DB_SECRET_ARN")
    if secret_arn:
        import boto3  # type: ignore[import-untyped]
        sm = boto3.client("secretsmanager")
        secret = json.loads(sm.get_secret_value(SecretId=secret_arn)["SecretString"])
        return (
            f"postgresql://{secret['username']}:{secret['password']}"
            f"@{secret['host']}:{secret['port']}/{secret['dbname']}"
        )
    raise RuntimeError("No DATABASE_URL or DB_SECRET_ARN configured")


def _ensure_game_row(
    appid: int, conn: "psycopg2.connection"  # type: ignore[name-defined]
) -> bool:
    """Ensure a minimal game row exists (FK required by reviews table)."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM games WHERE appid = %s", (appid,))
        if cur.fetchone():
            return True
        # Insert minimal stub — app_crawler will fill details later
        stub_name = f"App {appid}"
        stub_slug = f"app-{appid}"
        cur.execute(
            """
            INSERT INTO games (appid, name, slug) VALUES (%s, %s, %s)
            ON CONFLICT (appid) DO NOTHING
            """,
            (appid, stub_name, stub_slug),
        )
    conn.commit()
    return True


def _start_analysis(appid: int, game_name: str) -> str | None:
    """Start Step Functions execution. Returns execution ARN or None."""
    sfn_arn = os.getenv("SFN_ARN") or os.getenv("STEP_FUNCTIONS_ARN")
    if not sfn_arn:
        logger.info("No SFN_ARN set — skipping Step Functions trigger for appid=%s", appid)
        return None
    try:
        import boto3  # type: ignore[import-untyped]
        import uuid as _uuid
        sfn = boto3.client("stepfunctions")
        resp = sfn.start_execution(
            stateMachineArn=sfn_arn,
            name=f"analysis-{appid}-{_uuid.uuid4().hex[:8]}",
            input=json.dumps({"appid": appid, "game_name": game_name}),
        )
        arn: str = resp["executionArn"]
        logger.info("Started Step Functions execution %s for appid=%s", arn, appid)
        return arn
    except Exception as exc:
        logger.error("Failed to start Step Functions for appid=%s: %s", appid, exc)
        return None


# ---------------------------------------------------------------------------
# Core crawl logic (importable for testing)
# ---------------------------------------------------------------------------


async def crawl_reviews(
    appid: int,
    steam: DirectSteamSource,
    conn: "psycopg2.connection",  # type: ignore[name-defined]
    dry_run: bool = False,
) -> int:
    """Fetch and upsert reviews for one app. Returns count upserted."""
    try:
        reviews = await steam.get_reviews(appid, max_reviews=MAX_REVIEWS)
    except SteamAPIError as exc:
        logger.warning("Steam reviews API error for appid=%s: %s", appid, exc)
        return 0

    if not reviews:
        logger.info("No reviews found for appid=%s", appid)
        return 0

    logger.info("Fetched %d reviews for appid=%s", len(reviews), appid)

    if dry_run:
        return len(reviews)

    _ensure_game_row(appid, conn)

    # Fetch game name for SFN payload
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM games WHERE appid = %s", (appid,))
        row = cur.fetchone()
    game_name: str = row[0] if row else f"App {appid}"

    upserted = 0
    with conn.cursor() as cur:
        for r in reviews:
            steam_id: str = str(r.get("timestamp_created", "")) + "_" + str(appid)
            posted_at: datetime | None = None
            ts = r.get("timestamp_created")
            if ts:
                try:
                    posted_at = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                except (ValueError, OSError):
                    pass

            playtime_minutes: int = int(r.get("playtime_at_review") or 0)
            playtime_hours = playtime_minutes // 60

            cur.execute(
                """
                INSERT INTO reviews (
                    appid, steam_review_id, voted_up, playtime_hours, body, posted_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (steam_review_id) DO UPDATE SET
                    voted_up      = EXCLUDED.voted_up,
                    playtime_hours = EXCLUDED.playtime_hours,
                    body          = EXCLUDED.body
                """,
                (
                    appid,
                    steam_id,
                    bool(r.get("voted_up", False)),
                    playtime_hours,
                    r.get("review_text", ""),
                    posted_at,
                ),
            )
            upserted += 1

    conn.commit()
    logger.info("Upserted %d reviews for appid=%s", upserted, appid)

    # Trigger LLM analysis after successful review upsert
    _start_analysis(appid, game_name)

    return upserted


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

_conn: "psycopg2.connection | None" = None  # type: ignore[name-defined]


def _get_conn() -> "psycopg2.connection":  # type: ignore[name-defined]
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(_get_db_url())
    return _conn


def _record_handler(record: dict) -> None:
    """Process a single SQS record. Raises on failure so BatchProcessor marks it for DLQ."""
    body = json.loads(record["body"])
    appid = int(body["appid"])
    logger.append_keys(appid=appid)

    async def _run() -> None:
        async with httpx.AsyncClient(timeout=60.0) as client:
            steam = DirectSteamSource(client)
            n = await crawl_reviews(appid, steam, _get_conn())
            metrics.add_metric(name="ReviewsUpserted", unit=MetricUnit.Count, value=n)

    asyncio.run(_run())


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    """SQS-triggered Lambda. Each record body: {"appid": <int>}"""
    return process_partial_response(
        event=event,
        record_handler=_record_handler,
        processor=processor,
        context=context,
    )
