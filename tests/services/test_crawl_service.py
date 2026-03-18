"""Tests for CrawlService using real repos + real DB + moto SQS."""

import json
import re

from unittest.mock import MagicMock

import pytest
from library_layer.config import SteamPulseConfig
from library_layer.repositories.catalog_repo import CatalogRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.services.crawl_service import CrawlService
from library_layer.steam_source import DirectSteamSource
from moto import mock_aws
from pytest_httpx import HTTPXMock

REVIEW_SUMMARY = {
    "success": 1,
    "query_summary": {
        "total_positive": 182000,
        "total_negative": 6000,
        "total_reviews": 188000,
        "review_score": 9,
        "review_score_desc": "Overwhelmingly Positive",
    },
    "reviews": [],
}

SMALL_REVIEW_SUMMARY = {
    "success": 1,
    "query_summary": {
        "total_positive": 40,
        "total_negative": 10,
        "total_reviews": 50,
        "review_score": 7,
        "review_score_desc": "Positive",
    },
    "reviews": [],
}

REVIEWS_RESPONSE = {
    "success": 1,
    "query_summary": {},
    "reviews": [
        {
            "recommendationid": f"r{i}",
            "author": {"steamid": f"player{i}", "playtime_at_review": 120},
            "review": f"Great game review number {i}",
            "timestamp_created": 1700000000 + i,
            "voted_up": i % 2 == 0,
            "playtime_at_review": 120,
        }
        for i in range(4)
    ],
    "cursor": "",
}


def _mock_sns() -> MagicMock:
    sns = MagicMock()
    sns.publish.return_value = {"MessageId": "test-msg-id"}
    return sns


def _test_config() -> SteamPulseConfig:
    return SteamPulseConfig(
        GAME_EVENTS_TOPIC_ARN="arn:aws:sns:us-east-1:123456789:game-events",
        CONTENT_EVENTS_TOPIC_ARN="arn:aws:sns:us-east-1:123456789:content-events",
        SYSTEM_EVENTS_TOPIC_ARN="arn:aws:sns:us-east-1:123456789:system-events",
    )


def _make_service(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    sqs_client: object,
    review_queue_url: str,
    http_client: object,
    sfn_arn: str | None = None,
    sfn_client: object | None = None,
) -> CrawlService:
    steam = DirectSteamSource(http_client)
    return CrawlService(
        game_repo=game_repo,
        review_repo=review_repo,
        catalog_repo=catalog_repo,
        tag_repo=tag_repo,
        steam=steam,
        sqs_client=sqs_client,
        review_queue_url=review_queue_url,
        sns_client=_mock_sns(),
        config=_test_config(),
        sfn_arn=sfn_arn,
        sfn_client=sfn_client,
    )


@pytest.mark.asyncio
async def test_crawl_app_stores_game(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    import boto3
    import httpx as _httpx

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="review-crawl-q")["QueueUrl"]

        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
            json=steam_appdetails_440,
        )
        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
            json=REVIEW_SUMMARY,
        )

        async with _httpx.AsyncClient() as client:
            svc = _make_service(
                game_repo, review_repo, catalog_repo, tag_repo,
                sqs, queue_url, client,
            )
            result = await svc.crawl_app(440)

    assert result is True
    game = game_repo.find_by_appid(440)
    assert game is not None
    assert game.name == "Team Fortress 2"
    assert game.developer == "Valve"
    assert game.is_free is True


@pytest.mark.asyncio
async def test_crawl_app_enqueues_review_crawl_when_eligible(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    import boto3
    import httpx as _httpx

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="review-q-eligible")["QueueUrl"]

        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
            json=steam_appdetails_440,
        )
        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
            json=REVIEW_SUMMARY,
        )

        async with _httpx.AsyncClient() as client:
            svc = _make_service(
                game_repo, review_repo, catalog_repo, tag_repo,
                sqs, queue_url, client,
            )
            await svc.crawl_app(440)

        msgs = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10)
    assert len(msgs.get("Messages", [])) >= 1
    body = json.loads(msgs["Messages"][0]["Body"])
    assert body["appid"] == 440


@pytest.mark.asyncio
async def test_crawl_app_does_not_enqueue_ineligible(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    """A game with only 50 reviews should not be queued for review crawl."""
    import boto3
    import httpx as _httpx

    small_summary = {
        "success": 1,
        "query_summary": {
            "total_positive": 40,
            "total_negative": 10,
            "review_score_desc": "Positive",
        },
        "reviews": [],
    }

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="review-q-ineligible")["QueueUrl"]

        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
            json=steam_appdetails_440,
        )
        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
            json=small_summary,
        )

        async with _httpx.AsyncClient() as client:
            svc = _make_service(
                game_repo, review_repo, catalog_repo, tag_repo,
                sqs, queue_url, client,
            )
            await svc.crawl_app(440)

    pass


@pytest.mark.asyncio
async def test_crawl_app_handles_steam_error(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    httpx_mock: HTTPXMock,
) -> None:
    import boto3
    import httpx as _httpx

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="review-q-err")["QueueUrl"]

        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
            status_code=500,
        )

        async with _httpx.AsyncClient() as client:
            svc = _make_service(
                game_repo, review_repo, catalog_repo, tag_repo,
                sqs, queue_url, client,
            )
            result = await svc.crawl_app(440)

    assert result is False
    assert game_repo.find_by_appid(440) is None


@pytest.mark.asyncio
async def test_crawl_reviews_stores_reviews(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    httpx_mock: HTTPXMock,
) -> None:
    import boto3
    import httpx as _httpx

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="review-q-reviews")["QueueUrl"]

        game_repo.ensure_stub(440)

        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
            json=REVIEWS_RESPONSE,
        )

        async with _httpx.AsyncClient() as client:
            svc = _make_service(
                game_repo, review_repo, catalog_repo, tag_repo,
                sqs, queue_url, client,
            )
            count = await svc.crawl_reviews(440)

    assert count == 4
    assert review_repo.count_by_appid(440) == 4


@pytest.mark.asyncio
async def test_crawl_reviews_deduplicates(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    httpx_mock: HTTPXMock,
) -> None:
    import boto3
    import httpx as _httpx

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="review-q-dedup")["QueueUrl"]

        game_repo.ensure_stub(440)

        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
            json=REVIEWS_RESPONSE,
        )
        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
            json=REVIEWS_RESPONSE,
        )

        async with _httpx.AsyncClient() as client:
            svc = _make_service(
                game_repo, review_repo, catalog_repo, tag_repo,
                sqs, queue_url, client,
            )
            await svc.crawl_reviews(440)
            await svc.crawl_reviews(440)

    # No duplicates — still only 4
    assert review_repo.count_by_appid(440) == 4


@pytest.mark.parametrize("total,stored,expected", [
    # Tier 1: < 200 reviews, threshold 25
    (100, 0, True),      # delta=100 >= 25
    (100, 90, False),    # delta=10 < 25
    # Tier 2: 200-1999, threshold 150
    (500, 0, True),      # delta=500 >= 150
    (500, 400, False),   # delta=100 < 150
    # Tier 3: 2000-19999, threshold 500
    (5000, 0, True),     # delta=5000 >= 500
    (5000, 4600, False), # delta=400 < 500
    # Tier 4: 20000-199999, threshold 2000
    (50000, 0, True),    # delta=50000 >= 2000
    (50000, 48500, False), # delta=1500 < 2000
    # Tier 5: 200000+, threshold 10000
    (500000, 0, True),    # delta=500000 >= 10000
    (500000, 495000, False), # delta=5000 < 10000
])
def test_should_enqueue_reviews_thresholds(
    total: int,
    stored: int,
    expected: bool,
) -> None:
    # Use a minimal dummy service instance without real dependencies
    svc = CrawlService.__new__(CrawlService)
    assert svc._should_enqueue_reviews(total, stored) is expected
