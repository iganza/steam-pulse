"""Lambda handler — LLM analysis for a single game.

Triggered by Step Functions. Input: {"appid": <int>, "game_name": <str>}
Reads reviews from DB, runs two-pass LLM analysis, writes report to DB.
"""

import asyncio
import json
import os

import psycopg2
import psycopg2.extras
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

from library_layer.analyzer import analyze_reviews
from library_layer.storage import PostgresStorage

logger = Logger(service="analysis")
tracer = Tracer(service="analysis")
metrics = Metrics(namespace="SteamPulse", service="analysis")

MAX_REVIEWS = 2000


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


def _load_reviews(appid: int, db_url: str) -> tuple[str, list[dict]]:
    """Load game name and reviews from DB. Returns (game_name, reviews)."""
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT name FROM games WHERE appid = %s", (appid,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"appid={appid} not found in games table")
            game_name: str = row["name"]

            cur.execute(
                """
                SELECT voted_up, body, playtime_hours
                FROM reviews
                WHERE appid = %s
                ORDER BY posted_at DESC NULLS LAST
                LIMIT %s
                """,
                (appid, MAX_REVIEWS),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    reviews = [
        {
            "voted_up": r["voted_up"],
            "review_text": r["body"] or "",
            "playtime_at_review": (r["playtime_hours"] or 0) * 60,
        }
        for r in rows
        if r["body"]
    ]
    return game_name, reviews


async def _run(appid: int, game_name: str, db_url: str) -> dict:
    game_name_from_db, reviews = _load_reviews(appid, db_url)
    # Prefer game_name passed in (from review crawler); fall back to DB value
    name = game_name or game_name_from_db

    logger.info("Analyzing appid=%s name=%r reviews=%d", appid, name, len(reviews))

    if not reviews:
        raise ValueError(f"No reviews found for appid={appid}")

    result = await analyze_reviews(reviews, name, appid=appid)

    storage = PostgresStorage(db_url)
    await storage.upsert_report(appid, result)

    logger.info(
        "Report stored for appid=%s sentiment=%s",
        appid,
        result.get("overall_sentiment"),
    )
    return result


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    """Step Functions task. Input: {"appid": <int>, "game_name": <str>}"""
    appid = int(event["appid"])
    game_name: str = event.get("game_name", "")

    logger.append_keys(appid=appid)

    db_url = _get_db_url()
    result = asyncio.run(_run(appid, game_name, db_url))

    metrics.add_metric(name="ReportsGenerated", unit=MetricUnit.Count, value=1)

    return {
        "appid": appid,
        "game_name": game_name,
        "overall_sentiment": result.get("overall_sentiment"),
        "one_liner": result.get("one_liner"),
    }
