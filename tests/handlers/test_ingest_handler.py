"""Tests for ingest_handler — SQS → S3 fetch → CrawlService → S3 delete."""

import gzip
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import boto3
import pytest
from aws_lambda_powertools.utilities.batch.exceptions import BatchProcessingError
from moto import mock_aws


def _seed_ssm_and_secrets() -> None:
    ssm = boto3.client("ssm", region_name="us-east-1")
    for name, value in {
        "/steampulse/test/messaging/review-crawl-queue-url": "https://sqs.us-east-1.amazonaws.com/123/review-crawl",
        "/steampulse/test/data/assets-bucket-name": "test-assets-bucket",
        "/steampulse/test/messaging/game-events-topic-arn": "arn:aws:sns:us-east-1:123:game-events",
        "/steampulse/test/messaging/content-events-topic-arn": "arn:aws:sns:us-east-1:123:content-events",
    }.items():
        ssm.put_parameter(Name=name, Value=value, Type="String", Overwrite=True)
    sm = boto3.client("secretsmanager", region_name="us-east-1")
    try:
        sm.create_secret(Name="steampulse/test/steam-api-key", SecretString="test-key")
    except sm.exceptions.ResourceExistsException:
        pass


def _get_module() -> Any:
    _seed_ssm_and_secrets()
    import lambda_functions.crawler.ingest_handler as ih
    return ih


def _sqs_event(body: dict) -> dict:
    return {
        "Records": [{
            "messageId": "msg-1",
            "body": json.dumps(body),
            "receiptHandle": "receipt",
        }],
    }


def _gzipped(data: Any) -> bytes:
    return gzip.compress(json.dumps(data).encode())


# ── Routing ─────────────────────────────────────────────────────────────────


@mock_aws
def test_metadata_task_calls_ingest_spoke_metadata(lambda_context: Any) -> None:
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_metadata = AsyncMock(return_value=True)
    ih._s3 = MagicMock()
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped({"details": {"name": "TF2"}}))),
    }

    event = _sqs_event({"appid": 440, "task": "metadata", "s3_key": "spoke-results/metadata/440-abc.json.gz", "count": 1})
    ih.handler(event, lambda_context)

    ih._crawl_service.ingest_spoke_metadata.assert_called_once_with(440, {"details": {"name": "TF2"}})


@mock_aws
def test_reviews_task_calls_ingest_spoke_reviews(lambda_context: Any) -> None:
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_reviews = AsyncMock(return_value=3)
    ih._s3 = MagicMock()
    reviews = [{"review_text": "a"}, {"review_text": "b"}, {"review_text": "c"}]
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped(reviews))),
    }

    event = _sqs_event({"appid": 440, "task": "reviews", "s3_key": "spoke-results/reviews/440-abc.json.gz", "count": 3})
    ih.handler(event, lambda_context)

    ih._crawl_service.ingest_spoke_reviews.assert_called_once_with(440, reviews)


@mock_aws
def test_unknown_task_raises(lambda_context: Any) -> None:
    ih = _get_module()
    ih._s3 = MagicMock()
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped({}))),
    }

    event = _sqs_event({"appid": 440, "task": "bogus", "s3_key": "spoke-results/bogus/440.json.gz", "count": 1})
    # All records failed → BatchProcessingError raised
    with pytest.raises(BatchProcessingError):
        ih.handler(event, lambda_context)


# ── count==0 / no s3_key — skip processing ─────────────────────────────────


@mock_aws
def test_count_zero_skips_s3_and_ingest(lambda_context: Any) -> None:
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._s3 = MagicMock()

    event = _sqs_event({"appid": 440, "task": "metadata", "s3_key": None, "count": 0})
    ih.handler(event, lambda_context)

    ih._s3.get_object.assert_not_called()
    ih._crawl_service.ingest_spoke_metadata.assert_not_called()


@mock_aws
def test_missing_s3_key_skips_processing(lambda_context: Any) -> None:
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._s3 = MagicMock()

    event = _sqs_event({"appid": 440, "task": "reviews", "count": 5})
    ih.handler(event, lambda_context)

    ih._s3.get_object.assert_not_called()


# ── S3 delete after successful ingest ───────────────────────────────────────


@mock_aws
def test_s3_object_deleted_after_metadata_ingest(lambda_context: Any) -> None:
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_metadata = AsyncMock(return_value=True)
    ih._s3 = MagicMock()
    s3_key = "spoke-results/metadata/440-abc.json.gz"
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped({"details": {}}))),
    }

    event = _sqs_event({"appid": 440, "task": "metadata", "s3_key": s3_key, "count": 1})
    ih.handler(event, lambda_context)

    ih._s3.delete_object.assert_called_once_with(Bucket=ih._assets_bucket_name, Key=s3_key)


@mock_aws
def test_s3_object_deleted_after_reviews_ingest(lambda_context: Any) -> None:
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_reviews = AsyncMock(return_value=2)
    ih._s3 = MagicMock()
    s3_key = "spoke-results/reviews/440-abc.json.gz"
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped([{"r": 1}, {"r": 2}]))),
    }

    event = _sqs_event({"appid": 440, "task": "reviews", "s3_key": s3_key, "count": 2})
    ih.handler(event, lambda_context)

    ih._s3.delete_object.assert_called_once_with(Bucket=ih._assets_bucket_name, Key=s3_key)


@mock_aws
def test_s3_not_deleted_on_ingest_failure(lambda_context: Any) -> None:
    """If ingest raises, S3 object should NOT be deleted (batch failure → retry)."""
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_metadata = AsyncMock(side_effect=RuntimeError("db error"))
    ih._s3 = MagicMock()
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped({"details": {}}))),
    }

    event = _sqs_event({"appid": 440, "task": "metadata", "s3_key": "spoke-results/metadata/440-abc.json.gz", "count": 1})
    # All records failed → BatchProcessingError raised
    with pytest.raises(BatchProcessingError):
        ih.handler(event, lambda_context)

    ih._s3.delete_object.assert_not_called()


@mock_aws
def test_s3_not_deleted_when_count_zero(lambda_context: Any) -> None:
    ih = _get_module()
    ih._s3 = MagicMock()

    event = _sqs_event({"appid": 440, "task": "metadata", "s3_key": None, "count": 0})
    ih.handler(event, lambda_context)

    ih._s3.delete_object.assert_not_called()
