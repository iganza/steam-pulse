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
        "skip": false  # true if cache hit — no Bedrock job needed, state
                       # machine short-circuits directly to the next phase
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
    CHUNK_PROMPT_VERSION,
    AnalyzerSettings,
    build_chunk_requests,
    build_synthesis_request,
    run_merge_phase,
)
from library_layer.config import SteamPulseConfig
from library_layer.llm.batch import BatchBackend
from library_layer.llm.converse import ConverseBackend
from library_layer.models.analyzer_models import MergedSummary, RichChunkSummary
from library_layer.models.metadata import build_metadata_context
from library_layer.models.temporal import build_temporal_context
from library_layer.repositories.chunk_summary_repo import ChunkSummaryRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.merged_summary_repo import MergedSummaryRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.utils.chunking import dataset_reference_time
from library_layer.utils.db import get_conn
from library_layer.utils.scores import compute_hidden_gem_score, compute_sentiment_trend

logger = Logger(service="batch-prepare-phase")
tracer = Tracer(service="batch-prepare-phase")

_config = SteamPulseConfig()
_BATCH_BUCKET = os.environ["BATCH_BUCKET_NAME"]
_BATCH_ROLE_ARN = os.environ["BEDROCK_BATCH_ROLE_ARN"]

_game_repo = GameRepository(get_conn)
_review_repo = ReviewRepository(get_conn)
_chunk_repo = ChunkSummaryRepository(get_conn)
_merge_repo = MergedSummaryRepository(get_conn)
_tag_repo = TagRepository(get_conn)

# All analyzer tuning knobs (including max-reviews-per-analysis) come from
# SteamPulseConfig. No hardcoded module constants here.
_analyzer_settings = AnalyzerSettings.from_config(_config)

# Module-level ConverseBackend singleton — used by _prepare_merge which
# runs the merge phase inline. Building instructor/AnthropicBedrock on
# every invocation would defeat Lambda warm-start reuse.
_converse_backend = ConverseBackend(
    _config,
    max_workers=_config.ANALYSIS_CONVERSE_MAX_WORKERS,
)


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
        return _prepare_merge(appid, backend, execution_id)
    if phase == "synthesis":
        # `merged_summary_id` is threaded in from the state machine —
        # it's the id `_prepare_merge` returned for THIS execution, so
        # synthesis does not race on find_latest_by_appid under
        # concurrent re-analysis for the same appid.
        raw = event.get("merged_summary_id")
        merge_id = int(raw) if raw is not None else None
        return _prepare_synthesis(appid, backend, execution_id, merge_id)

    raise ValueError(f"Unknown phase: {phase!r}")


def _prepare_chunk(appid: int, backend: BatchBackend, execution_id: str) -> dict:
    game = _game_repo.find_by_appid(appid)
    if game is None:
        raise ValueError(f"appid={appid} not in games table")

    max_reviews = _config.ANALYSIS_MAX_REVIEWS
    logger.info("loading_reviews", extra={"appid": appid, "max_reviews": max_reviews})
    db_reviews = _review_repo.find_by_appid(appid, limit=max_reviews)
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

    cached_rows = _chunk_repo.find_by_appid(appid, CHUNK_PROMPT_VERSION)
    cached_hashes = {row["chunk_hash"] for row in cached_rows}
    _chunks, pending, _pending_meta = build_chunk_requests(
        appid=appid,
        game_name=game.name,
        reviews=reviews,
        cached_hashes=cached_hashes,
        chunk_size=_analyzer_settings.chunk_size,
        reference_time=dataset_reference_time(reviews),
        shuffle_seed=_analyzer_settings.shuffle_seed,
        chunk_max_tokens=_analyzer_settings.chunk_max_tokens,
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


def _prepare_merge(appid: int, backend: BatchBackend, execution_id: str) -> dict:
    """Run the merge phase INLINE via ConverseBackend and short-circuit the
    Step Functions wait loop.

    Merge is bounded by `MAX_CHUNKS_PER_MERGE_CALL * number_of_levels`
    LLM calls, each of which runs in seconds via sync Converse. Even for
    very large games (hundreds of chunks, 2 merge levels) this completes
    well within a Lambda timeout. Running merge inline — instead of
    spinning up a Bedrock Batch Inference job — means:

      * We share ONE `run_merge_phase` implementation with the realtime
        path, so hierarchical merge behavior and source_chunk_ids
        tracking cannot drift between paths.
      * The Step Functions state machine does not need a per-level loop;
        batch merge is always a single "skip=true" transition from the
        state machine's perspective.
      * We avoid the overhead of writing merge inputs to S3, submitting a
        batch job, and polling for completion — Bedrock Batch Inference
        is designed to amortize fixed per-job cost across many records,
        and merge has at most a handful.

    Bedrock Batch Inference is still used for the CHUNK phase (which has
    tens of records per game) and the SYNTHESIS phase.
    """
    game = _game_repo.find_by_appid(appid)
    if game is None:
        raise ValueError(f"appid={appid} not in games table")

    rows = _chunk_repo.find_by_appid(appid, CHUNK_PROMPT_VERSION)
    if not rows:
        raise ValueError(
            f"merge prep: no chunk_summaries for appid={appid} — run chunk phase first"
        )

    summaries = [RichChunkSummary.model_validate(r["summary_json"]) for r in rows]
    chunk_ids = [int(r["id"]) for r in rows]

    _merged, merged_summary_id = run_merge_phase(
        appid=appid,
        game_name=game.name,
        chunk_summaries=summaries,
        chunk_ids=chunk_ids,
        backend=_converse_backend,
        merge_repo=_merge_repo,
        max_chunks_per_merge_call=_analyzer_settings.max_chunks_per_merge_call,
        merge_max_tokens=_analyzer_settings.merge_max_tokens,
    )
    logger.info(
        "merge_prepare_inline_complete",
        extra={"chunks": len(summaries), "merged_summary_id": merged_summary_id},
    )
    return {
        "appid": appid,
        "phase": "merge",
        "execution_id": execution_id,
        "job_id": None,
        "skip": True,
        # Threaded forward to PrepareSynthesis via the state machine so
        # synthesis reads the exact merge row THIS execution produced,
        # not whatever `find_latest_by_appid` returns under a concurrent
        # re-analysis. Same bookkeeping pattern as the synthesis →
        # collect `merged_summary_id` / `chunk_count` threading.
        "merged_summary_id": merged_summary_id,
    }


def _prepare_synthesis(
    appid: int,
    backend: BatchBackend,
    execution_id: str,
    merged_summary_id: int | None,
) -> dict:
    game = _game_repo.find_by_appid(appid)
    if game is None:
        raise ValueError(f"appid={appid} not in games table")

    # The state machine threads `merged_summary_id` forward from
    # PrepareMerge, so we read the exact row that execution wrote.
    # If it's missing (old state machine deployment, hand-invoked test)
    # we fall back to the latest row for the appid — non-concurrent
    # paths are unaffected.
    if merged_summary_id is not None:
        merged_row = _merge_repo.find_by_id(merged_summary_id)
        if merged_row is None:
            raise ValueError(
                f"merged_summary id={merged_summary_id} not found for appid={appid}"
            )
    else:
        merged_row = _merge_repo.find_latest_by_appid(appid)
        if merged_row is None:
            raise ValueError(
                f"No merged_summary for appid={appid} — run merge phase first"
            )
        merged_summary_id = int(merged_row["id"])
    merged = MergedSummary.model_validate(merged_row["summary_json"])

    # Same race fix for chunk_count: capture "how many chunks fed this
    # synthesis" at prepare time and thread it through SFN state so the
    # collect phase can write it verbatim, instead of re-counting rows
    # that may have shifted between prepare and collect (concurrent
    # re-analysis, CHUNK_PROMPT_VERSION bump, etc.).
    chunk_count = len(_chunk_repo.find_by_appid(appid, CHUNK_PROMPT_VERSION))

    # Load the review list needed for compute_sentiment_trend. We only need
    # posted_at + voted_up for trend; the LLM does NOT see raw reviews in
    # the synthesis phase. Filter to reviews with non-empty bodies to
    # match the chunk-phase filter — otherwise `total_reviews_analyzed`
    # in the final report would claim more reviews than actually fed
    # the merged summary.
    db_reviews = _review_repo.find_by_appid(appid, limit=_config.ANALYSIS_MAX_REVIEWS)
    reviews = [
        {
            "voted_up": r.voted_up,
            "posted_at": r.posted_at.isoformat() if r.posted_at else None,
        }
        for r in db_reviews
        if r.body
    ]

    velocity = _review_repo.find_review_velocity(appid)
    ea = _review_repo.find_early_access_impact(appid)
    temporal = build_temporal_context(game, velocity, ea)

    # Store-page/metadata context — see analysis/handler.py for the
    # rationale. Without this both the metadata context block and the
    # store_page_alignment section of the synthesis prompt are dead code.
    tags = _tag_repo.find_tags_for_game(appid)
    genres = _tag_repo.find_genres_for_game(appid)
    metadata = build_metadata_context(game, tags, genres)

    hidden_gem_score = compute_hidden_gem_score(
        float(game.positive_pct) if game.positive_pct is not None else None,
        game.review_count or None,
    )
    trend = compute_sentiment_trend(reviews)

    request = build_synthesis_request(
        appid=appid,
        game_name=game.name,
        merged=merged,
        total_reviews=len(reviews),
        hidden_gem_score=hidden_gem_score,
        sentiment_trend=trend["trend"],
        sentiment_trend_note=trend["note"],
        steam_positive_pct=float(game.positive_pct) if game.positive_pct is not None else None,
        steam_review_score_desc=game.review_score_desc,
        temporal=temporal,
        metadata=metadata,
        synthesis_max_tokens=_analyzer_settings.synthesis_max_tokens,
    )
    s3_uri = backend.prepare([request], phase=f"synth-{appid}")
    job_id = backend.submit(s3_uri, task="summarizer", phase=f"synth-{appid}")
    return {
        "appid": appid,
        "phase": "synthesis",
        "execution_id": execution_id,
        "job_id": job_id,
        "skip": False,
        # Threaded through SFN state into the collect-phase payload so the
        # report's merged_summary_id points at the row we actually used,
        # not whatever find_latest_by_appid happens to return later.
        "merged_summary_id": merged_summary_id,
        # Same rationale — chunk_count reflects the persisted chunk set at
        # prepare time, not a racy re-count in collect.
        "chunk_count": chunk_count,
    }
