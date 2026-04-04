"""Tests for spoke_handler — SQS-triggered, S3 write, SQS notify, error paths."""

import gzip
import json
from typing import Any
from unittest.mock import MagicMock

import boto3
import pytest
from aws_lambda_powertools.utilities.batch.exceptions import BatchProcessingError
from lambda_functions.crawler.events import (
    MetadataSpokeRequest,
    MetadataSpokeResult,
    ReviewSpokeRequest,
    ReviewSpokeResult,
)
from library_layer.steam_source import SteamAPIError
from moto import mock_aws


def _seed_secrets() -> None:
    sm = boto3.client("secretsmanager", region_name="us-east-1")
    try:
        sm.create_secret(Name="steampulse/test/steam-api-key", SecretString="test-key")
    except sm.exceptions.ResourceExistsException:
        pass


def _get_handler_module() -> Any:
    _seed_secrets()
    import lambda_functions.crawler.spoke_handler as sh

    return sh


def _sqs_event(payload: dict) -> dict:
    """Wrap a payload dict in an SQS event envelope (single record)."""
    return {
        "Records": [
            {
                "messageId": "test-msg-1",
                "receiptHandle": "test-handle",
                "body": json.dumps(payload),
                "attributes": {},
                "messageAttributes": {},
                "md5OfBody": "",
                "eventSource": "aws:sqs",
                "eventSourceARN": "arn:aws:sqs:us-west-2:123456789012:test-queue",
                "awsRegion": "us-west-2",
            }
        ]
    }


# ── Routing ─────────────────────────────────────────────────────────────────


@mock_aws
def test_metadata_task_calls_get_app_details(lambda_context: Any) -> None:
    sh = _get_handler_module()
    sh._steam = MagicMock()
    sh._steam.get_app_details = MagicMock(return_value={"name": "TF2", "type": "game"})
    sh._steam.get_review_summary = MagicMock(return_value={"total_reviews": 100})
    sh._steam.get_deck_compatibility = MagicMock(return_value=None)
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    event = _sqs_event(MetadataSpokeRequest(appid=440).model_dump())
    result = sh.handler(event, lambda_context)

    assert result["batchItemFailures"] == []
    sh._steam.get_app_details.assert_called_once_with(440)


@mock_aws
def test_reviews_task_calls_get_reviews(lambda_context: Any) -> None:
    sh = _get_handler_module()
    sh._steam = MagicMock()
    sh._steam.get_reviews = MagicMock(return_value=([{"review_text": "great"}], None))
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    event = _sqs_event(ReviewSpokeRequest(appid=440).model_dump())
    result = sh.handler(event, lambda_context)

    assert result["batchItemFailures"] == []
    sh._steam.get_reviews.assert_called_once_with(440, max_reviews=sh.BATCH_SIZE, start_cursor="*")


@mock_aws
def test_unknown_task_reports_batch_failure(lambda_context: Any) -> None:
    sh = _get_handler_module()

    event = _sqs_event({"appid": 440, "task": "bogus"})
    with pytest.raises(BatchProcessingError):
        sh.handler(event, lambda_context)


# ── S3 write + SQS notify ──────────────────────────────────────────────────


@mock_aws
def test_metadata_writes_gzipped_json_to_s3(lambda_context: Any) -> None:
    sh = _get_handler_module()
    details = {"name": "TF2", "type": "game"}
    sh._steam = MagicMock()
    sh._steam.get_app_details = MagicMock(return_value=details)
    sh._steam.get_review_summary = MagicMock(return_value={"total_reviews": 100})
    sh._steam.get_deck_compatibility = MagicMock(return_value=None)
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    sh.handler(_sqs_event(MetadataSpokeRequest(appid=440).model_dump()), lambda_context)

    put_call = sh._s3.put_object.call_args
    assert put_call[1]["Key"].startswith("spoke-results/metadata/440-")
    assert put_call[1]["Key"].endswith(".json.gz")
    assert put_call[1]["ContentEncoding"] == "gzip"

    body = json.loads(gzip.decompress(put_call[1]["Body"]))
    assert body["details"] == details


@mock_aws
def test_metadata_sends_sqs_notification_with_s3_key(lambda_context: Any) -> None:
    sh = _get_handler_module()
    sh._steam = MagicMock()
    sh._steam.get_app_details = MagicMock(return_value={"name": "TF2"})
    sh._steam.get_review_summary = MagicMock(return_value={})
    sh._steam.get_deck_compatibility = MagicMock(return_value=None)
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    sh.handler(_sqs_event(MetadataSpokeRequest(appid=440).model_dump()), lambda_context)

    sqs_call = sh._sqs.send_message.call_args
    msg = MetadataSpokeResult.model_validate_json(sqs_call[1]["MessageBody"])
    assert msg.appid == 440
    assert msg.task == "metadata"
    assert msg.success is True
    assert msg.s3_key is not None
    assert msg.s3_key.startswith("spoke-results/metadata/440-")
    assert msg.count == 1


@mock_aws
def test_reviews_writes_to_s3_and_notifies(lambda_context: Any) -> None:
    sh = _get_handler_module()
    reviews = [{"review_text": "good"}, {"review_text": "bad"}]
    sh._steam = MagicMock()
    sh._steam.get_reviews = MagicMock(return_value=(reviews, "cursor123"))
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    sh.handler(_sqs_event(ReviewSpokeRequest(appid=440).model_dump()), lambda_context)

    put_call = sh._s3.put_object.call_args
    assert put_call[1]["Key"].startswith("spoke-results/reviews/440-")
    body = json.loads(gzip.decompress(put_call[1]["Body"]))
    assert len(body) == 2

    sqs_call = sh._sqs.send_message.call_args
    msg = ReviewSpokeResult.model_validate_json(sqs_call[1]["MessageBody"])
    assert msg.count == 2
    assert msg.success is True
    assert msg.s3_key == put_call[1]["Key"]
    assert msg.next_cursor == "cursor123"


@mock_aws
def test_reviews_exhausted_sends_none_cursor(lambda_context: Any) -> None:
    sh = _get_handler_module()
    reviews = [{"review_text": "good"}]
    sh._steam = MagicMock()
    sh._steam.get_reviews = MagicMock(return_value=(reviews, None))
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    sh.handler(_sqs_event(ReviewSpokeRequest(appid=440).model_dump()), lambda_context)

    sqs_call = sh._sqs.send_message.call_args
    msg = ReviewSpokeResult.model_validate_json(sqs_call[1]["MessageBody"])
    assert msg.next_cursor is None


@mock_aws
def test_reviews_with_cursor_and_max_reviews(lambda_context: Any) -> None:
    sh = _get_handler_module()
    sh._steam = MagicMock()
    sh._steam.get_reviews = MagicMock(return_value=([{"r": 1}], None))
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    sh.handler(
        _sqs_event(
            ReviewSpokeRequest(appid=440, cursor="saved_cursor", max_reviews=2000).model_dump()
        ),
        lambda_context,
    )

    sh._steam.get_reviews.assert_called_once_with(
        440, max_reviews=min(2000, sh.BATCH_SIZE), start_cursor="saved_cursor"
    )


# ── Error paths ─────────────────────────────────────────────────────────────


@mock_aws
def test_metadata_steam_api_error_notifies_failure(lambda_context: Any) -> None:
    sh = _get_handler_module()
    sh._steam = MagicMock()
    sh._steam.get_app_details = MagicMock(side_effect=SteamAPIError("rate limited"))
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    result = sh.handler(_sqs_event(MetadataSpokeRequest(appid=440).model_dump()), lambda_context)

    assert result["batchItemFailures"] == []
    sh._s3.put_object.assert_not_called()
    msg = MetadataSpokeResult.model_validate_json(sh._sqs.send_message.call_args[1]["MessageBody"])
    assert msg.success is False
    assert msg.s3_key is None
    assert msg.error is not None


@mock_aws
def test_metadata_empty_details_notifies_failure(lambda_context: Any) -> None:
    sh = _get_handler_module()
    sh._steam = MagicMock()
    sh._steam.get_app_details = MagicMock(return_value=None)
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    result = sh.handler(_sqs_event(MetadataSpokeRequest(appid=440).model_dump()), lambda_context)

    assert result["batchItemFailures"] == []
    sh._s3.put_object.assert_not_called()


@mock_aws
def test_reviews_steam_api_error_notifies_failure(lambda_context: Any) -> None:
    sh = _get_handler_module()
    sh._steam = MagicMock()
    sh._steam.get_reviews = MagicMock(side_effect=SteamAPIError("rate limited"))
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    result = sh.handler(_sqs_event(ReviewSpokeRequest(appid=440).model_dump()), lambda_context)

    assert result["batchItemFailures"] == []
    sh._s3.put_object.assert_not_called()


@mock_aws
def test_reviews_empty_list_notifies_failure(lambda_context: Any) -> None:
    sh = _get_handler_module()
    sh._steam = MagicMock()
    sh._steam.get_reviews = MagicMock(return_value=([], None))
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    result = sh.handler(_sqs_event(ReviewSpokeRequest(appid=440).model_dump()), lambda_context)

    assert result["batchItemFailures"] == []
    sh._s3.put_object.assert_not_called()


# ── S3 key uniqueness ──────────────────────────────────────────────────────


@mock_aws
def test_s3_keys_are_unique_across_invocations(lambda_context: Any) -> None:
    sh = _get_handler_module()
    sh._steam = MagicMock()
    sh._steam.get_app_details = MagicMock(return_value={"name": "TF2"})
    sh._steam.get_review_summary = MagicMock(return_value={})
    sh._steam.get_deck_compatibility = MagicMock(return_value=None)
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    sh.handler(_sqs_event(MetadataSpokeRequest(appid=440).model_dump()), lambda_context)
    sh.handler(_sqs_event(MetadataSpokeRequest(appid=440).model_dump()), lambda_context)

    keys = [call[1]["Key"] for call in sh._s3.put_object.call_args_list]
    assert len(keys) == 2
    assert keys[0] != keys[1]
