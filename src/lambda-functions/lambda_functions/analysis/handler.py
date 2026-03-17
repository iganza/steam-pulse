"""Lambda handler — LLM analysis for a single game.

Triggered by Step Functions. Input: {"appid": <int>, "game_name": <str>}
Reads reviews from DB, runs two-pass LLM analysis, writes report to DB.
"""

import asyncio
import os

import psycopg2
import psycopg2.extras
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.analyzer import analyze_reviews
from library_layer.utils.db import get_db_url
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.schema import create_all

from .events import AnalyzeRequest

logger = Logger(service="analysis")
tracer = Tracer(service="analysis")
metrics = Metrics(namespace="SteamPulse", service="analysis")

MAX_REVIEWS = 2000


# ── Eager module-level initialization — fails loud on cold start if DB unavailable
_conn: psycopg2.extensions.connection = psycopg2.connect(
    get_db_url(), cursor_factory=psycopg2.extras.RealDictCursor
)
create_all(_conn)
_game_repo: GameRepository = GameRepository(_conn)
_review_repo: ReviewRepository = ReviewRepository(_conn)
_report_repo: ReportRepository = ReportRepository(_conn)


async def _run(appid: int, game_name: str) -> dict:
    game = _game_repo.find_by_appid(appid)
    if not game:
        raise ValueError(f"appid={appid} not found in games table")

    db_reviews = _review_repo.find_by_appid(appid, limit=MAX_REVIEWS)
    if not db_reviews:
        raise ValueError(f"No reviews found for appid={appid}")

    reviews_for_llm = [
        {
            "voted_up": r.voted_up,
            "review_text": r.body or "",
            "playtime_at_review": (r.playtime_hours or 0) * 60,
        }
        for r in db_reviews
        if r.body
    ]

    if not reviews_for_llm:
        raise ValueError(f"No non-empty review bodies for appid={appid}")

    # Prefer game_name passed in (from review crawler); fall back to DB value
    name = game_name or game.name

    logger.info("Analyzing appid=%s name=%r reviews=%d", appid, name, len(reviews_for_llm))

    result = await analyze_reviews(reviews_for_llm, name, appid=appid)

    _report_repo.upsert(result)

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
    req = AnalyzeRequest.model_validate(event)
    logger.append_keys(appid=req.appid)

    result = asyncio.run(_run(req.appid, req.game_name))

    metrics.add_metric(name="ReportsGenerated", unit=MetricUnit.Count, value=1)

    return {
        "appid": req.appid,
        "game_name": req.game_name,
        "overall_sentiment": result.get("overall_sentiment"),
        "one_liner": result.get("one_liner"),
    }
