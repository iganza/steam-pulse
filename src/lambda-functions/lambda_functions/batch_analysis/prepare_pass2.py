"""PreparePass2 Lambda — aggregate Pass 1 signals, compute scores, write Pass 2 JSONL.

Input:  {execution_id: str, pass1_output_s3_uri: str}
Output: {input_s3_uri: str, output_s3_uri: str, total_records: int}
"""

import json
import os
import re

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.analyzer import (
    SYNTHESIS_SYSTEM_PROMPT,
    _aggregate_chunk_summaries,
    _build_synthesis_user_message,
)
from library_layer.models.analyzer_models import ChunkSummary
from library_layer.models.metadata import build_metadata_context
from library_layer.models.temporal import build_temporal_context
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.utils.db import get_conn
from library_layer.utils.scores import (
    compute_hidden_gem_score,
    compute_sentiment_score,
    compute_sentiment_trend,
    sentiment_label,
)

logger = Logger(service="batch-prepare-pass2")
tracer = Tracer(service="batch-prepare-pass2")

_s3 = boto3.client("s3")
_BUCKET = os.environ["BATCH_BUCKET_NAME"]
_SUMMARIZER_MODEL = os.environ["LLM_MODEL__SUMMARIZER"]

# recordId format: "{appid}-chunk-{n}"
_RECORD_ID_RE = re.compile(r"^(\d+)-chunk-\d+$")


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """Parse s3://bucket/key into (bucket, key)."""
    parts = uri.removeprefix("s3://").split("/", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def _list_output_objects(bucket: str, prefix: str) -> list[str]:
    """Return all S3 keys under prefix (Bedrock writes one or more .out files)."""
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


@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    execution_id: str = event["execution_id"]
    pass1_output_s3_uri: str = event["pass1_output_s3_uri"]

    bucket, prefix = _parse_s3_uri(pass1_output_s3_uri)
    output_keys = _list_output_objects(bucket, prefix)
    logger.info("found pass1 output files", extra={"count": len(output_keys)})

    # Group ChunkSummary objects by appid
    chunks_by_appid: dict[int, list[ChunkSummary]] = {}

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
                summary = ChunkSummary.model_validate_json(text)
            except Exception as exc:
                logger.error(
                    "failed to parse chunk summary",
                    extra={"record_id": record_id, "error": str(exc)},
                )
                continue

            chunks_by_appid.setdefault(appid, []).append(summary)

    logger.info("grouped chunks by appid", extra={"games": len(chunks_by_appid)})

    game_repo = GameRepository(get_conn)
    review_repo = ReviewRepository(get_conn)
    tag_repo = TagRepository(get_conn)
    pass2_records: list[dict] = []
    scores_by_appid: dict[str, dict] = {}

    all_appids = list(chunks_by_appid.keys())
    tags_by_appid = tag_repo.find_tags_for_appids(all_appids)
    genres_by_appid = tag_repo.find_genres_for_appids(all_appids)

    for appid, chunks in chunks_by_appid.items():
        aggregated = _aggregate_chunk_summaries(chunks)

        # Compute Python scores
        sentiment_score = compute_sentiment_score(chunks)
        total_reviews = (
            aggregated["total_stats"]["positive_count"]
            + aggregated["total_stats"]["negative_count"]
        )
        hidden_gem_score = compute_hidden_gem_score(total_reviews, sentiment_score)

        # Compute sentiment trend from DB review timestamps
        reviews_for_trend = review_repo.find_by_appid(appid, limit=2000)
        sentiment_trend, sentiment_trend_note = compute_sentiment_trend(
            [r.model_dump() for r in reviews_for_trend]
        )

        # Game must exist — chunks were produced from its reviews, so absence is a data integrity error
        game = game_repo.get_by_appid(appid)

        # Build temporal context from existing repo data
        velocity_data = review_repo.find_review_velocity(appid)
        ea_data = review_repo.find_early_access_impact(appid)
        temporal = build_temporal_context(game, velocity_data, ea_data)

        # Build metadata context from store page data (prefetched above)
        metadata = build_metadata_context(game, tags_by_appid[appid], genres_by_appid[appid])

        # Store pre-computed scores (ProcessResults will use these to override LLM output)
        scores_by_appid[str(appid)] = {
            "sentiment_score": sentiment_score,
            "hidden_gem_score": hidden_gem_score,
            "sentiment_trend": sentiment_trend,
            "sentiment_trend_note": sentiment_trend_note,
            "overall_sentiment": sentiment_label(sentiment_score),
            "review_velocity_lifetime": temporal.review_velocity_lifetime,
        }

        # Format Pass 2 JSONL record
        game_name = game.name
        user_content = _build_synthesis_user_message(
            aggregated,
            game_name,
            total_reviews,
            sentiment_score,
            hidden_gem_score,
            sentiment_trend,
            sentiment_trend_note,
            temporal=temporal,
            metadata=metadata,
        )
        pass2_records.append(
            {
                "recordId": f"{appid}-synthesis",
                "modelInput": {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 5000,
                    "system": SYNTHESIS_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_content}],
                },
            }
        )

    logger.info("prepared pass2 records", extra={"records": len(pass2_records)})

    # Upload scores metadata
    scores_key = f"jobs/{execution_id}/pass2/scores.json"
    _s3.put_object(
        Bucket=_BUCKET,
        Key=scores_key,
        Body=json.dumps(scores_by_appid).encode(),
        ContentType="application/json",
    )

    # Upload Pass 2 JSONL
    input_key = f"jobs/{execution_id}/pass2/input.jsonl"
    body = "\n".join(json.dumps(r) for r in pass2_records)
    _s3.put_object(
        Bucket=_BUCKET, Key=input_key, Body=body.encode(), ContentType="application/x-ndjson"
    )

    input_s3_uri = f"s3://{_BUCKET}/{input_key}"
    output_s3_uri = f"s3://{_BUCKET}/jobs/{execution_id}/pass2/output/"

    logger.info("pass2 input uploaded", extra={"uri": input_s3_uri})
    return {
        "input_s3_uri": input_s3_uri,
        "output_s3_uri": output_s3_uri,
        "total_records": len(pass2_records),
    }
