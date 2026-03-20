"""Tests for spoke_handler — direct invocation, S3 write, SQS notify, error paths."""

import gzip
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import boto3
import pytest
from lambda_functions.crawler.events import SpokeRequest, SpokeResponse, SpokeResult
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


# ── Routing ─────────────────────────────────────────────────────────────────


@mock_aws
def test_metadata_task_calls_get_app_details(lambda_context: Any) -> None:
    sh = _get_handler_module()
    sh._steam = MagicMock()
    sh._steam.get_app_details = AsyncMock(return_value={"name": "TF2", "type": "game"})
    sh._steam.get_review_summary = AsyncMock(return_value={"total_reviews": 100})
    sh._steam.get_deck_compatibility = AsyncMock(return_value=None)
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    result = sh.handler(SpokeRequest(appid=440, task="metadata").model_dump(), lambda_context)

    resp = SpokeResponse.model_validate(result)
    assert resp.appid == 440
    assert resp.task == "metadata"
    assert resp.success is True
    assert resp.count == 1
    sh._steam.get_app_details.assert_called_once_with(440)


@mock_aws
def test_reviews_task_calls_get_reviews(lambda_context: Any) -> None:
    sh = _get_handler_module()
    sh._steam = MagicMock()
    sh._steam.get_reviews = AsyncMock(return_value=[{"review_text": "great"}])
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    result = sh.handler(SpokeRequest(appid=440, task="reviews").model_dump(), lambda_context)

    resp = SpokeResponse.model_validate(result)
    assert resp.appid == 440
    assert resp.task == "reviews"
    assert resp.success is True
    assert resp.count == 1
    sh._steam.get_reviews.assert_called_once_with(440, max_reviews=None)


@mock_aws
def test_unknown_task_raises(lambda_context: Any) -> None:
    from pydantic import ValidationError

    sh = _get_handler_module()

    with pytest.raises(ValidationError):
        sh.handler({"appid": 440, "task": "bogus"}, lambda_context)


# ── S3 write + SQS notify ──────────────────────────────────────────────────


@mock_aws
def test_metadata_writes_gzipped_json_to_s3(lambda_context: Any) -> None:
    sh = _get_handler_module()
    details = {"name": "TF2", "type": "game"}
    sh._steam = MagicMock()
    sh._steam.get_app_details = AsyncMock(return_value=details)
    sh._steam.get_review_summary = AsyncMock(return_value={"total_reviews": 100})
    sh._steam.get_deck_compatibility = AsyncMock(return_value=None)
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    sh.handler(SpokeRequest(appid=440, task="metadata").model_dump(), lambda_context)

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
    sh._steam.get_app_details = AsyncMock(return_value={"name": "TF2"})
    sh._steam.get_review_summary = AsyncMock(return_value={})
    sh._steam.get_deck_compatibility = AsyncMock(return_value=None)
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    sh.handler(SpokeRequest(appid=440, task="metadata").model_dump(), lambda_context)

    sqs_call = sh._sqs.send_message.call_args
    msg = SpokeResult.model_validate_json(sqs_call[1]["MessageBody"])
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
    sh._steam.get_reviews = AsyncMock(return_value=reviews)
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    sh.handler(SpokeRequest(appid=440, task="reviews").model_dump(), lambda_context)

    put_call = sh._s3.put_object.call_args
    assert put_call[1]["Key"].startswith("spoke-results/reviews/440-")
    body = json.loads(gzip.decompress(put_call[1]["Body"]))
    assert len(body) == 2

    sqs_call = sh._sqs.send_message.call_args
    msg = SpokeResult.model_validate_json(sqs_call[1]["MessageBody"])
    assert msg.count == 2
    assert msg.success is True
    assert msg.s3_key == put_call[1]["Key"]


# ── Error paths ─────────────────────────────────────────────────────────────


@mock_aws
def test_metadata_steam_api_error_returns_failure(lambda_context: Any) -> None:
    sh = _get_handler_module()
    sh._steam = MagicMock()
    sh._steam.get_app_details = AsyncMock(side_effect=SteamAPIError("rate limited"))
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    result = sh.handler(SpokeRequest(appid=440, task="metadata").model_dump(), lambda_context)

    resp = SpokeResponse.model_validate(result)
    assert resp.success is False
    assert resp.count == 0
    sh._s3.put_object.assert_not_called()
    # Still notifies with success=False and error reason
    msg = SpokeResult.model_validate_json(sh._sqs.send_message.call_args[1]["MessageBody"])
    assert msg.success is False
    assert msg.s3_key is None
    assert msg.error is not None


@mock_aws
def test_metadata_empty_details_returns_failure(lambda_context: Any) -> None:
    sh = _get_handler_module()
    sh._steam = MagicMock()
    sh._steam.get_app_details = AsyncMock(return_value=None)
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    result = sh.handler(SpokeRequest(appid=440, task="metadata").model_dump(), lambda_context)

    resp = SpokeResponse.model_validate(result)
    assert resp.success is False
    sh._s3.put_object.assert_not_called()


@mock_aws
def test_reviews_steam_api_error_returns_zero(lambda_context: Any) -> None:
    sh = _get_handler_module()
    sh._steam = MagicMock()
    sh._steam.get_reviews = AsyncMock(side_effect=SteamAPIError("rate limited"))
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    result = sh.handler(SpokeRequest(appid=440, task="reviews").model_dump(), lambda_context)

    resp = SpokeResponse.model_validate(result)
    assert resp.success is False
    assert resp.count == 0
    sh._s3.put_object.assert_not_called()


@mock_aws
def test_reviews_empty_list_returns_zero(lambda_context: Any) -> None:
    sh = _get_handler_module()
    sh._steam = MagicMock()
    sh._steam.get_reviews = AsyncMock(return_value=[])
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    result = sh.handler(SpokeRequest(appid=440, task="reviews").model_dump(), lambda_context)

    resp = SpokeResponse.model_validate(result)
    assert resp.success is False
    assert resp.count == 0
    sh._s3.put_object.assert_not_called()


# ── S3 key uniqueness ──────────────────────────────────────────────────────


@mock_aws
def test_s3_keys_are_unique_across_invocations(lambda_context: Any) -> None:
    sh = _get_handler_module()
    sh._steam = MagicMock()
    sh._steam.get_app_details = AsyncMock(return_value={"name": "TF2"})
    sh._steam.get_review_summary = AsyncMock(return_value={})
    sh._steam.get_deck_compatibility = AsyncMock(return_value=None)
    sh._s3 = MagicMock()
    sh._sqs = MagicMock()

    sh.handler(SpokeRequest(appid=440, task="metadata").model_dump(), lambda_context)
    sh.handler(SpokeRequest(appid=440, task="metadata").model_dump(), lambda_context)

    keys = [call[1]["Key"] for call in sh._s3.put_object.call_args_list]
    assert len(keys) == 2
    assert keys[0] != keys[1]
