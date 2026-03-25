"""Tests for CrawlService using real repos + real DB + moto SQS."""

import json
import re
from unittest.mock import MagicMock

from library_layer.config import SteamPulseConfig
from library_layer.repositories.catalog_repo import CatalogRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.services.crawl_service import CrawlService
from library_layer.steam_source import DirectSteamSource
from moto import mock_aws
from pytest_httpx import HTTPXMock

# English review summary (first call from get_review_summary)
REVIEW_SUMMARY_ENGLISH = {
    "success": 1,
    "query_summary": {
        "total_positive": 150000,
        "total_negative": 5000,
        "total_reviews": 155000,
        "review_score": 9,
        "review_score_desc": "Overwhelmingly Positive",
    },
    "reviews": [],
}

# All-language review summary (second call from get_review_summary)
REVIEW_SUMMARY_ALL = {
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
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    sqs_client: object,
    review_queue_url: str,
    http_client: object,
    sfn_arn: str | None = None,
    sfn_client: object | None = None,
    s3_client: object | None = None,
    archive_bucket: str | None = None,
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
        s3_client=s3_client,
        archive_bucket=archive_bucket,
        game_events_topic_arn="arn:aws:sns:us-east-1:123456789012:game-events",
        content_events_topic_arn="arn:aws:sns:us-east-1:123456789012:content-events",
    )



def test_crawl_app_stores_game(
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
        # get_review_summary makes two calls: english then all
        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
            json=REVIEW_SUMMARY_ENGLISH,
        )
        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
            json=REVIEW_SUMMARY_ALL,
        )

        client = _httpx.Client()
        svc = _make_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            sqs,
            queue_url,
            client,
        )
        result = svc.crawl_app(440)

    assert result is True
    game = game_repo.find_by_appid(440)
    assert game is not None
    assert game.name == "Team Fortress 2"
    assert game.developer == "Valve"
    assert game.is_free is True
    assert game.review_count == 188000  # all languages
    assert game.review_count_english == 155000  # English only



def test_crawl_app_handles_steam_error(
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

        client = _httpx.Client()
        svc = _make_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            sqs,
            queue_url,
            client,
        )
        result = svc.crawl_app(440)

    assert result is False
    assert game_repo.find_by_appid(440) is None



def test_crawl_reviews_stores_reviews(
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

        client = _httpx.Client()
        svc = _make_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            sqs,
            queue_url,
            client,
        )
        count = svc.crawl_reviews(440)

    assert count == 4
    assert review_repo.count_by_appid(440) == 4



def test_crawl_reviews_deduplicates(
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

        client = _httpx.Client()
        svc = _make_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            sqs,
            queue_url,
            client,
        )
        svc.crawl_reviews(440)
        svc.crawl_reviews(440)

    # No duplicates — still only 4
    assert review_repo.count_by_appid(440) == 4


# ---------------------------------------------------------------------------
# Eligibility gates on review_count_english, not review_count
# ---------------------------------------------------------------------------



def test_crawl_app_eligibility_uses_english_count(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    """review_status should be 'ineligible' when English count < threshold, even if all-lang exceeds it."""
    import boto3
    import httpx as _httpx

    # English: 30 reviews (below default REVIEW_ELIGIBILITY_THRESHOLD=50)
    english_summary = {
        "success": 1,
        "query_summary": {
            "total_positive": 20,
            "total_negative": 10,
            "total_reviews": 30,
            "review_score": 5,
            "review_score_desc": "Mixed",
        },
        "reviews": [],
    }
    # All languages: 800 reviews (above threshold)
    all_summary = {
        "success": 1,
        "query_summary": {
            "total_positive": 650,
            "total_negative": 150,
            "total_reviews": 800,
            "review_score": 7,
            "review_score_desc": "Positive",
        },
        "reviews": [],
    }

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="review-q-eng-elig")["QueueUrl"]

        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
            json=steam_appdetails_440,
        )
        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
            json=english_summary,
        )
        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
            json=all_summary,
        )

        client = _httpx.Client()
        svc = _make_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            sqs,
            queue_url,
            client,
        )
        svc.crawl_app(440)

    game = game_repo.find_by_appid(440)
    assert game is not None
    assert game.review_count == 800  # all-lang stored for display
    assert game.review_count_english == 30  # English stored separately
    # Catalog status should be ineligible since English count < REVIEW_ELIGIBILITY_THRESHOLD
    entry = catalog_repo.find_by_appid(440)
    assert entry is not None
    assert entry.review_status == "ineligible"


# ---------------------------------------------------------------------------
# S3 archival tests
# ---------------------------------------------------------------------------



def test_crawl_app_archives_to_s3(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    """crawl_app should archive app details to S3 as gzip'd JSON."""
    import gzip

    import boto3
    import httpx as _httpx

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="review-q-s3")["QueueUrl"]

        s3 = MagicMock()

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

        client = _httpx.Client()
        svc = _make_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            sqs,
            queue_url,
            client,
            s3_client=s3,
            archive_bucket="test-archive-bucket",
        )
        svc.crawl_app(440)

    assert s3.put_object.call_count >= 1
    call_kwargs = s3.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == "test-archive-bucket"
    assert "app-details/440/" in call_kwargs["Key"]
    assert call_kwargs["Key"].endswith(".json.gz")
    assert call_kwargs["ContentEncoding"] == "gzip"
    # Verify the body is valid gzip'd JSON
    decompressed = gzip.decompress(call_kwargs["Body"])
    data = json.loads(decompressed)
    assert isinstance(data, dict)



def test_crawl_app_skips_s3_when_unconfigured(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_440: dict,
    httpx_mock: HTTPXMock,
) -> None:
    """No S3 client → no error, no S3 call."""
    import boto3
    import httpx as _httpx

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="review-q-nos3")["QueueUrl"]

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

        client = _httpx.Client()
        svc = _make_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            sqs,
            queue_url,
            client,
            # No s3_client or archive_bucket
        )
        result = svc.crawl_app(440)

    # Should succeed without errors
    assert result is True



def test_crawl_reviews_archives_to_s3(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    httpx_mock: HTTPXMock,
) -> None:
    """crawl_reviews should archive raw reviews to S3 as gzip'd JSON."""
    import gzip

    import boto3
    import httpx as _httpx

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="review-q-s3rev")["QueueUrl"]

        s3 = MagicMock()
        game_repo.ensure_stub(440)

        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
            json=REVIEWS_RESPONSE,
        )

        client = _httpx.Client()
        svc = _make_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            sqs,
            queue_url,
            client,
            s3_client=s3,
            archive_bucket="test-archive-bucket",
        )
        count = svc.crawl_reviews(440)

    assert count == 4
    assert s3.put_object.call_count >= 1
    call_kwargs = s3.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == "test-archive-bucket"
    assert "reviews/440/" in call_kwargs["Key"]
    assert call_kwargs["Key"].endswith(".json.gz")
    decompressed = gzip.decompress(call_kwargs["Body"])
    data = json.loads(decompressed)
    assert isinstance(data, list)
    assert len(data) == 4
