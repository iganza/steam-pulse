"""CollectPhase Lambda — collect Anthropic batch output and persist.

Runs after the status poller reports "completed" for a phase. Iterates
batch results via AnthropicBatchBackend.collect(), parses responses into
typed pydantic models, and persists them through the SAME repositories
the realtime path uses (chunk_repo, merge_repo, report_repo).

Input:
    {
        "appid": 440,
        "phase": "chunk" | "merge" | "synthesis",
        "execution_id": "...",
        "job_id": "msgbatch_01abc...",
        "merged_summary_id": 99,     # synthesis only
        "chunk_count": 7,            # synthesis only
        "merge_level": 1,            # merge only
        "group_meta": [...],         # merge only
        "cached_group_meta": [...]   # merge only
    }

Output (chunk):
    {"appid": 440, "phase": "chunk", "collected": <int>, "done": false}

Output (merge):
    {"merged_summary_id": <int|null>, "merged_ids": [...], ...}

Output (synthesis):
    {"appid": 440, "phase": "synthesis", "collected": 1, "done": true}
"""

import os
from decimal import Decimal

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.parameters import get_parameter
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.analyzer import (
    CHUNK_PROMPT_VERSION,
    MERGE_PROMPT_VERSION,
    PIPELINE_VERSION,
    parse_chunk_record_id,
    parse_merge_record_id,
)
from library_layer.config import SteamPulseConfig
from library_layer.events import ReportReadyEvent
from library_layer.llm import make_batch_backend
from library_layer.llm.anthropic_batch import AnthropicBatchBackend
from library_layer.llm.backend import estimate_batch_cost_usd
from library_layer.models.analyzer_models import GameReport, MergedSummary, RichChunkSummary
from library_layer.repositories.batch_execution_repo import BatchExecutionRepository
from library_layer.repositories.chunk_summary_repo import ChunkSummaryRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.merged_summary_repo import MergedSummaryRepository
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

_game_repo = GameRepository(get_conn)
_chunk_repo = ChunkSummaryRepository(get_conn)
_merge_repo = MergedSummaryRepository(get_conn)
_report_repo = ReportRepository(get_conn)
_review_repo = ReviewRepository(get_conn)
_batch_exec_repo = BatchExecutionRepository(get_conn)
_sns = boto3.client("sns")


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
    job_id = event["job_id"]
    logger.append_keys(appid=appid, phase=phase, execution_id=execution_id)

    backend = _backend_for(execution_id)

    if phase == "chunk":
        return _collect_chunk(appid, backend, job_id)
    if phase == "merge":
        merge_level = int(event["merge_level"])
        group_meta = event["group_meta"]
        cached_group_meta = event.get("cached_group_meta", [])
        return _collect_merge(appid, backend, job_id, merge_level, group_meta, cached_group_meta)
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
    raise ValueError(f"Unknown phase: {phase!r}")


def _collect_chunk(appid: int, backend: AnthropicBatchBackend, job_id: str) -> dict:
    """Persist chunk_summaries rows from a completed chunking batch job.

    The prepare_phase Lambda encodes (chunk_index, chunk_size, chunk_hash)
    into each request's `record_id`. We parse those fields out here
    instead of re-chunking the current DB review set — the review set
    may have grown between prepare and collect (Bedrock Batch jobs run
    for hours), which would shift chunk membership and corrupt chunk_hash
    cache keys.
    """
    try:
        collect_result = backend.collect(job_id, default_response_model=RichChunkSummary)
        model_id = _config.model_for("chunking")
        persisted = 0
        dropped_ids: list[str] = []

        for record_id, summary in collect_result.results:
            if not isinstance(summary, RichChunkSummary):
                logger.warning("unexpected_type", extra={"record_id": record_id})
                dropped_ids.append(record_id)
                continue
            parsed = parse_chunk_record_id(record_id)
            if parsed is None:
                # parse_chunk_record_id already logged the failure.
                dropped_ids.append(record_id)
                continue
            record_appid, chunk_index, review_count, chunk_hash = parsed
            if record_appid != appid:
                logger.warning(
                    "record_id_appid_mismatch",
                    extra={"record_id": record_id, "expected": appid, "got": record_appid},
                )
                dropped_ids.append(record_id)
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

        all_failed_ids = collect_result.failed_ids + dropped_ids
        # failed_count matches len(all_failed_ids) so the tracking table
        # is internally consistent. The backend's skipped count can include
        # unkeyed records (malformed JSON, missing recordId) not in
        # failed_ids — log it for observability but don't inflate the count.
        failed_count = len(all_failed_ids)
        if failed_count or collect_result.skipped:
            _sample = 10
            logger.error(
                "batch_chunk_records_failed",
                extra={
                    "appid": appid,
                    "job_id": job_id,
                    "api_failed_count": len(collect_result.failed_ids),
                    "api_failed_ids_sample": collect_result.failed_ids[:_sample],
                    "dropped_count": len(dropped_ids),
                    "dropped_ids_sample": dropped_ids[:_sample],
                    "skipped": collect_result.skipped,
                },
            )

        cost = estimate_batch_cost_usd(
            model_id=_config.model_for("chunking"),
            input_tokens=collect_result.input_tokens,
            output_tokens=collect_result.output_tokens,
            cache_read_tokens=collect_result.cache_read_tokens,
            cache_write_tokens=collect_result.cache_write_tokens,
        )

        # Always record token usage and cost first — even if every record
        # failed validation, the API consumed tokens and we need the cost.
        try:
            _batch_exec_repo.mark_completed(
                job_id,
                succeeded_count=persisted,
                failed_count=failed_count,
                failed_record_ids=all_failed_ids,
                input_tokens=collect_result.input_tokens,
                output_tokens=collect_result.output_tokens,
                cache_read_tokens=collect_result.cache_read_tokens,
                cache_write_tokens=collect_result.cache_write_tokens,
                estimated_cost_usd=Decimal(str(round(cost, 4))),
            )
        except Exception:
            logger.exception(
                "batch_execution_mark_completed_failed",
                extra={"appid": appid, "job_id": job_id},
            )

        # Any chunk failures mean the merge/synthesis phases would operate
        # on an incomplete review set — fail the pipeline so it retries
        # cleanly. Tokens/cost are already recorded above.
        if failed_count > 0:
            reason = (
                f"{failed_count}/{persisted + failed_count} chunk records failed "
                f"({persisted} persisted) for appid={appid}"
            )
            try:
                _batch_exec_repo.mark_failed(job_id, failure_reason=reason)
            except Exception:
                logger.exception(
                    "batch_execution_mark_failed_failed",
                    extra={"appid": appid, "job_id": job_id},
                )
            raise RuntimeError(reason)
    except Exception as exc:
        try:
            _batch_exec_repo.mark_failed(
                job_id,
                failure_reason=f"Chunk collect failed for appid={appid}: {exc}",
            )
        except Exception:
            logger.exception(
                "batch_execution_mark_failed_failed",
                extra={"appid": appid, "job_id": job_id},
            )
        raise

    return {"appid": appid, "phase": "chunk", "collected": persisted, "done": False}


def _collect_merge(
    appid: int,
    backend: AnthropicBatchBackend,
    job_id: str,
    merge_level: int,
    group_meta: list[dict],
    cached_group_meta: list[dict],
) -> dict:
    """Persist MergedSummary rows from a completed merge batch job.

    ``group_meta`` carries the source_chunk_ids per group, threaded from
    prepare via SFN state. ``cached_group_meta`` lists groups that were
    already persisted in prepare (cache hits); their merge_ids are merged
    with freshly collected results to determine whether another merge
    level is needed.

    Returns a dict written to ``$.merge`` by the state machine. The key
    fields are ``merged_summary_id`` (set when a single root remains)
    and ``merged_ids`` (all row IDs produced at this level, consumed by
    the next level's prepare).
    """
    meta_by_index = {int(gm["group_index"]): gm for gm in group_meta}
    model_id = _config.model_for("merging")
    # Track persisted IDs keyed by group_index so the output list is
    # deterministic (matches the original group order from prepare).
    # Non-deterministic ordering would change grouping at the next merge
    # level and reduce cache hit rates.
    persisted_by_index: dict[int, int] = {}
    already_failed = False

    try:
        collect_result = backend.collect(job_id, default_response_model=MergedSummary)
        dropped_ids: list[str] = []

        for record_id, summary in collect_result.results:
            if not isinstance(summary, MergedSummary):
                logger.warning("unexpected_type", extra={"record_id": record_id})
                dropped_ids.append(record_id)
                continue
            parsed = parse_merge_record_id(record_id)
            if parsed is None:
                dropped_ids.append(record_id)
                continue
            record_appid, level, group_index = parsed
            if record_appid != appid:
                logger.warning(
                    "record_id_appid_mismatch",
                    extra={"record_id": record_id, "expected": appid, "got": record_appid},
                )
                dropped_ids.append(record_id)
                continue
            if level != merge_level:
                logger.warning(
                    "record_id_level_mismatch",
                    extra={
                        "record_id": record_id,
                        "expected_level": merge_level,
                        "got_level": level,
                    },
                )
                dropped_ids.append(record_id)
                continue
            gm = meta_by_index.get(group_index)
            if gm is None:
                logger.warning(
                    "merge_group_meta_missing",
                    extra={"record_id": record_id, "group_index": group_index},
                )
                dropped_ids.append(record_id)
                continue

            source_chunk_ids = sorted(int(x) for x in gm["source_chunk_ids"])
            # Server-computed bookkeeping — never trust the LLM.
            summary.merge_level = merge_level
            summary.chunks_merged = len(source_chunk_ids)
            summary.source_chunk_ids = source_chunk_ids
            row_id = _merge_repo.insert(
                appid,
                merge_level,
                summary,
                source_chunk_ids,
                len(source_chunk_ids),
                model_id=model_id,
                prompt_version=MERGE_PROMPT_VERSION,
            )
            persisted_by_index[group_index] = row_id

        all_failed_ids = collect_result.failed_ids + dropped_ids
        failed_count = len(all_failed_ids)
        if failed_count or collect_result.skipped:
            _sample = 10
            logger.error(
                "batch_merge_records_failed",
                extra={
                    "appid": appid,
                    "job_id": job_id,
                    "api_failed_count": len(collect_result.failed_ids),
                    "api_failed_ids_sample": collect_result.failed_ids[:_sample],
                    "dropped_count": len(dropped_ids),
                    "dropped_ids_sample": dropped_ids[:_sample],
                    "skipped": collect_result.skipped,
                },
            )

        cost = estimate_batch_cost_usd(
            model_id=_config.model_for("merging"),
            input_tokens=collect_result.input_tokens,
            output_tokens=collect_result.output_tokens,
            cache_read_tokens=collect_result.cache_read_tokens,
            cache_write_tokens=collect_result.cache_write_tokens,
        )
        try:
            _batch_exec_repo.mark_completed(
                job_id,
                succeeded_count=len(persisted_by_index),
                failed_count=failed_count,
                failed_record_ids=all_failed_ids,
                input_tokens=collect_result.input_tokens,
                output_tokens=collect_result.output_tokens,
                cache_read_tokens=collect_result.cache_read_tokens,
                cache_write_tokens=collect_result.cache_write_tokens,
                estimated_cost_usd=Decimal(str(round(cost, 4))),
            )
        except Exception:
            logger.exception(
                "batch_execution_mark_completed_failed",
                extra={"appid": appid, "job_id": job_id},
            )

        if failed_count > 0:
            reason = (
                f"{failed_count}/{len(persisted_by_index) + failed_count} merge records "
                f"failed ({len(persisted_by_index)} persisted) for appid={appid}"
            )
            try:
                _batch_exec_repo.mark_failed(job_id, failure_reason=reason)
            except Exception:
                logger.exception(
                    "batch_execution_mark_failed_failed",
                    extra={"appid": appid, "job_id": job_id},
                )
            already_failed = True
            raise RuntimeError(reason)

    except Exception as exc:
        if not already_failed:
            try:
                _batch_exec_repo.mark_failed(
                    job_id,
                    failure_reason=f"Merge collect failed for appid={appid}: {exc}",
                )
            except Exception:
                logger.exception(
                    "batch_execution_mark_failed_failed",
                    extra={"appid": appid, "job_id": job_id},
                )
        raise

    # Build merged_ids in group_index order (persisted + cached) so the
    # next merge level groups them deterministically and maximises cache hits.
    cached_by_index = {int(cg["group_index"]): int(cg["merge_id"]) for cg in cached_group_meta}
    id_by_index = {**cached_by_index, **persisted_by_index}
    all_merged_ids = [id_by_index[k] for k in sorted(id_by_index)]

    if len(all_merged_ids) == 1:
        merged_summary_id = all_merged_ids[0]
    else:
        merged_summary_id = None

    logger.info(
        "merge_collect_complete",
        extra={
            "appid": appid,
            "merge_level": merge_level,
            "persisted": len(persisted_by_index),
            "cached": len(cached_group_meta),
            "total_merged": len(all_merged_ids),
            "merged_summary_id": merged_summary_id,
        },
    )
    return {
        "appid": appid,
        "phase": "merge",
        "merged_summary_id": merged_summary_id,
        "merged_ids": all_merged_ids,
    }


def _collect_synthesis(
    appid: int,
    backend: AnthropicBatchBackend,
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

    collect_result = backend.collect(job_id, default_response_model=GameReport)

    # Always record token usage and cost first — even on failure, the API
    # consumed tokens and we need the cost tracked.
    cost = estimate_batch_cost_usd(
        model_id=_config.model_for("summarizer"),
        input_tokens=collect_result.input_tokens,
        output_tokens=collect_result.output_tokens,
        cache_read_tokens=collect_result.cache_read_tokens,
        cache_write_tokens=collect_result.cache_write_tokens,
    )
    try:
        _batch_exec_repo.mark_completed(
            job_id,
            succeeded_count=len(collect_result.results),
            failed_count=len(collect_result.failed_ids),
            failed_record_ids=collect_result.failed_ids,
            input_tokens=collect_result.input_tokens,
            output_tokens=collect_result.output_tokens,
            cache_read_tokens=collect_result.cache_read_tokens,
            cache_write_tokens=collect_result.cache_write_tokens,
            estimated_cost_usd=Decimal(str(round(cost, 4))),
        )
    except Exception:
        logger.exception(
            "batch_execution_mark_completed_failed",
            extra={"appid": appid, "job_id": job_id},
        )

    try:
        if not collect_result.results:
            raise RuntimeError(f"No synthesis output for appid={appid}")
        _record_id, report = collect_result.results[0]
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
    except Exception as exc:
        try:
            _batch_exec_repo.mark_failed(
                job_id,
                failure_reason=f"Synthesis collect failed for appid={appid}: {exc}",
            )
        except Exception:
            logger.exception(
                "batch_execution_mark_failed_failed",
                extra={"appid": appid, "job_id": job_id},
            )
        raise

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
