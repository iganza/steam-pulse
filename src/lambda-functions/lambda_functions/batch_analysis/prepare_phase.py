"""PreparePhase Lambda — thin wrapper over shared analyzer helpers + AnthropicBatchBackend.

Per-game Step Functions execution: one appid per invocation. Parent orchestrator
uses a Map state to fan out across an appid list. Parametrized by `phase` so
the same handler services chunk / merge / synthesis preparation:

Input:
    {
        "appid": 440,
        "phase": "chunk" | "merge" | "synthesis",
        "execution_id": "sp-batch-20260409-abcd",
        "merged_summary_id": 99,  # synthesis only, threaded from merge phase
        "merge_level": 1,         # merge only, 1 or 2
        "merged_ids": [10, 20]    # merge L2 only, from L1 collect/skip
    }

Output (phase == "chunk" | "synthesis", skip=false):
    {
        "appid": 440,
        "phase": "<phase>",
        "execution_id": "...",
        "job_id": "msgbatch_01abc...",
        "skip": false
    }

Output (phase == "chunk" | "synthesis", skip=true — cache hit):
    {
        "appid": 440,
        "phase": "<phase>",
        "execution_id": "...",
        "job_id": null,
        "skip": true
    }

Output (phase == "merge", skip=true — single result, converged):
    {
        "appid": 440,
        "phase": "merge",
        "execution_id": "...",
        "job_id": null,
        "skip": true,
        "merge_level": 1,
        "merged_summary_id": 42,        # set when single result
        "merged_ids": [42]              # always present on skip
    }

Output (phase == "merge", skip=true — all groups cached, not yet converged):
    {
        "appid": 440,
        "phase": "merge",
        "execution_id": "...",
        "job_id": null,
        "skip": true,
        "merge_level": 1,
        "merged_summary_id": null,       # null — needs another level
        "merged_ids": [42, 43, ...]      # cached merge IDs to drive L2
    }

Output (phase == "merge", skip=false — batch submitted):
    {
        "appid": 440,
        "phase": "merge",
        "execution_id": "...",
        "job_id": "msgbatch_01abc...",
        "skip": false,
        "merge_level": 1,
        "group_meta": [...],            # threaded to collect
        "cached_group_meta": [...]      # groups already persisted
    }

    Note: merged_ids and merged_summary_id are produced by collect on
    the skip=false path, not by prepare.

When `skip=true`, Step Functions should short-circuit the Wait/Check loop for
this phase and proceed directly to the next phase.

"Job still pending" is Step Functions state, NEVER an exception. This Lambda
returns immediately after submit; the polling loop lives in the state machine
(see infra/stacks/batch_analysis_stack.py).
"""

import os

import psycopg2.extensions
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.analyzer import (
    CHUNK_PROMPT_VERSION,
    MERGE_PROMPT_VERSION,
    PIPELINE_VERSION,
    SYNTHESIS_PROMPT_VERSION,
    AnalyzerSettings,
    build_chunk_requests,
    build_merge_record_id,
    build_merge_request,
    build_synthesis_request,
    compute_merge_groups,
    merged_as_chunk_like,
    promote_single_chunk,
)
from library_layer.config import SteamPulseConfig
from library_layer.llm import make_batch_backend
from library_layer.llm.anthropic_batch import AnthropicBatchBackend
from library_layer.models.analyzer_models import MergedSummary, RichChunkSummary
from library_layer.models.metadata import build_metadata_context
from library_layer.models.temporal import build_temporal_context
from library_layer.repositories.batch_execution_repo import BatchExecutionRepository
from library_layer.repositories.chunk_summary_repo import ChunkSummaryRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.merged_summary_repo import MergedSummaryRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.utils.chunking import dataset_reference_time
from library_layer.utils.db import get_conn, run_with_retrying_transaction, transaction
from library_layer.utils.scores import compute_hidden_gem_score, compute_sentiment_trend

logger = Logger(service="batch-prepare-phase")
tracer = Tracer(service="batch-prepare-phase")

_config = SteamPulseConfig()
_BATCH_BUCKET = os.environ["BATCH_BUCKET_NAME"]
_BATCH_ROLE_ARN = os.environ["BEDROCK_BATCH_ROLE_ARN"]
_BATCH_CONNECT_TIMEOUT = 60  # cold-start burst tolerance


def _get_batch_conn() -> psycopg2.extensions.connection:
    return get_conn(connect_timeout=_BATCH_CONNECT_TIMEOUT, max_connect_attempts=3)


_game_repo = GameRepository(_get_batch_conn)
_review_repo = ReviewRepository(_get_batch_conn)
_chunk_repo = ChunkSummaryRepository(_get_batch_conn)
_merge_repo = MergedSummaryRepository(_get_batch_conn)
_report_repo = ReportRepository(_get_batch_conn)
_tag_repo = TagRepository(_get_batch_conn)
_batch_exec_repo = BatchExecutionRepository(_get_batch_conn)

# All analyzer tuning knobs (including max-reviews-per-analysis) come from
# SteamPulseConfig. No hardcoded module constants here.
_analyzer_settings = AnalyzerSettings.from_config(_config)


def _backend_for(execution_id: str) -> AnthropicBatchBackend:
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
    logger.append_keys(appid=appid, phase=phase, execution_id=execution_id)

    backend = _backend_for(execution_id)

    if phase == "chunk":
        return _prepare_chunk(appid, backend, execution_id)
    if phase == "merge":
        raw_level = event.get("merge_level")
        if raw_level is None:
            raise ValueError("Missing required merge event field: merge_level")
        merge_level = int(raw_level)
        if merge_level not in (1, 2):
            raise ValueError(f"Unsupported merge_level={merge_level}, expected 1 or 2")
        # merged_ids is only present for L2 (threaded from L1 output).
        merged_ids = [int(mid) for mid in event.get("merged_ids", [])]
        return _prepare_merge(appid, backend, execution_id, merge_level, merged_ids)
    if phase == "synthesis":
        # `merged_summary_id` is threaded in from the state machine —
        # it's the id the merge phase returned for THIS execution, so
        # synthesis does not race on find_latest_by_appid under
        # concurrent re-analysis for the same appid.
        raw = event.get("merged_summary_id")
        if raw is None:
            raise ValueError("Missing required synthesis event field: merged_summary_id")
        return _prepare_synthesis(appid, backend, execution_id, int(raw))

    raise ValueError(f"Unknown phase: {phase!r}")


def _prepare_chunk(appid: int, backend: AnthropicBatchBackend, execution_id: str) -> dict:
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
        chunk_temperature=_analyzer_settings.chunk_temperature,
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

    prepared = backend.prepare(pending, phase=f"chunk-{appid}")
    job_id = backend.submit(prepared, task="chunking", phase=f"chunk-{appid}")

    try:
        with transaction(_get_batch_conn()):
            _batch_exec_repo.insert(
                execution_id=execution_id,
                appid=appid,
                phase="chunk",
                backend=_config.LLM_BACKEND,
                batch_id=job_id,
                model_id=_config.model_for("chunking"),
                request_count=len(pending),
                pipeline_version=PIPELINE_VERSION,
                prompt_version=CHUNK_PROMPT_VERSION,
            )
    except Exception:
        logger.exception(
            "batch_execution_tracking_insert_failed",
            extra={
                "appid": appid,
                "execution_id": execution_id,
                "phase": "chunk",
                "job_id": job_id,
            },
        )

    return {
        "appid": appid,
        "phase": "chunk",
        "execution_id": execution_id,
        "job_id": job_id,
        "skip": False,
    }


def _prepare_merge(
    appid: int,
    backend: AnthropicBatchBackend,
    execution_id: str,
    merge_level: int,
    merged_ids: list[int],
) -> dict:
    """Submit merge groups as a batch job via AnthropicBatchBackend.

    Called for both merge levels. Level 1 loads chunk summaries from DB;
    level 2 loads intermediate MergedSummary rows produced by level 1.

    Returns ``skip=true`` when:
    - single chunk (Python promotion, no LLM needed)
    - whole-set cache hit
    - all groups cached at this level and only 1 result
    - level 2 receives a single merged_id (level 1 already converged)
    """
    if merge_level == 2:
        return _prepare_merge_l2(appid, backend, execution_id, merged_ids)

    # ── Level 1: load chunk summaries from DB ──
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

    def _skip_result(merged_summary_id: int) -> dict:
        return {
            "appid": appid,
            "phase": "merge",
            "execution_id": execution_id,
            "job_id": None,
            "skip": True,
            "merge_level": merge_level,
            "merged_summary_id": merged_summary_id,
            "merged_ids": [merged_summary_id],
        }

    # Single-chunk: Python promotion, no LLM call.
    if len(summaries) == 1:
        cached_promotion = _merge_repo.find_latest_by_source_ids(
            appid, [chunk_ids[0]], MERGE_PROMPT_VERSION
        )
        if cached_promotion is not None:
            logger.info(
                "merge_prepare_single_chunk_cache_hit",
                extra={"appid": appid, "merge_id": int(cached_promotion["id"])},
            )
            return _skip_result(int(cached_promotion["id"]))

        merged = promote_single_chunk(summaries[0], source_chunk_id=chunk_ids[0])
        row_id = run_with_retrying_transaction(
            _merge_repo.conn,
            lambda: _merge_repo.insert(
                appid,
                0,
                merged,
                [chunk_ids[0]],
                1,
                model_id="python-promotion",
                prompt_version=MERGE_PROMPT_VERSION,
            ),
        )
        logger.info(
            "merge_prepare_single_chunk_promoted",
            extra={"appid": appid, "merge_id": row_id},
        )
        return _skip_result(row_id)

    # Whole-set cache hit.
    cached = _merge_repo.find_latest_by_source_ids(appid, chunk_ids, MERGE_PROMPT_VERSION)
    if cached is not None:
        logger.info(
            "merge_prepare_whole_set_cache_hit",
            extra={"appid": appid, "merge_id": int(cached["id"])},
        )
        return _skip_result(int(cached["id"]))

    # Compute groups + per-group cache.
    return _submit_merge_batch(
        appid=appid,
        game_name=game.name,
        summaries=summaries,
        source_id_sets=[[cid] for cid in chunk_ids],
        backend=backend,
        execution_id=execution_id,
        merge_level=1,
    )


def _prepare_merge_l2(
    appid: int,
    backend: AnthropicBatchBackend,
    execution_id: str,
    merged_ids: list[int],
) -> dict:
    """Prepare merge level 2: load level-1 intermediates and merge them."""

    def _skip_result(merged_summary_id: int) -> dict:
        return {
            "appid": appid,
            "phase": "merge",
            "execution_id": execution_id,
            "job_id": None,
            "skip": True,
            "merge_level": 2,
            "merged_summary_id": merged_summary_id,
            "merged_ids": [merged_summary_id],
        }

    if not merged_ids:
        raise ValueError("merge L2: no merged_ids from level 1")

    # If level 1 already converged to a single result, skip.
    if len(merged_ids) == 1:
        logger.info(
            "merge_l2_prepare_single_input_skip",
            extra={"appid": appid, "merged_summary_id": merged_ids[0]},
        )
        return _skip_result(merged_ids[0])

    game = _game_repo.find_by_appid(appid)
    if game is None:
        raise ValueError(f"appid={appid} not in games table")

    # Load level-1 intermediates by their row IDs (race-free).
    intermediates: list[RichChunkSummary] = []
    source_id_sets: list[list[int]] = []
    for mid in merged_ids:
        row = _merge_repo.find_by_id(mid)
        if row is None:
            raise ValueError(f"merge L2: intermediate row {mid} not found")
        ms = MergedSummary.model_validate(row["summary_json"])
        intermediates.append(merged_as_chunk_like(ms))
        # Transitive leaf IDs from the intermediate's source_chunk_ids.
        source_id_sets.append(sorted(row["source_chunk_ids"]))

    # Whole-set cache check (all leaf IDs across all intermediates).
    all_leaf_ids = sorted({lid for ids in source_id_sets for lid in ids})
    cached = _merge_repo.find_latest_by_source_ids(appid, all_leaf_ids, MERGE_PROMPT_VERSION)
    if cached is not None:
        logger.info(
            "merge_l2_prepare_whole_set_cache_hit",
            extra={"appid": appid, "merge_id": int(cached["id"])},
        )
        return _skip_result(int(cached["id"]))

    return _submit_merge_batch(
        appid=appid,
        game_name=game.name,
        summaries=intermediates,
        source_id_sets=source_id_sets,
        backend=backend,
        execution_id=execution_id,
        merge_level=2,
    )


def _submit_merge_batch(
    *,
    appid: int,
    game_name: str,
    summaries: list[RichChunkSummary],
    source_id_sets: list[list[int]],
    backend: AnthropicBatchBackend,
    execution_id: str,
    merge_level: int,
) -> dict:
    """Shared logic for level 1 and level 2 merge batch submission."""
    plan = compute_merge_groups(
        appid=appid,
        chunk_summaries=summaries,
        source_id_sets=source_id_sets,
        merge_repo=_merge_repo,
        max_chunks_per_merge_call=_analyzer_settings.max_chunks_per_merge_call,
    )

    # If all groups are cached, short-circuit.
    if not plan.pending:
        if len(plan.cached) == 1:
            cg = plan.cached[0]
            logger.info(
                "merge_prepare_all_cached_single",
                extra={"appid": appid, "merge_id": cg.merge_id, "level": merge_level},
            )
            return {
                "appid": appid,
                "phase": "merge",
                "execution_id": execution_id,
                "job_id": None,
                "skip": True,
                "merge_level": merge_level,
                "merged_summary_id": cg.merge_id,
                "merged_ids": [cg.merge_id],
            }
        # Multiple cached groups: need another level to converge.
        # At L1 this is fine — L2 will process them. At L2 this would
        # require a third level, which means >1600 chunks (>80k reviews).
        # No Steam game reaches this; fail fast rather than silently
        # passing null merged_summary_id to synthesis.
        if merge_level >= 2:
            raise RuntimeError(
                f"Merge L{merge_level}: {len(plan.cached)} cached groups remain "
                f"after all groups resolved — would need level {merge_level + 1} "
                f"which exceeds the 2-level limit. appid={appid}"
            )
        return {
            "appid": appid,
            "phase": "merge",
            "execution_id": execution_id,
            "job_id": None,
            "skip": True,
            "merge_level": merge_level,
            "merged_summary_id": None,
            "merged_ids": [cg.merge_id for cg in plan.cached],
        }

    # At L2, the total group count (pending + cached) must be 1 after
    # the batch completes — otherwise we'd need a third merge level.
    # Fail fast here rather than producing a null merged_summary_id that
    # crashes the state machine at synthesis.
    total_groups = len(plan.pending) + len(plan.cached)
    if merge_level >= 2 and total_groups > 1:
        raise RuntimeError(
            f"Merge L{merge_level}: {total_groups} groups "
            f"({len(plan.pending)} pending, {len(plan.cached)} cached) — "
            f"would need level {merge_level + 1} which exceeds the 2-level "
            f"limit. appid={appid}"
        )

    # Build LLMRequests for pending groups.
    pending_requests = []
    group_meta = []
    for mg in plan.pending:
        request = build_merge_request(
            appid=appid,
            game_name=game_name,
            summaries=mg.summaries,
            record_id=build_merge_record_id(appid, merge_level, mg.group_index),
            merge_max_tokens=_analyzer_settings.merge_max_tokens,
            merge_temperature=_analyzer_settings.merge_temperature,
        )
        pending_requests.append(request)
        group_meta.append(
            {
                "group_index": mg.group_index,
                "source_chunk_ids": mg.source_chunk_ids,
            }
        )

    cached_group_meta = [
        {"group_index": cg.group_index, "merge_id": cg.merge_id} for cg in plan.cached
    ]

    prepared = backend.prepare(pending_requests, phase=f"merge-{appid}-L{merge_level}")
    job_id = backend.submit(prepared, task="merging", phase=f"merge-{appid}-L{merge_level}")

    try:
        with transaction(_get_batch_conn()):
            _batch_exec_repo.insert(
                execution_id=execution_id,
                appid=appid,
                phase=f"merge-L{merge_level}",
                backend=_config.LLM_BACKEND,
                batch_id=job_id,
                model_id=_config.model_for("merging"),
                request_count=len(pending_requests),
                pipeline_version=PIPELINE_VERSION,
                prompt_version=MERGE_PROMPT_VERSION,
            )
    except Exception:
        logger.exception(
            "batch_execution_tracking_insert_failed",
            extra={
                "appid": appid,
                "execution_id": execution_id,
                "phase": f"merge-L{merge_level}",
                "job_id": job_id,
            },
        )

    logger.info(
        "merge_prepare_batch_submitted",
        extra={
            "appid": appid,
            "merge_level": merge_level,
            "pending_groups": len(plan.pending),
            "cached_groups": len(plan.cached),
            "job_id": job_id,
        },
    )
    return {
        "appid": appid,
        "phase": "merge",
        "execution_id": execution_id,
        "job_id": job_id,
        "skip": False,
        "merge_level": merge_level,
        "group_meta": group_meta,
        "cached_group_meta": cached_group_meta,
    }


def _prepare_synthesis(
    appid: int,
    backend: AnthropicBatchBackend,
    execution_id: str,
    merged_summary_id: int,
) -> dict:
    # Short-circuit: if a report already exists at the current pipeline
    # version, skip synthesis entirely — no tokens spent.
    if _report_repo.has_current_report(appid, PIPELINE_VERSION):
        logger.info(
            "synthesis_prepare_skipped_current_report",
            extra={"appid": appid, "pipeline_version": PIPELINE_VERSION},
        )
        return {
            "appid": appid,
            "phase": "synthesis",
            "execution_id": execution_id,
            "job_id": None,
            "skip": True,
            "merged_summary_id": merged_summary_id,
            "chunk_count": 0,
        }

    game = _game_repo.find_by_appid(appid)
    if game is None:
        raise ValueError(f"appid={appid} not in games table")

    # The state machine threads `merged_summary_id` forward from
    # PrepareMerge, so we read the exact row that execution wrote.
    merged_row = _merge_repo.find_by_id(merged_summary_id)
    if merged_row is None:
        raise ValueError(f"merged_summary id={merged_summary_id} not found for appid={appid}")
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
        synthesis_temperature=_analyzer_settings.synthesis_temperature,
    )
    prepared = backend.prepare([request], phase=f"synth-{appid}")
    job_id = backend.submit(prepared, task="summarizer", phase=f"synth-{appid}")

    try:
        with transaction(_get_batch_conn()):
            _batch_exec_repo.insert(
                execution_id=execution_id,
                appid=appid,
                phase="synthesis",
                backend=_config.LLM_BACKEND,
                batch_id=job_id,
                model_id=_config.model_for("summarizer"),
                request_count=1,
                pipeline_version=PIPELINE_VERSION,
                prompt_version=SYNTHESIS_PROMPT_VERSION,
            )
    except Exception:
        logger.exception(
            "batch_execution_tracking_insert_failed",
            extra={
                "appid": appid,
                "execution_id": execution_id,
                "phase": "synthesis",
                "job_id": job_id,
            },
        )

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
