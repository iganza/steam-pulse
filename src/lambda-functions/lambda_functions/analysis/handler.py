"""Lambda handler — LLM analysis for a single game.

Triggered by Step Functions. Input: {"appid": <int>, "game_name": <str>}
Reads reviews from DB, runs two-pass LLM analysis, writes report to DB.

DEPRECATED: This real-time analysis path is unused. The active analysis path is
the batch pipeline in lambda_functions/batch_analysis/. This file is slated for
deletion — see scripts/prompts/remove-realtime-analysis.md. Do not add new features here.
"""

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.parameters import get_parameter
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.analyzer import analyze_reviews
from library_layer.config import SteamPulseConfig
from library_layer.events import ReportReadyEvent
from library_layer.models.temporal import build_temporal_context
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.utils.db import get_conn
from library_layer.utils.events import EventPublishError, publish_event

from .events import AnalyzeRequest

logger = Logger(service="analysis")
tracer = Tracer(service="analysis")
metrics = Metrics(namespace="SteamPulse", service="analysis")

MAX_REVIEWS = 2000


# ── Module-level repo wiring — DB connection is lazy (established on first query).
# Schema managed by yoyo migrations — see src/lambda-functions/migrations/
_game_repo: GameRepository = GameRepository(get_conn)
_review_repo: ReviewRepository = ReviewRepository(get_conn)
_report_repo: ReportRepository = ReportRepository(get_conn)

_sns_client = boto3.client("sns")
_analysis_config = SteamPulseConfig()
metrics.set_default_dimensions(environment=_analysis_config.ENVIRONMENT)
_content_events_topic_arn = get_parameter(_analysis_config.CONTENT_EVENTS_TOPIC_PARAM_NAME)


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    """Step Functions task. Input: {"appid": <int>, "game_name": <str>}"""
    req = AnalyzeRequest.model_validate(event)
    logger.append_keys(appid=req.appid)

    game = _game_repo.find_by_appid(req.appid)
    if not game:
        raise ValueError(f"appid={req.appid} not found in games table")

    db_reviews = _review_repo.find_by_appid(req.appid, limit=MAX_REVIEWS)
    if not db_reviews:
        raise ValueError(f"No reviews found for appid={req.appid}")

    reviews_for_llm = [
        {
            "voted_up": r.voted_up,
            "review_text": r.body,
            "playtime_hours": r.playtime_hours or 0,
            "votes_helpful": r.votes_helpful,
            "votes_funny": r.votes_funny,
            "posted_at": r.posted_at.isoformat() if r.posted_at else None,
            "written_during_early_access": r.written_during_early_access,
            "received_for_free": r.received_for_free,
        }
        for r in db_reviews
        if r.body
    ]

    if not reviews_for_llm:
        raise ValueError(f"No non-empty review bodies for appid={req.appid}")

    name = req.game_name or game.name
    logger.info(
        "Analyzing game",
        extra={"appid": req.appid, "game_name": name, "review_count": len(reviews_for_llm)},
    )

    # Build temporal context from existing repo data
    velocity_data = _review_repo.find_review_velocity(req.appid)
    ea_data = _review_repo.find_early_access_impact(req.appid)
    temporal = build_temporal_context(game, velocity_data, ea_data)

    result = analyze_reviews(
        reviews_for_llm,
        name,
        appid=req.appid,
        temporal=temporal,
        steam_positive_pct=float(game.positive_pct) if game.positive_pct is not None else None,
        steam_review_count=game.review_count or None,
        steam_review_score_desc=game.review_score_desc,
    )
    _report_repo.upsert(result)

    if temporal.review_velocity_lifetime is not None:
        _game_repo.update_velocity_cache(req.appid, temporal.review_velocity_lifetime)

    try:
        publish_event(
            _sns_client,
            _content_events_topic_arn,
            ReportReadyEvent(
                appid=req.appid,
                game_name=req.game_name,
                review_score_desc=game.review_score_desc,
            ),
        )
    except EventPublishError:
        logger.warning("Failed to publish report-ready", extra={"appid": req.appid})

    metrics.add_metric(name="ReportsGenerated", unit=MetricUnit.Count, value=1)

    return {
        "appid": req.appid,
        "game_name": req.game_name,
        "review_score_desc": game.review_score_desc,
        "one_liner": result.get("one_liner"),
    }
