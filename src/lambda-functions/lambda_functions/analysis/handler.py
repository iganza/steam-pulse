"""Lambda handler — three-phase LLM analysis for a single game (realtime mode).

Triggered by Step Functions or admin tools. Input: {"appid": <int>, "game_name": <str>}
Reads reviews from DB, runs the three-phase pipeline via ConverseBackend
(synchronous, in-process), writes the GameReport to DB, publishes ReportReadyEvent.

Batch-mode analysis (Bedrock Batch Inference) runs the SAME `analyze_game`
function with BatchBackend, driven by a separate Step Functions state
machine in infra/stacks/batch_analysis_stack.py.
"""

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.parameters import get_parameter
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.analyzer import analyze_game
from library_layer.config import SteamPulseConfig
from library_layer.events import AnalysisRequest, ReportReadyEvent
from library_layer.llm.converse import ConverseBackend
from library_layer.models.temporal import build_temporal_context
from library_layer.repositories.chunk_summary_repo import ChunkSummaryRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.merged_summary_repo import MergedSummaryRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.utils.db import get_conn
from library_layer.utils.events import EventPublishError, publish_event

from .events import AnalyzeRequest

logger = Logger(service="analysis")
tracer = Tracer(service="analysis")
metrics = Metrics(namespace="SteamPulse", service="analysis")

MAX_REVIEWS = 2000


# ── Module-level repo + backend wiring. DB connection is lazy; ConverseBackend
# is safe to construct at import time (holds a boto3 Bedrock client).
_game_repo: GameRepository = GameRepository(get_conn)
_review_repo: ReviewRepository = ReviewRepository(get_conn)
_report_repo: ReportRepository = ReportRepository(get_conn)
_chunk_repo: ChunkSummaryRepository = ChunkSummaryRepository(get_conn)
_merge_repo: MergedSummaryRepository = MergedSummaryRepository(get_conn)

_sns_client = boto3.client("sns")
_analysis_config = SteamPulseConfig()
_backend = ConverseBackend(_analysis_config)
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
            "steam_review_id": r.steam_review_id,
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

    analysis_req = AnalysisRequest(
        appid=req.appid,
        mode="realtime",
        reason="step_functions_realtime",
    )
    report = analyze_game(
        analysis_req,
        backend=_backend,
        chunk_repo=_chunk_repo,
        merge_repo=_merge_repo,
        report_repo=_report_repo,
        reviews=reviews_for_llm,
        game_name=name,
        temporal=temporal,
        steam_positive_pct=float(game.positive_pct) if game.positive_pct is not None else None,
        steam_review_count=game.review_count or None,
        steam_review_score_desc=game.review_score_desc,
    )

    if temporal.review_velocity_lifetime is not None:
        _game_repo.update_velocity_cache(req.appid, temporal.review_velocity_lifetime)

    try:
        publish_event(
            _sns_client,
            _content_events_topic_arn,
            ReportReadyEvent(
                appid=req.appid,
                game_name=name,
                review_score_desc=game.review_score_desc,
            ),
        )
    except EventPublishError:
        logger.warning("Failed to publish report-ready", extra={"appid": req.appid})

    metrics.add_metric(name="ReportsGenerated", unit=MetricUnit.Count, value=1)

    return {
        "appid": req.appid,
        "game_name": name,
        "review_score_desc": game.review_score_desc,
        "one_liner": report.one_liner,
    }
