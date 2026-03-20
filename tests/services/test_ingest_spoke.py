"""Tests for CrawlService spoke ingest methods."""

import asyncio
from unittest.mock import MagicMock

from library_layer.config import SteamPulseConfig
from library_layer.repositories.catalog_repo import CatalogRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.services.crawl_service import CrawlService
from library_layer.steam_source import DirectSteamSource

_REQUIRED_FIELDS: dict = {
    "DB_SECRET_NAME": "steampulse/test/db-credentials",
    "STEAM_API_KEY_SECRET_NAME": "steampulse/test/steam-api-key",
    "SFN_PARAM_NAME": "/steampulse/test/compute/sfn-arn",
    "STEP_FUNCTIONS_PARAM_NAME": "/steampulse/test/compute/sfn-arn",
    "APP_CRAWL_QUEUE_PARAM_NAME": "/steampulse/test/messaging/app-crawl-queue-url",
    "REVIEW_CRAWL_QUEUE_PARAM_NAME": "/steampulse/test/messaging/review-crawl-queue-url",
    "ASSETS_BUCKET_PARAM_NAME": "/steampulse/test/data/assets-bucket-name",
    "GAME_EVENTS_TOPIC_PARAM_NAME": "/steampulse/test/messaging/game-events-topic-arn",
    "CONTENT_EVENTS_TOPIC_PARAM_NAME": "/steampulse/test/messaging/content-events-topic-arn",
    "SYSTEM_EVENTS_TOPIC_PARAM_NAME": "/steampulse/test/messaging/system-events-topic-arn",
}


def _make_crawl_service() -> CrawlService:
    return CrawlService(
        game_repo=MagicMock(spec=GameRepository),
        review_repo=MagicMock(spec=ReviewRepository),
        catalog_repo=MagicMock(spec=CatalogRepository),
        tag_repo=MagicMock(spec=TagRepository),
        steam=MagicMock(spec=DirectSteamSource),
        sqs_client=MagicMock(),
        review_queue_url="https://sqs.us-east-1.amazonaws.com/123456789012/review-crawl",
        sns_client=MagicMock(),
        config=SteamPulseConfig(**_REQUIRED_FIELDS),
        game_events_topic_arn="arn:aws:sns:us-east-1:123456789012:game-events",
        content_events_topic_arn="arn:aws:sns:us-east-1:123456789012:content-events",
    )


def test_ingest_spoke_metadata_delegates() -> None:
    """ingest_spoke_metadata delegates to _ingest_app_data and publishes events."""
    svc = _make_crawl_service()
    svc._game_repo.find_by_appid = MagicMock(return_value=None)
    svc._ingest_app_data = MagicMock(return_value={"appid": 440, "name": "TF2", "review_count": 100})
    raw = {"details": {"name": "TF2", "type": "game"}, "summary": {}, "deck_compat": None}
    result = asyncio.run(svc.ingest_spoke_metadata(440, raw))
    assert result is True
    svc._ingest_app_data.assert_called_once()


def test_ingest_spoke_metadata_empty_details() -> None:
    """ingest_spoke_metadata returns False on empty details."""
    svc = _make_crawl_service()
    result = asyncio.run(svc.ingest_spoke_metadata(440, {}))
    assert result is False


def test_ingest_spoke_metadata_none_details() -> None:
    """ingest_spoke_metadata returns False when details is None."""
    svc = _make_crawl_service()
    result = asyncio.run(svc.ingest_spoke_metadata(440, {"details": None}))
    assert result is False


def test_ingest_spoke_reviews_returns_count() -> None:
    """ingest_spoke_reviews upserts reviews and returns count."""
    svc = _make_crawl_service()
    svc._review_repo.bulk_upsert = MagicMock(return_value=1)
    svc._game_repo.ensure_stub = MagicMock()

    reviews = [{
        "review_text": "good game",
        "voted_up": True,
        "playtime_at_review": 120,
        "timestamp_created": 1700000001,
        "language": "english",
        "author_steamid": "u1",
        "votes_helpful": 5,
        "votes_funny": 0,
        "written_during_early_access": False,
        "received_for_free": False,
    }]
    result = asyncio.run(svc.ingest_spoke_reviews(440, reviews))
    assert result == 1
    svc._game_repo.ensure_stub.assert_called_once_with(440)
    svc._review_repo.bulk_upsert.assert_called_once()


def test_ingest_spoke_reviews_empty() -> None:
    """ingest_spoke_reviews returns 0 on empty list."""
    svc = _make_crawl_service()
    result = asyncio.run(svc.ingest_spoke_reviews(440, []))
    assert result == 0
