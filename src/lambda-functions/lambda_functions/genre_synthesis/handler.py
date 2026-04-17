"""Lambda handler — Phase-4 cross-genre LLM synthesizer.

Two event shapes handled:

  1. EventBridge weekly scan: `{"action": "scan_stale"}` → find slugs whose
     mv_genre_synthesis row is older than GENRE_SYNTHESIS_MAX_AGE_DAYS and
     enqueue one GenreSynthesisJobMessage per stale slug on the synthesis
     queue. Scans only — no LLM call in this path.

  2. SQS (genre-synthesis-queue) records: each record is a
     GenreSynthesisJobMessage (JSON body). The handler calls
     GenreSynthesisService.synthesize(slug=..., prompt_version=...) which
     short-circuits on input_hash cache hits and otherwise runs one
     Bedrock Sonnet tool_use call.
"""

from __future__ import annotations

import json
import os

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response,
)
from aws_lambda_powertools.utilities.parameters import get_parameter
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.config import SteamPulseConfig
from library_layer.events import GenreSynthesisJobMessage
from library_layer.llm import make_converse_backend
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.genre_synthesis_repo import (
    GenreSynthesisRepository,
)
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.services.genre_synthesis_service import (
    GenreSynthesisService,
    NotEnoughReportsError,
)
from library_layer.utils.db import get_conn

logger = Logger(service="genre_synthesis")
tracer = Tracer(service="genre_synthesis")
metrics = Metrics(namespace="SteamPulse", service="genre_synthesis")

# ── Module-level wiring (built at cold start; fails loud on misconfig) ──────
_config = SteamPulseConfig()
metrics.set_default_dimensions(environment=_config.ENVIRONMENT)

_report_repo = ReportRepository(get_conn)
_tag_repo = TagRepository(get_conn)
_game_repo = GameRepository(get_conn)
_synthesis_repo = GenreSynthesisRepository(get_conn)

# Single-call backend; max_workers=1 and max_retries=0 are fine — we run
# exactly one LLMRequest per invocation, and the caller (SQS) owns retry
# semantics via DLQ after 3 receive attempts.
_llm_backend = make_converse_backend(_config, max_workers=1, max_retries=0)

_service = GenreSynthesisService(
    report_repo=_report_repo,
    tag_repo=_tag_repo,
    game_repo=_game_repo,
    synthesis_repo=_synthesis_repo,
    llm_backend=_llm_backend,
    config=_config,
    metrics=metrics,
)

_sqs = boto3.client("sqs")
_sqs_processor = BatchProcessor(event_type=EventType.SQS)

# Resolve the synthesis queue URL at cold start. Only required when the
# Lambda is running in AWS — the scan_stale path is the only caller that
# needs it, and local unit tests don't exercise that path.
_queue_url: str = ""
if _config.GENRE_SYNTHESIS_QUEUE_PARAM_NAME and os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    _queue_url = get_parameter(_config.GENRE_SYNTHESIS_QUEUE_PARAM_NAME)


def _scan_stale() -> dict:
    """Find stale synthesis rows and enqueue one job per slug."""
    if not _queue_url:
        raise RuntimeError(
            "GENRE_SYNTHESIS_QUEUE_PARAM_NAME resolved to empty — "
            "scan_stale cannot enqueue. Check SSM param."
        )
    stale = _synthesis_repo.find_stale(_config.GENRE_SYNTHESIS_MAX_AGE_DAYS)
    logger.info("stale_slugs", extra={"count": len(stale), "slugs": stale})
    for slug in stale:
        msg = GenreSynthesisJobMessage(
            slug=slug,
            prompt_version=_config.GENRE_SYNTHESIS_PROMPT_VERSION,
        )
        _sqs.send_message(QueueUrl=_queue_url, MessageBody=msg.model_dump_json())
    metrics.add_metric(
        name="GenreSynthesisStaleEnqueued",
        unit=MetricUnit.Count,
        value=len(stale),
    )
    return {"stale_enqueued": len(stale)}


def _handle_sqs_record(record: dict) -> None:
    """Parse one SQS record into a GenreSynthesisJobMessage and run synth."""
    body = json.loads(record["body"])
    msg = GenreSynthesisJobMessage.model_validate(body)
    logger.append_keys(slug=msg.slug, prompt_version=msg.prompt_version)
    try:
        _service.synthesize(slug=msg.slug, prompt_version=msg.prompt_version)
    except NotEnoughReportsError as exc:
        # Don't retry: the genre doesn't have enough analyzed games yet.
        # The next weekly scan will re-evaluate. Log and mark success so
        # SQS drops the message (avoids DLQ churn).
        logger.warning(
            "genre_synthesis_skipped_insufficient_reports",
            extra={"slug": msg.slug, "error": str(exc)},
        )
        metrics.add_metric(
            name="GenreSynthesisSkipped", unit=MetricUnit.Count, value=1
        )


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    # EventBridge scheduled trigger — stale scan.
    if event.get("action") == "scan_stale" or event.get("source") == "aws.events":
        logger.info("scan_stale trigger")
        return _scan_stale()

    # SQS batch — one message per slug to synthesize.
    if "Records" in event:
        logger.info("SQS batch", extra={"record_count": len(event["Records"])})
        return process_partial_response(
            event=event,
            record_handler=_handle_sqs_record,
            processor=_sqs_processor,
            context=context,
        )

    raise ValueError(f"Unrecognised event shape: {list(event.keys())}")
