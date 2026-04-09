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
    MERGE_PROMPT_VERSION,
)
from library_layer.config import SteamPulseConfig
from library_layer.events import ReportReadyEvent
from library_layer.llm.batch import BatchBackend
from library_layer.models.analyzer_models import GameReport, MergedSummary, RichChunkSummary
from library_layer.repositories.chunk_summary_repo import ChunkSummaryRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.merged_summary_repo import MergedSummaryRepository
from library_layer.repositories.report_repo import ReportRepository
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
_sns = boto3.client("sns")


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
    job_id = event["job_id"]
    logger.append_keys(appid=appid, phase=phase, execution_id=execution_id)

    backend = _backend_for(execution_id)

    if phase == "chunk":
        return _collect_chunk(appid, backend, job_id)
    if phase == "merge":
        return _collect_merge(appid, backend, job_id)
    if phase == "synthesis":
        return _collect_synthesis(appid, backend, job_id)

    raise ValueError(f"Unknown phase: {phase!r}")


def _collect_chunk(appid: int, backend: BatchBackend, job_id: str) -> dict:
    # We can't know upfront which record_ids are pending — rebuild the
    # response_model map by listing all possible chunk record_ids for this
    # appid. The model is the same for every chunk so a single-entry map
    # with a wildcard lookup works: we read record_ids from the output
    # JSONL directly.
    # Simpler approach: pass a permissive response_models that tries
    # RichChunkSummary for every record_id seen. We do this with a dict
    # that has a __missing__-style default, simulated by pre-populating
    # from the actual JSONL scan inside BatchBackend.collect.
    #
    # For now, we do a two-pass: peek at output to get record_ids, then
    # build the map. Cleaner: extend BatchBackend.collect to accept a
    # single default response_model. For the initial wiring we load chunk
    # indices 0..N by scanning output.
    # Pragmatic shortcut: the backend returns all records it can parse, so
    # we use a single-shot mapping that matches on prefix.
    #
    # Workable implementation: construct a defaultdict-like via dict
    # comprehension after a cheap list of record_ids. We do this via the
    # backend's list_objects path indirectly by calling collect with an
    # empty map first... that won't work. Simplest: use a custom dict
    # subclass.
    results = backend.collect(job_id, default_response_model=RichChunkSummary)

    model_id = _config.model_for("chunking")
    persisted = 0
    # We need chunk_hash + chunk_index + review_count for each result. The
    # record_id encodes chunk_index ("{appid}-chunk-{i}"); rebuilding hash
    # requires the original review set, which we have on hand from the DB.
    from library_layer.repositories.review_repo import ReviewRepository
    from library_layer.utils.chunking import compute_chunk_hash, stratified_chunk_reviews

    review_repo = ReviewRepository(get_conn)
    db_reviews = review_repo.find_by_appid(appid, limit=2000)
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
    chunks = stratified_chunk_reviews(reviews)

    for record_id, summary in results:
        if not isinstance(summary, RichChunkSummary):
            logger.warning("unexpected_type", extra={"record_id": record_id})
            continue
        try:
            chunk_index = int(record_id.rsplit("-", 1)[1])
        except (ValueError, IndexError):
            logger.warning("bad_record_id", extra={"record_id": record_id})
            continue
        if chunk_index >= len(chunks):
            logger.warning("chunk_index_out_of_range", extra={"record_id": record_id})
            continue
        chunk = chunks[chunk_index]
        _chunk_repo.insert(
            appid,
            chunk_index,
            compute_chunk_hash(chunk),
            len(chunk),
            summary,
            model_id=model_id,
            prompt_version=CHUNK_PROMPT_VERSION,
        )
        persisted += 1
    return {"appid": appid, "phase": "chunk", "collected": persisted, "done": False}


def _collect_merge(appid: int, backend: BatchBackend, job_id: str) -> dict:
    """Collect the single-call merge output and persist it.

    Reads the `source_chunk_ids` sidecar written by prepare_phase and
    writes it verbatim into merged_summaries so `find_latest_by_source_ids`
    cache-lookups work on replays. `chunks_merged` is computed from the
    server-side source id list, never trusted from the LLM output.
    """
    results = backend.collect(job_id, default_response_model=MergedSummary)
    if not results:
        raise RuntimeError(f"No merge output for appid={appid}")
    if len(results) != 1:
        logger.warning(
            "merge_unexpected_record_count",
            extra={"appid": appid, "count": len(results)},
        )

    source_chunk_ids = _read_source_ids_sidecar(backend, appid)

    _record_id, merged = results[0]
    if not isinstance(merged, MergedSummary):
        raise TypeError(f"Expected MergedSummary, got {type(merged).__name__}")

    # Server-computed bookkeeping — never trust the LLM for these.
    merged.merge_level = 1
    merged.chunks_merged = len(source_chunk_ids)
    merged.source_chunk_ids = source_chunk_ids

    _merge_repo.insert(
        appid,
        1,
        merged,
        source_chunk_ids,
        len(source_chunk_ids),
        model_id=_config.model_for("merging"),
        prompt_version=MERGE_PROMPT_VERSION,
    )
    return {"appid": appid, "phase": "merge", "collected": 1, "done": False}


def _read_source_ids_sidecar(backend: BatchBackend, appid: int) -> list[int]:
    """Read the sidecar written by prepare_phase._write_source_ids_sidecar."""
    import json as _json

    key = f"jobs/{backend._execution_id}/merge-{appid}/source_chunk_ids.json"
    body = backend._s3.get_object(Bucket=backend._bucket, Key=key)["Body"].read()
    data = _json.loads(body.decode("utf-8"))
    return sorted(int(x) for x in data["source_chunk_ids"])


def _collect_synthesis(appid: int, backend: BatchBackend, job_id: str) -> dict:
    game = _game_repo.find_by_appid(appid)
    if game is None:
        raise ValueError(f"appid={appid} not in games table")

    from library_layer.repositories.review_repo import ReviewRepository

    review_repo = ReviewRepository(get_conn)
    db_reviews = review_repo.find_by_appid(appid, limit=2000)
    trend_reviews = [
        {
            "voted_up": r.voted_up,
            "posted_at": r.posted_at.isoformat() if r.posted_at else None,
        }
        for r in db_reviews
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

    # Populate pipeline bookkeeping columns from the persisted artifacts.
    from library_layer.analyzer import PIPELINE_VERSION

    merged_row = _merge_repo.find_latest_by_appid(appid)
    payload = report.model_dump()
    payload["pipeline_version"] = PIPELINE_VERSION
    payload["merged_summary_id"] = int(merged_row["id"]) if merged_row else None
    payload["chunk_count"] = len(_chunk_repo.find_by_appid(appid, CHUNK_PROMPT_VERSION))
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
