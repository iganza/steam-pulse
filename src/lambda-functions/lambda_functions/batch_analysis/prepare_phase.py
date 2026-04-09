"""PreparePhase Lambda — thin wrapper over shared analyzer helpers + BatchBackend.

Per-game Step Functions execution: one appid per invocation. Parent orchestrator
uses a Map state to fan out across an appid list. Parametrized by `phase` so
the same handler services chunk / merge / synthesis preparation:

Input:
    {
        "appid": 440,
        "phase": "chunk" | "merge" | "synthesis",
        "execution_id": "sp-batch-20260409-abcd"
    }

Output (phase == "chunk" | "merge" | "synthesis"):
    {
        "appid": 440,
        "phase": "<phase>",
        "execution_id": "...",
        "job_id": "arn:aws:bedrock:...:model-invocation-job/...",
        "skip": false,    # true if everything was cache-hit and no Bedrock job was needed
        "next_level": null  # populated for merge continuation (see collect_phase)
    }

When `skip=true`, Step Functions should short-circuit the Wait/Check loop for
this phase and proceed directly to the next phase. The downstream state reads
the persisted artifacts (chunk_summaries / merged_summaries) from Postgres.

"Job still pending" is Step Functions state, NEVER an exception. This Lambda
returns immediately after `BatchBackend.submit()`; the polling loop lives in
the state machine (see infra/stacks/batch_analysis_stack.py).
"""

import os

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.analyzer import (
    build_chunk_requests,
    build_merge_requests,
    build_synthesis_request,
)
from library_layer.config import SteamPulseConfig
from library_layer.llm.batch import BatchBackend
from library_layer.models.analyzer_models import RichChunkSummary
from library_layer.models.temporal import build_temporal_context
from library_layer.repositories.chunk_summary_repo import ChunkSummaryRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.merged_summary_repo import MergedSummaryRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.utils.db import get_conn

logger = Logger(service="batch-prepare-phase")
tracer = Tracer(service="batch-prepare-phase")

_config = SteamPulseConfig()
_BATCH_BUCKET = os.environ["BATCH_BUCKET_NAME"]
_BATCH_ROLE_ARN = os.environ["BEDROCK_BATCH_ROLE_ARN"]

_game_repo = GameRepository(get_conn)
_review_repo = ReviewRepository(get_conn)
_chunk_repo = ChunkSummaryRepository(get_conn)
_merge_repo = MergedSummaryRepository(get_conn)

MAX_REVIEWS = 2000


def _backend_for(execution_id: str) -> BatchBackend:
    return BatchBackend(
        _config,
        batch_bucket_name=_BATCH_BUCKET,
        batch_role_arn=_BATCH_ROLE_ARN,
        execution_id=execution_id,
    )


@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    appid = int(event["appid"])
    phase = event["phase"]
    execution_id = event["execution_id"]
    logger.append_keys(appid=appid, phase=phase, execution_id=execution_id)

    backend = _backend_for(execution_id)

    if phase == "chunk":
        return _prepare_chunk(appid, backend, execution_id)
    if phase == "merge":
        level = int(event.get("level", 1))
        return _prepare_merge(appid, backend, execution_id, level)
    if phase == "synthesis":
        return _prepare_synthesis(appid, backend, execution_id)

    raise ValueError(f"Unknown phase: {phase!r}")


def _prepare_chunk(appid: int, backend: BatchBackend, execution_id: str) -> dict:
    game = _game_repo.find_by_appid(appid)
    if game is None:
        raise ValueError(f"appid={appid} not in games table")

    db_reviews = _review_repo.find_by_appid(appid, limit=MAX_REVIEWS)
    reviews = [
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
    if not reviews:
        raise ValueError(f"No non-empty reviews for appid={appid}")

    from library_layer.analyzer import CHUNK_PROMPT_VERSION

    cached_rows = _chunk_repo.find_by_appid(appid, CHUNK_PROMPT_VERSION)
    cached_hashes = {row["chunk_hash"] for row in cached_rows}
    _chunks, pending, _pending_meta = build_chunk_requests(
        appid=appid,
        game_name=game.name,
        reviews=reviews,
        cached_hashes=cached_hashes,
    )

    if not pending:
        logger.info("chunk_prepare_all_cached", extra={"cached": len(cached_rows)})
        return {
            "appid": appid,
            "phase": "chunk",
            "execution_id": execution_id,
            "job_id": None,
            "skip": True,
        }

    s3_uri = backend.prepare(pending, phase=f"chunk-{appid}")
    job_id = backend.submit(s3_uri, task="chunking", phase=f"chunk-{appid}")
    return {
        "appid": appid,
        "phase": "chunk",
        "execution_id": execution_id,
        "job_id": job_id,
        "skip": False,
    }


def _prepare_merge(appid: int, backend: BatchBackend, execution_id: str, level: int) -> dict:
    """Build merge requests for the current level.

    Level 1: inputs are chunk_summaries rows.
    Level >= 2: inputs are merged_summaries rows from the previous level.
    Returns `next_level: null` when the merge converges to a single summary,
    signalling the state machine to proceed to synthesis.
    """
    game = _game_repo.find_by_appid(appid)
    if game is None:
        raise ValueError(f"appid={appid} not in games table")

    from library_layer.analyzer import (
        CHUNK_PROMPT_VERSION,
        plan_merge_groups,
    )

    if level == 1:
        rows = _chunk_repo.find_by_appid(appid, CHUNK_PROMPT_VERSION)
        summaries = [RichChunkSummary.model_validate(r["summary_json"]) for r in rows]
    else:
        # For level > 1 we would read merged_summaries at the prior level.
        # Per the plan, max depth is 3. In the current pragmatic design
        # higher levels run through without source-id cache lookup.
        raise NotImplementedError("level > 1 merge not yet wired — requires DB read-back")

    if len(summaries) <= 1:
        logger.info("merge_prepare_promote_single", extra={"level": level})
        return {
            "appid": appid,
            "phase": "merge",
            "execution_id": execution_id,
            "job_id": None,
            "skip": True,
            "next_level": None,
        }

    groups = plan_merge_groups(summaries)
    indexed = list(enumerate(groups))
    requests = build_merge_requests(
        appid=appid,
        game_name=game.name,
        groups=indexed,
        level=level,
    )
    s3_uri = backend.prepare(requests, phase=f"merge-L{level}-{appid}")
    job_id = backend.submit(s3_uri, task="merging", phase=f"merge-L{level}-{appid}")
    # If this level produced a single group we're done after it collects.
    next_level = None if len(groups) == 1 else level + 1
    return {
        "appid": appid,
        "phase": "merge",
        "execution_id": execution_id,
        "job_id": job_id,
        "skip": False,
        "level": level,
        "next_level": next_level,
    }


def _prepare_synthesis(appid: int, backend: BatchBackend, execution_id: str) -> dict:
    game = _game_repo.find_by_appid(appid)
    if game is None:
        raise ValueError(f"appid={appid} not in games table")

    merged_row = _merge_repo.find_latest_by_appid(appid)
    if merged_row is None:
        raise ValueError(f"No merged_summary for appid={appid} — run merge phase first")
    from library_layer.models.analyzer_models import MergedSummary

    merged = MergedSummary.model_validate(merged_row["summary_json"])

    # Load the review list needed for compute_sentiment_trend. We only need
    # posted_at + voted_up for trend; the LLM does NOT see raw reviews in
    # the synthesis phase.
    db_reviews = _review_repo.find_by_appid(appid, limit=MAX_REVIEWS)
    reviews = [
        {
            "voted_up": r.voted_up,
            "posted_at": r.posted_at.isoformat() if r.posted_at else None,
        }
        for r in db_reviews
    ]

    velocity = _review_repo.find_review_velocity(appid)
    ea = _review_repo.find_early_access_impact(appid)
    temporal = build_temporal_context(game, velocity, ea)

    from library_layer.utils.scores import compute_hidden_gem_score, compute_sentiment_trend

    hidden_gem_score = compute_hidden_gem_score(
        float(game.positive_pct) if game.positive_pct is not None else None,
        game.review_count or None,
    )
    trend = compute_sentiment_trend(reviews)

    request = build_synthesis_request(
        appid=appid,
        game_name=game.name,
        merged=merged,
        total_reviews=len(db_reviews),
        hidden_gem_score=hidden_gem_score,
        sentiment_trend=trend["trend"],
        sentiment_trend_note=trend["note"],
        steam_positive_pct=float(game.positive_pct) if game.positive_pct is not None else None,
        steam_review_score_desc=game.review_score_desc,
        temporal=temporal,
        metadata=None,
    )
    s3_uri = backend.prepare([request], phase=f"synth-{appid}")
    job_id = backend.submit(s3_uri, task="summarizer", phase=f"synth-{appid}")
    return {
        "appid": appid,
        "phase": "synthesis",
        "execution_id": execution_id,
        "job_id": job_id,
        "skip": False,
    }
