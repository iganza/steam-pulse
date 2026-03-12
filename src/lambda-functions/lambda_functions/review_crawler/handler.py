"""Lambda handler — crawls reviews and triggers Step Functions analysis.

Triggered by SQS review-crawl-queue. Each message body: {"appid": <int>}
Writes to: reviews.
Triggers: Step Functions state machine for LLM analysis.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import httpx
import psycopg2

from steampulse.steam_source import DirectSteamSource, SteamAPIError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MAX_REVIEWS = 2000


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


def handler(event: dict, context: object) -> dict:
    """SQS-triggered Lambda. Each record body: {"appid": <int>}"""

    async def _run() -> dict:
        db_url = _get_db_url()
        conn = psycopg2.connect(db_url)
        total = failed = 0
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                steam = DirectSteamSource(client)
                for record in event.get("Records", []):
                    try:
                        body = json.loads(record["body"])
                        appid = int(body["appid"])
                    except (KeyError, ValueError, json.JSONDecodeError) as exc:
                        logger.error("Bad SQS message body=%r error=%s", record.get("body"), exc)
                        failed += 1
                        continue
                    n = await crawl_reviews(appid, steam, conn)
                    if n >= 0:
                        total += n
                    else:
                        failed += 1
        finally:
            conn.close()
        return {"reviews_upserted": total, "failed": failed}

    return asyncio.run(_run())
