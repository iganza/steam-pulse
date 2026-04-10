"""CollectPhase Lambda — collect Bedrock batch output and persist.

Runs after BatchBackend.status() reports "completed" for a phase. Reads the
output JSONL via BatchBackend.collect(), parses responses into the typed
pydantic models, and persists them through the SAME repositories the
realtime path uses (chunk_repo, merge_repo, report_repo).

Input:
    {
        "appid": 440,
        "phase": "chunk" | "merge" | "synthesis",
        "execution_id": "...",
        "job_id": "arn:aws:bedrock:...:model-invocation-job/...",
        "level": 1   # merge only
    }

Output:
    {
        "appid": 440,
        "phase": "<phase>",
        "collected": <int>,
        "done": true  # for synthesis, signals state machine to publish event
    }
"""

import os

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.parameters import get_parameter
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.analyzer import (
    CHUNK_PROMPT_VERSION,
    PIPELINE_VERSION,
    parse_chunk_record_id,
)
from library_layer.config import SteamPulseConfig
from library_layer.events import ReportReadyEvent
from library_layer.llm import make_batch_backend
from library_layer.llm.anthropic_batch import AnthropicBatchBackend
from library_layer.llm.batch import BatchBackend
from library_layer.models.analyzer_models import GameReport, RichChunkSummary
from library_layer.repositories.chunk_summary_repo import ChunkSummaryRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.utils.db import get_conn
from library_layer.utils.events import EventPublishError, publish_event
from library_layer.utils.scores import compute_hidden_gem_score, compute_sentiment_trend

logger = Logger(service="batch-collect-phase")
tracer = Tracer(service="batch-collect-phase")

_config = SteamPulseConfig()
_BATCH_BUCKET = os.environ["BATCH_BUCKET_NAME"]
_BATCH_ROLE_ARN = os.environ["BEDROCK_BATCH_ROLE_ARN"]
_CONTENT_EVENTS_TOPIC_ARN = get_parameter(_config.CONTENT_EVENTS_TOPIC_PARAM_NAME)

# Merge is handled entirely inline by `prepare_phase._prepare_merge` via
# ConverseBackend, so collect_phase owns no MergedSummaryRepository singleton
# — merged_summary_id flows in through the Step Functions event payload.
_game_repo = GameRepository(get_conn)
_chunk_repo = ChunkSummaryRepository(get_conn)
_report_repo = ReportRepository(get_conn)
_review_repo = ReviewRepository(get_conn)
_sns = boto3.client("sns")


def _backend_for(execution_id: str) -> BatchBackend | AnthropicBatchBackend:
    return make_batch_backend(
        _config,
        execution_id=execution_id,
        batch_bucket_name=_BATCH_BUCKET,
        batch_role_arn=_BATCH_ROLE_ARN,
    )


@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    appid = int(event["appid"])
    phase = event["phase"]
    execution_id = event["execution_id"]
    job_id = event["job_id"]
    logger.append_keys(appid=appid, phase=phase, execution_id=execution_id)

    backend = _backend_for(execution_id)

    if phase == "chunk":
        return _collect_chunk(appid, backend, job_id)
    if phase == "synthesis":
        # `merged_summary_id` and `chunk_count` are both threaded through
        # SFN state from the prepare-synthesis payload so the collect
        # phase never races on `find_latest_by_appid` / `find_by_appid`.
        if "merged_summary_id" not in event or event["merged_summary_id"] is None:
            raise ValueError("Missing required synthesis event field: merged_summary_id")
        if "chunk_count" not in event or event["chunk_count"] is None:
            raise ValueError("Missing required synthesis event field: chunk_count")
        merged_summary_id = int(event["merged_summary_id"])
        chunk_count = int(event["chunk_count"])
        return _collect_synthesis(appid, backend, job_id, merged_summary_id, chunk_count)
    # `merge` is handled entirely inline by `prepare_phase._prepare_merge`
    # via ConverseBackend — it always returns skip=true and the state
    # machine never routes a merge event here.
    raise ValueError(f"Unknown phase: {phase!r}")


def _collect_chunk(appid: int, backend: BatchBackend | AnthropicBatchBackend, job_id: str) -> dict:
    """Persist chunk_summaries rows from a completed chunking batch job.

    The prepare_phase Lambda encodes (chunk_index, chunk_size, chunk_hash)
    into each request's `record_id`. We parse those fields out here
    instead of re-chunking the current DB review set — the review set
    may have grown between prepare and collect (Bedrock Batch jobs run
    for hours), which would shift chunk membership and corrupt chunk_hash
    cache keys.
    """
    results = backend.collect(job_id, default_response_model=RichChunkSummary)
    model_id = _config.model_for("chunking")
    persisted = 0

    for record_id, summary in results:
        if not isinstance(summary, RichChunkSummary):
            logger.warning("unexpected_type", extra={"record_id": record_id})
            continue
        parsed = parse_chunk_record_id(record_id)
        if parsed is None:
            # parse_chunk_record_id already logged the failure.
            continue
        record_appid, chunk_index, review_count, chunk_hash = parsed
        if record_appid != appid:
            logger.warning(
                "record_id_appid_mismatch",
                extra={"record_id": record_id, "expected": appid, "got": record_appid},
            )
            continue
        _chunk_repo.insert(
            appid,
            chunk_index,
            chunk_hash,
            review_count,
            summary,
            model_id=model_id,
            prompt_version=CHUNK_PROMPT_VERSION,
        )
        persisted += 1
    return {"appid": appid, "phase": "chunk", "collected": persisted, "done": False}


def _collect_synthesis(
    appid: int,
    backend: BatchBackend | AnthropicBatchBackend,
    job_id: str,
    merged_summary_id: int,
    chunk_count: int,
) -> dict:
    """Collect synthesis output and upsert the final report.

    Both `merged_summary_id` and `chunk_count` are threaded from the
    prepare-synthesis payload via Step Functions state, NOT re-queried
    from the DB. Re-querying races with concurrent re-analysis and
    could attribute the report to a different merge row, or record a
    chunk count that does not match what the synthesis actually saw.
    """
    game = _game_repo.find_by_appid(appid)
    if game is None:
        raise ValueError(f"appid={appid} not in games table")

    # Filter to non-empty bodies so sentiment_trend / sample_size are
    # computed from the SAME review set the chunk + synthesis prepare
    # phases used. Otherwise the Python overrides would disagree with
    # `total_reviews_analyzed` and the pipeline would not be reproducible
    # across phases.
    db_reviews = _review_repo.find_by_appid(appid, limit=_config.ANALYSIS_MAX_REVIEWS)
    trend_reviews = [
        {
            "voted_up": r.voted_up,
            "posted_at": r.posted_at.isoformat() if r.posted_at else None,
        }
        for r in db_reviews
        if r.body
    ]

    results = backend.collect(job_id, default_response_model=GameReport)
    if not results:
        raise RuntimeError(f"No synthesis output for appid={appid}")
    _record_id, report = results[0]
    if not isinstance(report, GameReport):
        raise TypeError(f"Expected GameReport, got {type(report).__name__}")

    hidden_gem_score = compute_hidden_gem_score(
        float(game.positive_pct) if game.positive_pct is not None else None,
        game.review_count or None,
    )
    trend = compute_sentiment_trend(trend_reviews)
    report.hidden_gem_score = hidden_gem_score
    report.sentiment_trend = trend["trend"]  # type: ignore[assignment]
    report.sentiment_trend_note = trend["note"]
    report.sentiment_trend_reliable = trend["reliable"]
    report.sentiment_trend_sample_size = trend["sample_size"]
    report.appid = appid

    # Populate pipeline bookkeeping columns from the SFN-threaded state.
    # Both merged_summary_id AND chunk_count were captured at prepare
    # time so concurrent re-analysis / a CHUNK_PROMPT_VERSION bump
    # between prepare and collect cannot mis-attribute either field.
    payload = report.model_dump()
    payload["pipeline_version"] = PIPELINE_VERSION
    payload["merged_summary_id"] = merged_summary_id
    payload["chunk_count"] = chunk_count
    _report_repo.upsert(payload)

    try:
        publish_event(
            _sns,
            _CONTENT_EVENTS_TOPIC_ARN,
            ReportReadyEvent(
                appid=appid,
                game_name=game.name,
                review_score_desc=game.review_score_desc,
            ),
        )
    except EventPublishError:
        logger.warning("failed_to_publish_report_ready", extra={"appid": appid})

    return {"appid": appid, "phase": "synthesis", "collected": 1, "done": True}
