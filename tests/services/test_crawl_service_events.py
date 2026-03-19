"""Tests for CrawlService + CatalogService SNS event publishing (tests 27-43 from spec)."""

import json
import re
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from library_layer.config import SteamPulseConfig
from library_layer.repositories.catalog_repo import CatalogRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.services.catalog_service import CatalogService
from library_layer.services.crawl_service import CrawlService
from library_layer.steam_source import DirectSteamSource
from library_layer.utils.ssm import _ssm_cache, get_eligibility_threshold
from moto import mock_aws
from pytest_httpx import HTTPXMock


# English review summary (first call)
REVIEW_SUMMARY_ENGLISH = {
    "success": 1,
    "query_summary": {
        "total_positive": 800,
        "total_negative": 200,
        "total_reviews": 1000,
        "review_score": 9,
        "review_score_desc": "Very Positive",
    },
    "reviews": [],
}

# All-language review summary (second call)
REVIEW_SUMMARY_ALL = {
    "success": 1,
    "query_summary": {
        "total_positive": 900,
        "total_negative": 250,
        "total_reviews": 1150,
        "review_score": 9,
        "review_score_desc": "Very Positive",
    },
    "reviews": [],
}

SMALL_REVIEW_SUMMARY = {
    "success": 1,
    "query_summary": {
        "total_positive": 80,
        "total_negative": 20,
        "total_reviews": 100,
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
            "language": "english",
            "votes_up": i * 2,
            "votes_funny": 0,
            "written_during_early_access": False,
            "received_for_free": False,
        }
        for i in range(4)
    ],
    "cursor": "",
}


def _mock_sns() -> MagicMock:
    client = MagicMock()
    client.publish.return_value = {"MessageId": "test-msg-id"}
    return client


def _mock_sqs() -> MagicMock:
    """Mock SQS client that accepts send_message and send_message_batch calls."""
    client = MagicMock()
    client.send_message.return_value = {"MessageId": "sqs-msg-id"}
    client.send_message_batch.return_value = {"Successful": [], "Failed": []}
    return client


def _test_config(**overrides: Any) -> SteamPulseConfig:
    defaults: dict = {
        "DB_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:db",
        "SFN_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:crawl",
        "APP_CRAWL_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/app-crawl",
        "REVIEW_CRAWL_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/review-crawl",
        "STEAM_API_KEY_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:steam-key",
        "ASSETS_BUCKET_NAME": "steampulse-assets-test",
        "STEP_FUNCTIONS_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:crawl",
        "GAME_EVENTS_TOPIC_ARN": "arn:aws:sns:us-west-2:000:game-events",
        "CONTENT_EVENTS_TOPIC_ARN": "arn:aws:sns:us-west-2:000:content-events",
        "SYSTEM_EVENTS_TOPIC_ARN": "arn:aws:sns:us-west-2:000:system-events",
        "REVIEW_ELIGIBILITY_THRESHOLD": 500,
    }
    defaults.update(overrides)
    return SteamPulseConfig(**defaults)


def _make_crawl_service(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    http_client: object,
    sns_client: object | None = None,
    config: SteamPulseConfig | None = None,
) -> CrawlService:
    steam = DirectSteamSource(http_client)
    return CrawlService(
        game_repo=game_repo,
        review_repo=review_repo,
        catalog_repo=catalog_repo,
        tag_repo=tag_repo,
        steam=steam,
        sqs_client=_mock_sqs(),
        review_queue_url="https://sqs.fake/review-q",
        sns_client=sns_client,
        config=config,
    )


def _game_row(**overrides: Any) -> dict:
    """Build a complete game_data dict for GameRepository.upsert()."""
    base = {
        "appid": 440,
        "name": "TF2",
        "slug": "tf2",
        "type": "game",
        "developer": "Valve",
        "developer_slug": "valve",
        "publisher": "Valve",
        "developers": "[]",
        "publishers": "[]",
        "website": None,
        "release_date": None,
        "coming_soon": False,
        "price_usd": None,
        "is_free": True,
        "short_desc": "",
        "detailed_description": "",
        "about_the_game": "",
        "review_count": 0,
        "review_count_english": 0,
        "total_positive": 0,
        "total_negative": 0,
        "positive_pct": None,
        "review_score_desc": "",
        "header_image": "",
        "background_image": "",
        "required_age": 0,
        "platforms": "{}",
        "supported_languages": "",
        "achievements_total": 0,
        "metacritic_score": None,
        "deck_compatibility": None,
        "deck_test_results": None,
        "data_source": "test",
    }
    base.update(overrides)
    return base


def _find_sns_calls(sns: MagicMock, event_type: str) -> list:
    """Find SNS publish calls matching a given event_type."""
    return [c for c in sns.publish.call_args_list if event_type in (c.kwargs.get("Message") or "")]


def _find_sns_calls_by_attr(sns: MagicMock, event_type: str) -> list:
    """Find SNS publish calls where MessageAttributes.event_type matches."""
    return [
        c
        for c in sns.publish.call_args_list
        if c.kwargs.get("MessageAttributes", {}).get("event_type", {}).get("StringValue")
        == event_type
    ]


# ── 27. crawl_app publishes metadata-ready ──────────────────────────────────


@pytest.mark.asyncio
async def test_crawl_app_publishes_metadata_ready(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    import httpx as _httpx

    sns = _mock_sns()
    config = _test_config()

    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
        json=steam_appdetails_440,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ENGLISH,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ALL,
    )

    async with _httpx.AsyncClient() as client:
        svc = _make_crawl_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            client,
            sns_client=sns,
            config=config,
        )
        await svc.crawl_app(440)

    calls = _find_sns_calls_by_attr(sns, "game-metadata-ready")
    assert len(calls) >= 1


# ── 28. eligible game sets is_eligible=true ─────────────────────────────────


@pytest.mark.asyncio
async def test_crawl_app_eligible_sets_is_eligible_true(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    import httpx as _httpx

    sns = _mock_sns()
    config = _test_config(REVIEW_ELIGIBILITY_THRESHOLD=500)

    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
        json=steam_appdetails_440,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ENGLISH,  # 1000 English reviews > 500 threshold
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ALL,
    )

    async with _httpx.AsyncClient() as client:
        svc = _make_crawl_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            client,
            sns_client=sns,
            config=config,
        )
        await svc.crawl_app(440)

    for call in _find_sns_calls_by_attr(sns, "game-metadata-ready"):
        attrs = call.kwargs["MessageAttributes"]
        assert attrs["is_eligible"]["StringValue"] == "true"
        return
    pytest.fail("No metadata-ready event found")


# ── 29. ineligible game sets is_eligible=false ──────────────────────────────


@pytest.mark.asyncio
async def test_crawl_app_ineligible_sets_is_eligible_false(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    import httpx as _httpx

    sns = _mock_sns()
    config = _test_config(REVIEW_ELIGIBILITY_THRESHOLD=500)

    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
        json=steam_appdetails_440,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=SMALL_REVIEW_SUMMARY,  # 100 English reviews < 500 threshold
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=SMALL_REVIEW_SUMMARY,  # all languages (same for small game)
    )

    async with _httpx.AsyncClient() as client:
        svc = _make_crawl_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            client,
            sns_client=sns,
            config=config,
        )
        await svc.crawl_app(440)

    for call in _find_sns_calls_by_attr(sns, "game-metadata-ready"):
        attrs = call.kwargs["MessageAttributes"]
        assert attrs["is_eligible"]["StringValue"] == "false"
        return
    pytest.fail("No metadata-ready event found")


# ── 30. configurable threshold ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crawl_app_uses_configurable_threshold(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    """Threshold=200, game with 1000 reviews → eligible."""
    import httpx as _httpx

    sns = _mock_sns()
    config = _test_config(REVIEW_ELIGIBILITY_THRESHOLD=200)

    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
        json=steam_appdetails_440,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ENGLISH,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ALL,
    )

    async with _httpx.AsyncClient() as client:
        svc = _make_crawl_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            client,
            sns_client=sns,
            config=config,
        )
        await svc.crawl_app(440)

    for call in _find_sns_calls_by_attr(sns, "game-metadata-ready"):
        attrs = call.kwargs["MessageAttributes"]
        assert attrs["is_eligible"]["StringValue"] == "true"
        return
    pytest.fail("No metadata-ready event found")


# ── 31. SSM override ────────────────────────────────────────────────────────


@mock_aws
def test_get_eligibility_threshold_ssm_override() -> None:
    import boto3

    _ssm_cache.clear()
    ssm = boto3.client("ssm", region_name="us-east-1")
    ssm.put_parameter(
        Name="/steampulse/staging/config/review-eligibility-threshold",
        Value="1000",
        Type="String",
    )
    config = _test_config(REVIEW_ELIGIBILITY_THRESHOLD=500)
    result = get_eligibility_threshold(config, env="staging")
    assert result == 1000
    _ssm_cache.clear()


# ── 32. SSM fallback ────────────────────────────────────────────────────────


def test_get_eligibility_threshold_ssm_fallback() -> None:
    _ssm_cache.clear()
    config = _test_config(REVIEW_ELIGIBILITY_THRESHOLD=500)
    result = get_eligibility_threshold(config, env="staging")
    assert result == 500
    _ssm_cache.clear()


# ── 33. SSM caches ──────────────────────────────────────────────────────────


def test_get_eligibility_threshold_caches() -> None:
    _ssm_cache.clear()
    config = _test_config()

    with patch("library_layer.utils.ssm.boto3") as mock_boto:
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "800"}}
        mock_boto.client.return_value = mock_ssm

        get_eligibility_threshold(config, env="staging")
        get_eligibility_threshold(config, env="staging")

        assert mock_ssm.get_parameter.call_count == 1

    _ssm_cache.clear()


# ── 34. detects game-released ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crawl_app_detects_game_released(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    import httpx as _httpx

    sns = _mock_sns()
    config = _test_config()

    # Insert existing game with coming_soon=True
    game_repo.upsert(_game_row(coming_soon=True, review_count=0))

    # Steam returns coming_soon=False (game released)
    details_with_release = dict(steam_appdetails_440)
    details_with_release["440"] = dict(steam_appdetails_440["440"])
    details_with_release["440"]["data"] = dict(steam_appdetails_440["440"]["data"])
    details_with_release["440"]["data"]["release_date"] = {
        "coming_soon": False,
        "date": "Oct 10, 2007",
    }

    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
        json=details_with_release,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ENGLISH,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ALL,
    )

    async with _httpx.AsyncClient() as client:
        svc = _make_crawl_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            client,
            sns_client=sns,
            config=config,
        )
        await svc.crawl_app(440)

    released_calls = _find_sns_calls(sns, "game-released")
    assert len(released_calls) >= 1


# ── 35. no release if already released ───────────────────────────────────────


@pytest.mark.asyncio
async def test_crawl_app_no_release_if_already_released(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    import httpx as _httpx

    sns = _mock_sns()
    config = _test_config()

    game_repo.upsert(_game_row(coming_soon=False, review_count=0))

    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
        json=steam_appdetails_440,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ENGLISH,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ALL,
    )

    async with _httpx.AsyncClient() as client:
        svc = _make_crawl_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            client,
            sns_client=sns,
            config=config,
        )
        await svc.crawl_app(440)

    released_calls = _find_sns_calls(sns, "game-released")
    assert len(released_calls) == 0


# ── 36. detects price change ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crawl_app_detects_price_change(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    import httpx as _httpx

    sns = _mock_sns()
    config = _test_config()

    game_repo.upsert(_game_row(price_usd=Decimal("29.99"), is_free=False, review_count=0))

    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
        json=steam_appdetails_440,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ENGLISH,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ALL,
    )

    async with _httpx.AsyncClient() as client:
        svc = _make_crawl_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            client,
            sns_client=sns,
            config=config,
        )
        await svc.crawl_app(440)

    price_calls = _find_sns_calls(sns, "game-price-changed")
    assert len(price_calls) >= 1


# ── 37. no price event if same ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crawl_app_no_price_event_if_same(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    import httpx as _httpx

    sns = _mock_sns()
    config = _test_config()

    # TF2 is free — matching the fixture
    game_repo.upsert(_game_row(price_usd=None, is_free=True, review_count=0))

    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
        json=steam_appdetails_440,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ENGLISH,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ALL,
    )

    async with _httpx.AsyncClient() as client:
        svc = _make_crawl_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            client,
            sns_client=sns,
            config=config,
        )
        await svc.crawl_app(440)

    price_calls = _find_sns_calls(sns, "game-price-changed")
    assert len(price_calls) == 0


# ── 38. detects review milestone ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crawl_app_detects_review_milestone(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    import httpx as _httpx

    sns = _mock_sns()
    config = _test_config()

    game_repo.upsert(_game_row(review_count=490))

    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
        json=steam_appdetails_440,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ENGLISH,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ALL,  # 1150 all-lang reviews → crosses 500, 1000
    )

    async with _httpx.AsyncClient() as client:
        svc = _make_crawl_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            client,
            sns_client=sns,
            config=config,
        )
        await svc.crawl_app(440)

    milestone_calls = _find_sns_calls(sns, "review-milestone")
    assert len(milestone_calls) >= 1
    body = json.loads(milestone_calls[0].kwargs["Message"])
    assert body["milestone"] in [500, 1000]


# ── 39. publishes ALL crossed milestones ────────────────────────────────────


@pytest.mark.asyncio
async def test_crawl_app_publishes_all_crossed_milestones(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    import httpx as _httpx

    sns = _mock_sns()
    config = _test_config()

    game_repo.upsert(_game_row(review_count=400))

    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
        json=steam_appdetails_440,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ENGLISH,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ALL,  # 1150 all-lang → crosses 500 and 1000
    )

    async with _httpx.AsyncClient() as client:
        svc = _make_crawl_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            client,
            sns_client=sns,
            config=config,
        )
        await svc.crawl_app(440)

    milestone_calls = _find_sns_calls(sns, "review-milestone")
    milestones_published = {json.loads(c.kwargs["Message"])["milestone"] for c in milestone_calls}
    assert 500 in milestones_published
    assert 1000 in milestones_published


# ── 40. no milestone if already past ────────────────────────────────────────


@pytest.mark.asyncio
async def test_crawl_app_no_milestone_if_already_past(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    import httpx as _httpx

    sns = _mock_sns()
    config = _test_config()

    game_repo.upsert(_game_row(review_count=600))

    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
        json=steam_appdetails_440,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ENGLISH,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEW_SUMMARY_ALL,  # 1150 all-lang reviews
    )

    async with _httpx.AsyncClient() as client:
        svc = _make_crawl_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            client,
            sns_client=sns,
            config=config,
        )
        await svc.crawl_app(440)

    milestone_calls = _find_sns_calls(sns, "review-milestone")
    milestones_published = {json.loads(c.kwargs["Message"])["milestone"] for c in milestone_calls}
    assert 500 not in milestones_published
    assert 1000 in milestones_published


# ── 41. crawl_reviews publishes reviews-ready ────────────────────────────────


@pytest.mark.asyncio
async def test_crawl_reviews_publishes_reviews_ready(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    httpx_mock: HTTPXMock,
) -> None:
    import httpx as _httpx

    sns = _mock_sns()
    config = _test_config()

    game_repo.upsert(_game_row(review_count=100))

    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=REVIEWS_RESPONSE,
    )

    async with _httpx.AsyncClient() as client:
        svc = _make_crawl_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            client,
            sns_client=sns,
            config=config,
        )
        await svc.crawl_reviews(440)

    reviews_ready_calls = _find_sns_calls(sns, "reviews-ready")
    assert len(reviews_ready_calls) == 1
    body = json.loads(reviews_ready_calls[0].kwargs["Message"])
    assert body["appid"] == 440
    assert body["reviews_crawled"] == 4


# ── 42. catalog_refresh publishes discovered events ──────────────────────────


def test_catalog_refresh_publishes_discovered_events(
    catalog_repo: CatalogRepository,
) -> None:
    sns = _mock_sns()
    config = _test_config()

    apps = [{"appid": 100 + i, "name": f"Game {i}"} for i in range(3)]

    with httpx.Client() as http_client:
        import unittest.mock as mock

        with mock.patch.object(http_client, "get") as mock_get:
            mock_resp = mock.MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {"response": {"apps": apps, "have_more_results": False}}
            mock_get.return_value = mock_resp

            svc = CatalogService(
                catalog_repo=catalog_repo,
                http_client=http_client,
                sqs_client=_mock_sqs(),
                app_crawl_queue_url="https://sqs.fake/app-crawl",
                steam_api_key="test-key",
                sns_client=sns,
                config=config,
            )
            svc.refresh()

    discovered_calls = _find_sns_calls(sns, "game-discovered")
    assert len(discovered_calls) == 3


# ── 43. catalog_refresh publishes completion event ───────────────────────────


def test_catalog_refresh_publishes_completion(
    catalog_repo: CatalogRepository,
) -> None:
    sns = _mock_sns()
    config = _test_config()

    apps = [{"appid": 200 + i, "name": f"Game {i}"} for i in range(2)]

    with httpx.Client() as http_client:
        import unittest.mock as mock

        with mock.patch.object(http_client, "get") as mock_get:
            mock_resp = mock.MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {"response": {"apps": apps, "have_more_results": False}}
            mock_get.return_value = mock_resp

            svc = CatalogService(
                catalog_repo=catalog_repo,
                http_client=http_client,
                sqs_client=_mock_sqs(),
                app_crawl_queue_url="https://sqs.fake/app-crawl",
                steam_api_key="test-key",
                sns_client=sns,
                config=config,
            )
            svc.refresh()

    completion_calls = _find_sns_calls(sns, "catalog-refresh-complete")
    assert len(completion_calls) == 1
    body = json.loads(completion_calls[0].kwargs["Message"])
    assert body["new_games"] == 2
    assert body["total_games"] == 2
