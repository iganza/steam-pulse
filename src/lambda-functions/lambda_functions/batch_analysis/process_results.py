"""ProcessResults Lambda — parse Pass 2 output, upsert reports, publish events.

Input:  {pass2_output_s3_uri: str, execution_id: str}
Output: {processed: int, failed: int, failed_appids: list[int]}
"""

import json
import os
import re

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.parameters import get_parameter
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.models.analyzer_models import GameReport
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.services.revenue_estimator import compute_estimate
from library_layer.utils.db import get_conn

logger = Logger(service="batch-process-results")
tracer = Tracer(service="batch-process-results")

_s3 = boto3.client("s3")
_sns = boto3.client("sns")

_content_events_topic_arn = get_parameter(os.environ["CONTENT_EVENTS_TOPIC_PARAM_NAME"])
_system_events_topic_arn = get_parameter(os.environ["SYSTEM_EVENTS_TOPIC_PARAM_NAME"])

_BUCKET = os.environ["BATCH_BUCKET_NAME"]

# recordId format: "{appid}-synthesis"
_RECORD_ID_RE = re.compile(r"^(\d+)-synthesis$")


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parts = uri.removeprefix("s3://").split("/", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def _list_output_objects(bucket: str, prefix: str) -> list[str]:
    paginator = _s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def _read_jsonl_from_s3(bucket: str, key: str) -> list[dict]:
    resp = _s3.get_object(Bucket=bucket, Key=key)
    records = []
    for line in resp["Body"].iter_lines():
        if isinstance(line, bytes):
            line = line.decode()
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _read_scores_from_s3(execution_id: str) -> dict[str, dict]:
    scores_key = f"jobs/{execution_id}/pass2/scores.json"
    try:
        resp = _s3.get_object(Bucket=_BUCKET, Key=scores_key)
        return json.loads(resp["Body"].read().decode())
    except Exception as exc:
        logger.warning("could not read scores.json, using LLM values", extra={"error": str(exc)})
        return {}


def _update_revenue_estimates(
    game_repo: GameRepository,
    tag_repo: TagRepository,
    appids: list[int],
) -> None:
    """Compute + persist Boxleiter revenue estimates for a batch of appids.

    Best-effort: any per-appid exception (estimator edge case, bad tag data,
    missing row) is logged and skipped so a single bad record cannot poison
    the rest of the batch. Uses the bulk genre/tag fetchers so we issue two
    queries total for the lookup side instead of two per appid, and a single
    bulk UPDATE + commit at the end.
    """
    genres_by_appid = tag_repo.find_genres_for_appids(appids)
    tags_by_appid = tag_repo.find_tags_for_appids(appids)
    updates: list[tuple[int, int | None, object, str | None]] = []
    for appid in appids:
        try:
            game = game_repo.find_for_revenue_estimate(appid)
            if game is None:
                continue
            estimate = compute_estimate(
                game,
                genres_by_appid.get(appid, []),
                tags_by_appid.get(appid, []),
            )
            updates.append(
                (
                    appid,
                    estimate.estimated_owners,
                    estimate.estimated_revenue_usd,
                    estimate.method,
                )
            )
            logger.info(
                "revenue estimate computed",
                extra={
                    "appid": appid,
                    "owners": estimate.estimated_owners,
                    "revenue_usd": float(estimate.estimated_revenue_usd)
                    if estimate.estimated_revenue_usd is not None
                    else None,
                    "reason": estimate.reason,
                },
            )
        except Exception:
            logger.exception(
                "revenue estimate failed; continuing with next appid",
                extra={"appid": appid},
            )
    # Single commit for the whole batch — avoids per-row transaction overhead.
    try:
        game_repo.bulk_update_revenue_estimates(updates)  # type: ignore[arg-type]
    except Exception:
        logger.exception(
            "bulk revenue estimate update failed",
            extra={"batch_size": len(updates)},
        )


@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    pass2_output_s3_uri: str = event["pass2_output_s3_uri"]
    execution_id: str = event["execution_id"]

    bucket, prefix = _parse_s3_uri(pass2_output_s3_uri)
    output_keys = _list_output_objects(bucket, prefix)
    scores_by_appid = _read_scores_from_s3(execution_id)

    report_repo = ReportRepository(get_conn)
    game_repo = GameRepository(get_conn)
    tag_repo = TagRepository(get_conn)

    processed = 0
    failed = 0
    failed_appids: list[int] = []
    # Appids whose reports upserted successfully — used for a single bulk
    # revenue-estimate pass after the per-record loop so we can reuse
    # TagRepository's batch helpers instead of N+1 per-record lookups.
    successful_appids: list[int] = []

    for key in output_keys:
        records = _read_jsonl_from_s3(bucket, key)
        for record in records:
            record_id: str = record.get("recordId", "")
            m = _RECORD_ID_RE.match(record_id)
            if not m:
                logger.warning("unrecognised recordId, skipping", extra={"record_id": record_id})
                continue

            appid = int(m.group(1))

            try:
                model_output = record["modelOutput"]
                text = model_output["content"][0]["text"]
                report = GameReport.model_validate_json(text)

                # Override with Python-computed scores from PreparePass2
                pre_computed = scores_by_appid.get(str(appid))
                if pre_computed:
                    report.hidden_gem_score = pre_computed["hidden_gem_score"]
                    report.sentiment_trend = pre_computed["sentiment_trend"]
                    report.sentiment_trend_note = pre_computed["sentiment_trend_note"]
                    report.sentiment_trend_reliable = pre_computed.get(
                        "sentiment_trend_reliable", False
                    )
                    report.sentiment_trend_sample_size = pre_computed.get(
                        "sentiment_trend_sample_size", 0
                    )

                report.appid = appid
                report_repo.upsert(report.model_dump())

                # Update velocity cache if available
                velocity = pre_computed.get("review_velocity_lifetime") if pre_computed else None
                if velocity is not None:
                    game_repo.update_velocity_cache(appid, velocity)

                successful_appids.append(appid)

                # Publish report-ready event per game
                _sns.publish(
                    TopicArn=_content_events_topic_arn,
                    Message=json.dumps({"event": "report-ready", "appid": appid}),
                    Subject="report-ready",
                )

                processed += 1
                logger.info("report upserted", extra={"appid": appid})

            except Exception as exc:
                logger.error("failed to process record", extra={"appid": appid, "error": str(exc)})
                failed += 1
                failed_appids.append(appid)

    # Boxleiter v1 revenue estimates — gross, pre-Steam-cut, +/-50%.
    # Single bulk pass after record processing so we can reuse the bulk
    # genre/tag repo helpers and avoid N+1 per-record queries. Backend
    # persists unconditionally; Pro-gating is frontend-only.
    #
    # Revenue estimates are strictly additive — a failure here must NOT
    # block batch-complete signalling or fail the Lambda invocation. The
    # helper is already best-effort per-appid; this outer guard catches any
    # systemic issue (connection lost, etc.) and keeps the handler alive.
    if successful_appids:
        try:
            _update_revenue_estimates(game_repo, tag_repo, successful_appids)
        except Exception:
            logger.exception(
                "revenue estimate pass failed; continuing to batch-complete",
                extra={
                    "execution_id": execution_id,
                    "successful_appids_count": len(successful_appids),
                },
            )

    # Publish batch-complete event
    _sns.publish(
        TopicArn=_system_events_topic_arn,
        Message=json.dumps(
            {
                "event": "batch-complete",
                "execution_id": execution_id,
                "processed": processed,
                "failed": failed,
                "failed_appids": failed_appids,
            }
        ),
        Subject="batch-complete",
    )

    logger.info("batch complete", extra={"processed": processed, "failed": failed})
    return {"processed": processed, "failed": failed, "failed_appids": failed_appids}
