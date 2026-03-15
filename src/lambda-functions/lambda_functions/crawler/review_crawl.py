"""Review crawl logic — fetches Steam reviews and triggers Step Functions analysis.

Writes to: reviews.
Triggers: Step Functions state machine for LLM analysis.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

import httpx
import psycopg2
from aws_lambda_powertools import Logger

from library_layer.steam_source import DirectSteamSource, SteamAPIError

from .events import CrawlReviewsRequest

logger = Logger(service="crawler")

MAX_REVIEWS = 3000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_game_row(
    appid: int, conn: "psycopg2.connection"  # type: ignore[name-defined]
) -> bool:
    """Ensure a minimal game row exists (FK required by reviews table)."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM games WHERE appid = %s", (appid,))
        if cur.fetchone():
            return True
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
    max_reviews: int = MAX_REVIEWS,
) -> int:
    """Fetch and upsert reviews for one app. Returns count upserted."""
    try:
        reviews = await steam.get_reviews(appid, max_reviews=max_reviews)
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
# Dispatcher entry point
# ---------------------------------------------------------------------------


async def run(req: CrawlReviewsRequest, conn: "psycopg2.connection") -> dict:  # type: ignore[name-defined]
    async with httpx.AsyncClient(timeout=60.0) as client:
        steam = DirectSteamSource(client)
        n = await crawl_reviews(req.appid, steam, conn, max_reviews=req.max_reviews)
        return {"appid": req.appid, "reviews_upserted": n}
