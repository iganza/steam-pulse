"""Tests for CatalogService using real repos + real DB + moto SQS."""

from unittest.mock import MagicMock

import httpx
from library_layer.config import SteamPulseConfig
from library_layer.models.catalog import CatalogEntry
from library_layer.repositories.catalog_repo import CatalogRepository
from library_layer.services.catalog_service import CatalogService, _dispatched_by_tier
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
    review_queue_url: str | None = None,
) -> CatalogService:
    return CatalogService(
        catalog_repo=catalog_repo,
        http_client=http_client,
        sqs_client=sqs_client,
        app_crawl_queue_url=queue_url,
        review_crawl_queue_url=review_queue_url or queue_url,
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


def _seed_game_for_tier(
    catalog_repo: CatalogRepository,
    appid: int,
    review_count: int,
    coming_soon: bool = False,
) -> None:
    with catalog_repo.conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO games (appid, name, slug, type, coming_soon, review_count)
            VALUES (%s, %s, %s, 'game', %s, %s)
            ON CONFLICT (appid) DO UPDATE SET
                coming_soon = EXCLUDED.coming_soon,
                review_count = EXCLUDED.review_count
            """,
            (appid, f"Game {appid}", f"game-{appid}", coming_soon, review_count),
        )
    catalog_repo.conn.commit()


@mock_aws
def test_enqueue_refresh_meta_sends_metadata_and_tags(
    catalog_repo: CatalogRepository,
) -> None:
    import boto3

    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(QueueName="app-crawl-refresh")["QueueUrl"]

    catalog_repo.bulk_upsert([{"appid": 800 + i, "name": f"S{i}"} for i in range(2)])
    for i in range(2):
        appid = 800 + i
        catalog_repo.set_meta_status(appid, "done")
        _seed_game_for_tier(catalog_repo, appid, review_count=100)  # B tier
    with catalog_repo.conn.cursor() as cur:
        cur.execute(
            "UPDATE app_catalog SET meta_crawled_at = NOW() - INTERVAL '180 days' "
            "WHERE appid IN (800, 801)"
        )
    catalog_repo.conn.commit()

    with httpx.Client() as http_client:
        svc = _make_service(catalog_repo, sqs, queue_url, http_client)
        count = svc.enqueue_refresh_meta(limit=10)

    assert count == 2

    # 2 appids × 2 tasks (metadata + tags) = 4 messages
    import json as _json

    resp = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10)
    received = [_json.loads(m["Body"]) for m in resp.get("Messages", [])]
    tasks = sorted(m["task"] for m in received)
    assert tasks == ["metadata", "metadata", "tags", "tags"]


@mock_aws
def test_enqueue_refresh_reviews_tags_source_refresh(
    catalog_repo: CatalogRepository,
) -> None:
    import boto3

    sqs = boto3.client("sqs", region_name="us-east-1")
    app_q = sqs.create_queue(QueueName="app-crawl-refresh-rev")["QueueUrl"]
    rev_q = sqs.create_queue(QueueName="review-crawl-refresh")["QueueUrl"]

    catalog_repo.bulk_upsert([{"appid": 900 + i, "name": f"R{i}"} for i in range(2)])
    for i in range(2):
        appid = 900 + i
        catalog_repo.set_meta_status(appid, "done")
        _seed_game_for_tier(catalog_repo, appid, review_count=5_000)  # A tier, not coming_soon
    with catalog_repo.conn.cursor() as cur:
        cur.execute(
            "UPDATE app_catalog SET review_crawled_at = NOW() - INTERVAL '30 days' "
            "WHERE appid IN (900, 901)"
        )
    catalog_repo.conn.commit()

    with httpx.Client() as http_client:
        svc = _make_service(
            catalog_repo, sqs, app_q, http_client, review_queue_url=rev_q
        )
        count = svc.enqueue_refresh_reviews(limit=10)

    assert count == 2

    import json as _json

    resp = sqs.receive_message(QueueUrl=rev_q, MaxNumberOfMessages=10)
    received = [_json.loads(m["Body"]) for m in resp.get("Messages", [])]
    assert len(received) == 2
    # Each message must be tagged source='refresh' so the dispatcher logs it
    # and dashboards can attribute queue volume.
    for msg in received:
        assert msg["source"] == "refresh"
        assert msg["appid"] in {900, 901}


@mock_aws
def test_enqueue_refresh_reviews_skips_coming_soon(
    catalog_repo: CatalogRepository,
) -> None:
    import boto3

    sqs = boto3.client("sqs", region_name="us-east-1")
    app_q = sqs.create_queue(QueueName="app-crawl-cs-skip")["QueueUrl"]
    rev_q = sqs.create_queue(QueueName="review-crawl-cs-skip")["QueueUrl"]

    catalog_repo.bulk_upsert([{"appid": 950, "name": "Upcoming"}])
    catalog_repo.set_meta_status(950, "done")
    _seed_game_for_tier(catalog_repo, 950, review_count=500, coming_soon=True)
    with catalog_repo.conn.cursor() as cur:
        cur.execute("UPDATE app_catalog SET review_crawled_at = NULL WHERE appid = 950")
    catalog_repo.conn.commit()

    with httpx.Client() as http_client:
        svc = _make_service(
            catalog_repo, sqs, app_q, http_client, review_queue_url=rev_q
        )
        count = svc.enqueue_refresh_reviews(limit=10)

    assert count == 0


def _stub_entry(appid: int, tier_rank: int | None) -> CatalogEntry:
    return CatalogEntry(appid=appid, name=f"Game {appid}", tier_rank=tier_rank)


def test_dispatched_by_tier_counts_each_tier() -> None:
    entries = [
        _stub_entry(1, 0),  # S
        _stub_entry(2, 0),  # S
        _stub_entry(3, 1),  # A
        _stub_entry(4, 2),  # B
        _stub_entry(5, 2),  # B
        _stub_entry(6, 3),  # C
    ]
    assert _dispatched_by_tier(entries) == {
        "S": 2,
        "A": 1,
        "B": 2,
        "C": 1,
        "unknown": 0,
    }


def test_dispatched_by_tier_surfaces_unknown_ranks() -> None:
    """Unexpected tier_rank values show up in the 'unknown' bucket, not silently dropped."""
    entries = [
        _stub_entry(1, 0),  # S
        _stub_entry(2, 99),  # out-of-range
        _stub_entry(3, None),  # NULL from DB
    ]
    result = _dispatched_by_tier(entries)
    assert result["S"] == 1
    assert result["unknown"] == 2
