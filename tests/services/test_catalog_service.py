"""Tests for CatalogService using real repos + real DB + moto SQS."""

from unittest.mock import MagicMock

import httpx
from library_layer.config import SteamPulseConfig
from library_layer.repositories.catalog_repo import CatalogRepository
from library_layer.services.catalog_service import CatalogService
from moto import mock_aws


def _app_list_response(apps: list[dict], have_more: bool = False) -> dict:
    return {
        "response": {
            "apps": apps,
            "have_more_results": have_more,
        }
    }


def _mock_sns() -> MagicMock:
    sns = MagicMock()
    sns.publish.return_value = {"MessageId": "test-msg-id"}
    return sns


_REQUIRED_FIELDS: dict = {
    "DB_SECRET_NAME": "steampulse/test/db-credentials",
    "STEAM_API_KEY_SECRET_NAME": "steampulse/test/steam-api-key",
    "SFN_PARAM_NAME": "/steampulse/test/compute/sfn-arn",
    "STEP_FUNCTIONS_PARAM_NAME": "/steampulse/test/compute/sfn-arn",
    "APP_CRAWL_QUEUE_PARAM_NAME": "/steampulse/test/messaging/app-crawl-queue-url",
    "REVIEW_CRAWL_QUEUE_PARAM_NAME": "/steampulse/test/messaging/review-crawl-queue-url",
    "ASSETS_BUCKET_PARAM_NAME": "/steampulse/test/app/assets-bucket-name",
    "GAME_EVENTS_TOPIC_PARAM_NAME": "/steampulse/test/messaging/game-events-topic-arn",
    "CONTENT_EVENTS_TOPIC_PARAM_NAME": "/steampulse/test/messaging/content-events-topic-arn",
    "SYSTEM_EVENTS_TOPIC_PARAM_NAME": "/steampulse/test/messaging/system-events-topic-arn",
}


def _test_config() -> SteamPulseConfig:
    return SteamPulseConfig(**_REQUIRED_FIELDS)


def _make_service(
    catalog_repo: CatalogRepository,
    sqs_client: object,
    queue_url: str,
    http_client: httpx.Client,
    api_key: str = "test-key",
    sns_client: object | None = None,
    config: SteamPulseConfig | None = None,
) -> CatalogService:
    return CatalogService(
        catalog_repo=catalog_repo,
        http_client=http_client,
        sqs_client=sqs_client,
        app_crawl_queue_url=queue_url,
        sns_client=sns_client or _mock_sns(),
        config=config or _test_config(),
        steam_api_key=api_key,
        game_events_topic_arn="arn:aws:sns:us-east-1:123456789012:game-events",
        system_events_topic_arn="arn:aws:sns:us-east-1:123456789012:system-events",
    )


@mock_aws
def test_refresh_inserts_new_apps(
    catalog_repo: CatalogRepository,
) -> None:
    import boto3

    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(QueueName="app-crawl-refresh")["QueueUrl"]

    apps = [{"appid": 100 + i, "name": f"Game {i}"} for i in range(5)]

    with httpx.Client() as http_client:
        # Patch the HTTP call
        import unittest.mock as mock

        with mock.patch.object(http_client, "get") as mock_get:
            mock_resp = mock.MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = _app_list_response(apps, have_more=False)
            mock_get.return_value = mock_resp

            svc = _make_service(catalog_repo, sqs, queue_url, http_client)
            result = svc.refresh()

    assert result["apps_fetched"] == 5
    assert result["new_rows"] == 5
    assert result["enqueued"] == 5


@mock_aws
def test_refresh_skips_existing(
    catalog_repo: CatalogRepository,
) -> None:
    import boto3

    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(QueueName="app-crawl-skip-existing")["QueueUrl"]

    # Pre-insert 3 apps
    catalog_repo.bulk_upsert([{"appid": 200 + i, "name": f"Game {i}"} for i in range(3)])

    apps = [{"appid": 200 + i, "name": f"Game {i}"} for i in range(5)]  # 3 old + 2 new

    with httpx.Client() as http_client:
        import unittest.mock as mock

        with mock.patch.object(http_client, "get") as mock_get:
            mock_resp = mock.MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = _app_list_response(apps, have_more=False)
            mock_get.return_value = mock_resp

            svc = _make_service(catalog_repo, sqs, queue_url, http_client)
            result = svc.refresh()

    # Only 2 new rows (others existed)
    assert result["new_rows"] == 2


@mock_aws
def test_enqueue_pending(
    catalog_repo: CatalogRepository,
) -> None:
    import boto3

    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(QueueName="app-crawl-enqueue")["QueueUrl"]

    catalog_repo.bulk_upsert([{"appid": 300 + i, "name": f"G{i}"} for i in range(3)])

    with httpx.Client() as http_client:
        svc = _make_service(catalog_repo, sqs, queue_url, http_client)
        enqueued = svc.enqueue_pending()

    assert enqueued == 3

    # 3 apps × 2 tasks (metadata + tags) = 6 messages
    msgs = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10)
    assert len(msgs.get("Messages", [])) == 6


@mock_aws
def test_status_returns_counts(
    catalog_repo: CatalogRepository,
) -> None:
    import boto3

    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(QueueName="app-crawl-status")["QueueUrl"]

    catalog_repo.bulk_upsert([{"appid": 400 + i, "name": f"G{i}"} for i in range(4)])
    catalog_repo.set_meta_status(400, "done")
    catalog_repo.set_meta_status(401, "failed")

    with httpx.Client() as http_client:
        svc = _make_service(catalog_repo, sqs, queue_url, http_client)
        status = svc.status()

    assert status["meta"]["done"] >= 1
    assert status["meta"]["failed"] >= 1
    assert status["meta"]["pending"] >= 2


@mock_aws
def test_enqueue_stale_sends_metadata_and_tags(
    catalog_repo: CatalogRepository,
) -> None:
    import boto3

    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(QueueName="app-crawl-stale")["QueueUrl"]

    catalog_repo.bulk_upsert([{"appid": 800 + i, "name": f"S{i}"} for i in range(2)])
    for i in range(2):
        catalog_repo.set_meta_status(800 + i, "done")
    with catalog_repo.conn.cursor() as cur:
        cur.execute(
            "UPDATE app_catalog SET meta_crawled_at = NOW() - INTERVAL '40 days' "
            "WHERE appid IN (800, 801)"
        )
    catalog_repo.conn.commit()

    with httpx.Client() as http_client:
        svc = _make_service(catalog_repo, sqs, queue_url, http_client)
        count = svc.enqueue_stale(limit=10)

    assert count == 2

    # 2 appids x 2 tasks (metadata + tags) = 4 messages
    import json as _json

    resp = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10)
    received = [_json.loads(m["Body"]) for m in resp.get("Messages", [])]
    tasks = sorted(m["task"] for m in received)
    assert tasks == ["metadata", "metadata", "tags", "tags"]
