"""Tests for CatalogService using real repos + real DB + moto SQS."""


import httpx
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


def _make_service(
    catalog_repo: CatalogRepository,
    sqs_client: object,
    queue_url: str,
    http_client: httpx.Client,
    api_key: str = "test-key",
) -> CatalogService:
    return CatalogService(
        catalog_repo=catalog_repo,
        http_client=http_client,
        sqs_client=sqs_client,
        app_crawl_queue_url=queue_url,
        steam_api_key=api_key,
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

    msgs = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10)
    assert len(msgs.get("Messages", [])) == 3


@mock_aws
def test_status_returns_counts(
    catalog_repo: CatalogRepository,
) -> None:
    import boto3

    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(QueueName="app-crawl-status")["QueueUrl"]

    catalog_repo.bulk_upsert([{"appid": 400 + i, "name": f"G{i}"} for i in range(4)])
    catalog_repo.set_meta_status(400, "done", review_status="done")
    catalog_repo.set_meta_status(401, "failed")

    with httpx.Client() as http_client:
        svc = _make_service(catalog_repo, sqs, queue_url, http_client)
        status = svc.status()

    assert status["meta"]["done"] >= 1
    assert status["meta"]["failed"] >= 1
    assert status["meta"]["pending"] >= 2
