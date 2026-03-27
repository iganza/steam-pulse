"""PreparePass1 Lambda — read reviews from DB, write Pass 1 JSONL to S3.

Input:  {execution_id: str, appids: list[int] | "ALL_ELIGIBLE"}
Output: {input_s3_uri: str, output_s3_uri: str, total_records: int}
"""

import json
import os

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.analyzer import CHUNK_SIZE, CHUNK_SYSTEM_PROMPT, _build_chunk_user_message
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.utils.db import get_conn

logger = Logger(service="batch-prepare-pass1")
tracer = Tracer(service="batch-prepare-pass1")

_conn = get_conn()
_s3 = boto3.client("s3")
_BUCKET = os.environ["BATCH_BUCKET_NAME"]
_CHUNKING_MODEL = os.environ["LLM_MODEL__CHUNKING"]


def _get_eligible_appids(game_repo: GameRepository) -> list[int]:
    """Return appids for games with at least 50 reviews (batch-eligible)."""
    return [g.appid for g in game_repo.find_eligible_for_reviews(min_reviews=50)]


def _format_chunk_record(appid: int, chunk: list[dict], chunk_index: int, total_chunks: int, game_name: str) -> dict:
    return {
        "recordId": f"{appid}-chunk-{chunk_index}",
        "modelInput": {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "system": CHUNK_SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": _build_chunk_user_message(chunk, chunk_index, total_chunks, game_name),
                }
            ],
        },
    }


@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    execution_id: str = event["execution_id"]
    appids_input = event["appids"]

    game_repo = GameRepository(_conn)
    review_repo = ReviewRepository(_conn)

    if appids_input == "ALL_ELIGIBLE":
        appids = _get_eligible_appids(game_repo)
        logger.info("resolved eligible appids", extra={"count": len(appids)})
    else:
        appids = [int(a) for a in appids_input]

    records: list[dict] = []
    for appid in appids:
        game = game_repo.find_by_appid(appid)
        game_name = game.name if game else str(appid)

        reviews = review_repo.find_by_appid(appid, limit=2000)
        if not reviews:
            logger.info("no reviews, skipping", extra={"appid": appid})
            continue

        # Sort chronologically — earlier reviews as first chunk
        reviews_sorted = sorted(
            [r.model_dump() for r in reviews],
            key=lambda r: r.get("posted_at") or "",
        )

        chunks = [
            reviews_sorted[i : i + CHUNK_SIZE]
            for i in range(0, len(reviews_sorted), CHUNK_SIZE)
        ]
        total_chunks = len(chunks)

        for i, chunk in enumerate(chunks):
            records.append(_format_chunk_record(appid, chunk, i, total_chunks, game_name))

    logger.info("prepared pass1 records", extra={"records": len(records), "appids": len(appids)})

    # Upload JSONL to S3
    input_key = f"jobs/{execution_id}/pass1/input.jsonl"
    body = "\n".join(json.dumps(r) for r in records)
    _s3.put_object(Bucket=_BUCKET, Key=input_key, Body=body.encode(), ContentType="application/x-ndjson")

    input_s3_uri = f"s3://{_BUCKET}/{input_key}"
    output_s3_uri = f"s3://{_BUCKET}/jobs/{execution_id}/pass1/output/"

    logger.info("pass1 input uploaded", extra={"uri": input_s3_uri, "records": len(records)})
    return {"input_s3_uri": input_s3_uri, "output_s3_uri": output_s3_uri, "total_records": len(records)}
