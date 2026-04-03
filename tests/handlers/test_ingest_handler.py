"""Tests for ingest_handler — SQS → S3 fetch → CrawlService → S3 delete."""

import gzip
import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import boto3
import pytest
from aws_lambda_powertools.utilities.batch.exceptions import BatchProcessingError
from lambda_functions.crawler.events import MetadataSpokeResult, ReviewSpokeResult, TagsSpokeResult
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


def _sqs_event(result: MetadataSpokeResult | ReviewSpokeResult | TagsSpokeResult) -> dict:
    return {
        "Records": [
            {
                "messageId": "msg-1",
                "body": result.model_dump_json(),
                "receiptHandle": "receipt",
            }
        ],
    }


def _gzipped(data: Any) -> bytes:
    return gzip.compress(json.dumps(data).encode())


def _mock_catalog_and_review_repos(ih: Any, reviews_completed_at: datetime | None = None) -> None:
    """Stub out catalog_repo and review_repo so termination logic doesn't hit DB."""
    ih._catalog_repo = MagicMock()
    ih._catalog_repo.get_reviews_completed_at = MagicMock(return_value=reviews_completed_at)
    ih._review_repo = MagicMock()
    ih._review_repo.count_by_appid = MagicMock(return_value=0)


# ── Routing ─────────────────────────────────────────────────────────────────


@mock_aws
def test_metadata_task_calls_ingest_spoke_metadata(lambda_context: Any) -> None:
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_metadata = MagicMock(return_value=True)
    ih._s3 = MagicMock()
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped({"details": {"name": "TF2"}}))),
    }

    event = _sqs_event(
        MetadataSpokeResult(
            appid=440,
            success=True,
            s3_key="spoke-results/metadata/440-abc.json.gz",
            count=1,
            spoke_region="us-east-1",
        )
    )
    ih.handler(event, lambda_context)

    ih._crawl_service.ingest_spoke_metadata.assert_called_once_with(
        440, {"details": {"name": "TF2"}}
    )


@mock_aws
def test_reviews_task_calls_ingest_spoke_reviews(lambda_context: Any) -> None:
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_reviews = MagicMock(return_value=3)
    ih._s3 = MagicMock()
    reviews = [{"review_text": "a"}, {"review_text": "b"}, {"review_text": "c"}]
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped(reviews))),
    }
    _mock_catalog_and_review_repos(ih)

    event = _sqs_event(
        ReviewSpokeResult(
            appid=440,
            success=True,
            s3_key="spoke-results/reviews/440-abc.json.gz",
            count=3,
            spoke_region="us-east-1",
            next_cursor=None,
        )
    )
    ih.handler(event, lambda_context)

    ih._crawl_service.ingest_spoke_reviews.assert_called_once_with(440, reviews)


@mock_aws
def test_unknown_task_raises(lambda_context: Any) -> None:
    ih = _get_module()
    ih._s3 = MagicMock()

    # Bypass model construction — raw JSON with unknown task
    event = {
        "Records": [
            {
                "messageId": "msg-1",
                "body": json.dumps(
                    {
                        "appid": 440,
                        "task": "bogus",
                        "success": True,
                        "s3_key": "x",
                        "count": 1,
                        "spoke_region": "us-east-1",
                    }
                ),
                "receiptHandle": "receipt",
            }
        ],
    }
    with pytest.raises(BatchProcessingError):
        ih.handler(event, lambda_context)


# ── Cursor management ───────────────────────────────────────────────────────


@mock_aws
def test_reviews_exhausted_marks_complete(lambda_context: Any) -> None:
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_reviews = MagicMock(return_value=500)
    ih._s3 = MagicMock()
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped([]))),
    }
    ih._sqs = MagicMock()
    _mock_catalog_and_review_repos(ih)

    event = _sqs_event(
        ReviewSpokeResult(
            appid=440,
            success=True,
            s3_key="k",
            count=500,
            spoke_region="us-east-1",
            next_cursor=None,
        )
    )
    ih.handler(event, lambda_context)

    ih._catalog_repo.mark_reviews_complete.assert_called_once_with(440, completed_at=None)
    ih._sqs.send_message.assert_not_called()


@mock_aws
def test_early_stop_marks_complete_when_batch_older_than_completed_at(lambda_context: Any) -> None:
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_reviews = MagicMock(return_value=10)
    ih._s3 = MagicMock()
    old_ts = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp())
    reviews = [{"timestamp_created": old_ts}]
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped(reviews))),
    }
    ih._sqs = MagicMock()
    _mock_catalog_and_review_repos(
        ih,
        reviews_completed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    event = _sqs_event(
        ReviewSpokeResult(
            appid=440,
            success=True,
            s3_key="k",
            count=10,
            spoke_region="us-east-1",
            next_cursor="has_more",
        )
    )
    ih.handler(event, lambda_context)

    # On early-stop, completed_at is set to the batch boundary (oldest timestamp in batch)
    expected_boundary = datetime(2023, 1, 1, tzinfo=timezone.utc)
    ih._catalog_repo.mark_reviews_complete.assert_called_once_with(
        440, completed_at=expected_boundary
    )
    ih._sqs.send_message.assert_not_called()


@mock_aws
def test_no_early_stop_on_first_crawl(lambda_context: Any) -> None:
    """First crawl (reviews_completed_at=None) — old timestamps must NOT trigger early-stop."""
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_reviews = MagicMock(return_value=1000)
    ih._s3 = MagicMock()
    old_ts = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
    reviews = [{"timestamp_created": old_ts}]
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped(reviews))),
    }
    ih._sqs = MagicMock()
    _mock_catalog_and_review_repos(ih, reviews_completed_at=None)

    event = _sqs_event(
        ReviewSpokeResult(
            appid=440,
            success=True,
            s3_key="k",
            count=1000,
            spoke_region="us-east-1",
            next_cursor="cursor_abc",
        )
    )
    ih.handler(event, lambda_context)

    ih._catalog_repo.mark_reviews_complete.assert_not_called()
    ih._sqs.send_message.assert_called_once()


@mock_aws
def test_no_early_stop_when_batch_has_new_reviews(lambda_context: Any) -> None:
    """Batch with reviews newer than reviews_completed_at must not early-stop."""
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_reviews = MagicMock(return_value=1000)
    ih._s3 = MagicMock()
    new_ts = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
    reviews = [{"timestamp_created": new_ts}]
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped(reviews))),
    }
    ih._sqs = MagicMock()
    _mock_catalog_and_review_repos(
        ih,
        reviews_completed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    event = _sqs_event(
        ReviewSpokeResult(
            appid=440,
            success=True,
            s3_key="k",
            count=1000,
            spoke_region="us-east-1",
            next_cursor="cursor_abc",
        )
    )
    ih.handler(event, lambda_context)

    ih._catalog_repo.mark_reviews_complete.assert_not_called()
    ih._sqs.send_message.assert_called_once()


@mock_aws
def test_reviews_target_hit_marks_complete(lambda_context: Any) -> None:
    """target <= batch count → budget exhausted → mark_reviews_complete, no re-queue."""
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_reviews = MagicMock(return_value=1000)
    ih._s3 = MagicMock()
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped([]))),
    }
    ih._sqs = MagicMock()
    _mock_catalog_and_review_repos(ih)

    # target=1000 equals batch count=1000 → this batch exhausts the budget
    event = _sqs_event(
        ReviewSpokeResult(
            appid=440,
            success=True,
            s3_key="k",
            count=1000,
            spoke_region="us-east-1",
            next_cursor="cursor_abc",
            target=1000,
        )
    )
    ih.handler(event, lambda_context)

    ih._catalog_repo.mark_reviews_complete.assert_called_once_with(440, completed_at=None)
    ih._sqs.send_message.assert_not_called()


@mock_aws
def test_reviews_more_pages_requeues_with_cursor_in_message(lambda_context: Any) -> None:
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_reviews = MagicMock(return_value=1000)
    ih._s3 = MagicMock()
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped([]))),
    }
    ih._catalog_repo = MagicMock()
    ih._catalog_repo.get_reviews_completed_at = MagicMock(return_value=None)
    ih._review_repo = MagicMock()
    ih._review_repo.count_by_appid = MagicMock(return_value=1000)

    event = _sqs_event(
        ReviewSpokeResult(
            appid=440,
            success=True,
            s3_key="k",
            count=1000,
            spoke_region="us-east-1",
            next_cursor="cursor_abc",
            target=10000,
            started_at="2026-03-26T12:00:00+00:00",
        )
    )
    ih.handler(event, lambda_context)

    ih._sqs.send_message.assert_called_once()
    sent_body = json.loads(ih._sqs.send_message.call_args[1]["MessageBody"])
    # target becomes remaining = 10000 - 1000 = 9000 to prevent overshoot on the final batch
    assert sent_body == {
        "appid": 440,
        "task": "reviews",
        "cursor": "cursor_abc",
        "target": 9000,
        "started_at": "2026-03-26T12:00:00+00:00",
    }
    ih._catalog_repo.save_review_cursor.assert_not_called()


@mock_aws
def test_reviews_two_batch_chain_completes_at_cap(lambda_context: Any) -> None:
    """Two sequential batches: hop 1 re-queues with decremented budget; hop 2 marks complete."""
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_reviews = MagicMock(return_value=1000)
    ih._s3 = MagicMock()
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped([]))),
    }
    ih._sqs = MagicMock()
    ih._catalog_repo = MagicMock()
    ih._catalog_repo.get_reviews_completed_at = MagicMock(return_value=None)
    ih._review_repo = MagicMock()
    ih._review_repo.count_by_appid = MagicMock(return_value=1000)

    started_at = "2026-03-26T12:00:00+00:00"

    # Hop 1: target=2000, count=1000 → budget not yet exhausted, re-queue with remaining=1000
    hop1 = _sqs_event(
        ReviewSpokeResult(
            appid=440,
            success=True,
            s3_key="k1",
            count=1000,
            spoke_region="us-east-1",
            next_cursor="cursor_hop2",
            target=2000,
            started_at=started_at,
        )
    )
    ih.handler(hop1, lambda_context)

    ih._catalog_repo.mark_reviews_complete.assert_not_called()
    ih._sqs.send_message.assert_called_once()
    sent = json.loads(ih._sqs.send_message.call_args[1]["MessageBody"])
    assert sent["target"] == 1000  # 2000 - 1000
    assert sent["cursor"] == "cursor_hop2"
    ih._sqs.reset_mock()

    # Hop 2: target=1000, count=1000 → budget exactly exhausted → mark complete
    hop2 = _sqs_event(
        ReviewSpokeResult(
            appid=440,
            success=True,
            s3_key="k2",
            count=1000,
            spoke_region="us-east-1",
            next_cursor="cursor_hop3",
            target=1000,
            started_at=started_at,
        )
    )
    ih.handler(hop2, lambda_context)

    ih._catalog_repo.mark_reviews_complete.assert_called_once_with(440, completed_at=None)
    ih._sqs.send_message.assert_not_called()


# ── count==0 / no s3_key — skip processing ─────────────────────────────────


@mock_aws
def test_failure_skips_s3_and_ingest(lambda_context: Any) -> None:
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._s3 = MagicMock()

    event = _sqs_event(
        MetadataSpokeResult(
            appid=440, success=False, spoke_region="us-east-1", error="Steam API: rate limited"
        )
    )
    ih.handler(event, lambda_context)

    ih._s3.get_object.assert_not_called()
    ih._crawl_service.ingest_spoke_metadata.assert_not_called()


@mock_aws
def test_failure_without_error_skips_processing(lambda_context: Any) -> None:
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._s3 = MagicMock()

    event = _sqs_event(ReviewSpokeResult(appid=440, success=False, spoke_region="us-east-1"))
    ih.handler(event, lambda_context)

    ih._s3.get_object.assert_not_called()


# ── S3 delete after successful ingest ───────────────────────────────────────


@mock_aws
def test_s3_object_deleted_after_metadata_ingest(lambda_context: Any) -> None:
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_metadata = MagicMock(return_value=True)
    ih._s3 = MagicMock()
    s3_key = "spoke-results/metadata/440-abc.json.gz"
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped({"details": {}}))),
    }

    event = _sqs_event(
        MetadataSpokeResult(
            appid=440, success=True, s3_key=s3_key, count=1, spoke_region="us-east-1"
        )
    )
    ih.handler(event, lambda_context)

    ih._s3.delete_object.assert_called_once_with(Bucket=ih._assets_bucket_name, Key=s3_key)


@mock_aws
def test_s3_object_deleted_after_reviews_ingest(lambda_context: Any) -> None:
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_reviews = MagicMock(return_value=2)
    ih._s3 = MagicMock()
    s3_key = "spoke-results/reviews/440-abc.json.gz"
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped([{"r": 1}, {"r": 2}]))),
    }
    _mock_catalog_and_review_repos(ih)

    event = _sqs_event(
        ReviewSpokeResult(
            appid=440,
            success=True,
            s3_key=s3_key,
            count=2,
            spoke_region="us-east-1",
            next_cursor=None,
        )
    )
    ih.handler(event, lambda_context)

    ih._s3.delete_object.assert_called_once_with(Bucket=ih._assets_bucket_name, Key=s3_key)


@mock_aws
def test_s3_not_deleted_on_ingest_failure(lambda_context: Any) -> None:
    """If ingest raises, S3 object should NOT be deleted (batch failure → retry)."""
    ih = _get_module()
    ih._crawl_service = MagicMock()
    ih._crawl_service.ingest_spoke_metadata = MagicMock(side_effect=RuntimeError("db error"))
    ih._s3 = MagicMock()
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped({"details": {}}))),
    }

    event = _sqs_event(
        MetadataSpokeResult(
            appid=440,
            success=True,
            s3_key="spoke-results/metadata/440-abc.json.gz",
            count=1,
            spoke_region="us-east-1",
        )
    )
    with pytest.raises(BatchProcessingError):
        ih.handler(event, lambda_context)

    ih._s3.delete_object.assert_not_called()


@mock_aws
def test_s3_not_deleted_when_failure(lambda_context: Any) -> None:
    ih = _get_module()
    ih._s3 = MagicMock()

    event = _sqs_event(
        MetadataSpokeResult(
            appid=440, success=False, spoke_region="us-east-1", error="empty details"
        )
    )
    ih.handler(event, lambda_context)

    ih._s3.delete_object.assert_not_called()


# ── Tags ingest ──────────────────────────────────────────────────────────────


@mock_aws
def test_tags_task_upserts_tags(lambda_context: Any) -> None:
    """Successful tags result → upsert tags, emit metric, delete S3."""
    ih = _get_module()
    ih._tag_repo = MagicMock()
    ih._s3 = MagicMock()

    payload = {
        "tags": [
            {"name": "FPS", "votes": 5000, "tagid": 1663},
            {"name": "Multiplayer", "votes": 3000, "tagid": 3859},
        ],
    }
    ih._s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=_gzipped(payload))),
    }

    event = _sqs_event(
        TagsSpokeResult(
            appid=440,
            success=True,
            s3_key="spoke-results/tags/440-abc.json.gz",
            count=2,
            spoke_region="us-east-1",
        )
    )
    ih.handler(event, lambda_context)

    ih._tag_repo.upsert_tags.assert_called_once()
    tag_args = ih._tag_repo.upsert_tags.call_args[0][0]
    assert len(tag_args) == 2
    assert tag_args[0] == {"appid": 440, "name": "FPS", "votes": 5000, "tagid": 1663}

    ih._s3.delete_object.assert_called_once()


@mock_aws
def test_tags_failure_skips_processing(lambda_context: Any) -> None:
    """Tags spoke failure → log warning, no S3 fetch, no upsert."""
    ih = _get_module()
    ih._tag_repo = MagicMock()
    ih._s3 = MagicMock()

    event = _sqs_event(
        TagsSpokeResult(
            appid=440,
            success=False,
            spoke_region="us-east-1",
            error="Steam store page timeout",
        )
    )
    ih.handler(event, lambda_context)

    ih._s3.get_object.assert_not_called()
    ih._tag_repo.upsert_tags.assert_not_called()


@mock_aws
def test_tags_success_no_s3_key_skips(lambda_context: Any) -> None:
    """Tags success with no s3_key (no tag data) → skip, no crash."""
    ih = _get_module()
    ih._tag_repo = MagicMock()
    ih._s3 = MagicMock()

    event = _sqs_event(
        TagsSpokeResult(
            appid=440,
            success=True,
            count=0,
            spoke_region="us-east-1",
        )
    )
    ih.handler(event, lambda_context)

    ih._s3.get_object.assert_not_called()
    ih._tag_repo.upsert_tags.assert_not_called()
