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
    "REFRESH_REVIEWS_ENABLED": False,
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


def test_crawl_app_stores_usd_price(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_paid_usd: dict,
    httpx_mock: HTTPXMock,
) -> None:
    import boto3
    import httpx as _httpx

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="review-crawl-q-usd")["QueueUrl"]

        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
            json=steam_appdetails_paid_usd,
        )
        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/2084000"),
            json=SMALL_REVIEW_SUMMARY,
        )
        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/2084000"),
            json=SMALL_REVIEW_SUMMARY,
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
        result = svc.crawl_app(2084000)

    assert result is True
    game = game_repo.find_by_appid(2084000)
    assert game is not None
    assert game.is_free is False
    assert float(game.price_usd) == 14.99


def test_crawl_app_nulls_price_on_non_usd(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    steam_appdetails_paid_clp: dict,
    httpx_mock: HTTPXMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    import boto3
    import httpx as _httpx

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="review-crawl-q-clp")["QueueUrl"]

        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
            json=steam_appdetails_paid_clp,
        )
        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/2084001"),
            json=SMALL_REVIEW_SUMMARY,
        )
        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/2084001"),
            json=SMALL_REVIEW_SUMMARY,
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
        with caplog.at_level(logging.WARNING):
            result = svc.crawl_app(2084001)

    assert result is True
    game = game_repo.find_by_appid(2084001)
    assert game is not None
    assert game.is_free is False
    assert game.price_usd is None
    assert any("non-USD price" in rec.message for rec in caplog.records)


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


def test_crawl_reviews_triggers_analysis_by_default(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    httpx_mock: HTTPXMock,
) -> None:
    """Default new-game path must call Step Functions (preserves existing behavior)."""
    import boto3
    import httpx as _httpx

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="review-q-analysis-on")["QueueUrl"]

        game_repo.ensure_stub(440)

        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
            json=REVIEWS_RESPONSE,
        )

        sfn = MagicMock()
        sfn.start_execution.return_value = {"executionArn": "arn:test"}

        client = _httpx.Client()
        svc = _make_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            sqs,
            queue_url,
            client,
            sfn_arn="arn:aws:states:us-east-1:123456789012:stateMachine:test",
            sfn_client=sfn,
        )
        svc.crawl_reviews(440)

    sfn.start_execution.assert_called_once()


def test_crawl_reviews_refresh_skips_analysis(
    game_repo: GameRepository,
    review_repo: ReviewRepository,
    catalog_repo: CatalogRepository,
    tag_repo: TagRepository,
    httpx_mock: HTTPXMock,
) -> None:
    """trigger_analysis=False prevents the ~$1 Step Functions execution."""
    import boto3
    import httpx as _httpx

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="review-q-analysis-off")["QueueUrl"]

        game_repo.ensure_stub(440)

        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
            json=REVIEWS_RESPONSE,
        )

        sfn = MagicMock()

        client = _httpx.Client()
        svc = _make_service(
            game_repo,
            review_repo,
            catalog_repo,
            tag_repo,
            sqs,
            queue_url,
            client,
            sfn_arn="arn:aws:states:us-east-1:123456789012:stateMachine:test",
            sfn_client=sfn,
        )
        svc.crawl_reviews(440, trigger_analysis=False)

    sfn.start_execution.assert_not_called()


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
    """Eligibility is enforced at SNS filter level; crawl_app stores English count regardless."""
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
    # Eligibility is enforced at SNS filter level — catalog entry is still recorded
    entry = catalog_repo.find_by_appid(440)
    assert entry is not None
    assert entry.meta_status == "done"
    assert entry.review_count == 800


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


# ── _maybe_dispatch_review_crawl: inline review-crawl gate (mirrors find_due_reviews) ──


def _make_service_for_dispatch(
    *,
    refresh_reviews_enabled: bool,
    sqs_client: object,
    review_queue_url: str,
) -> CrawlService:
    """Build a minimal CrawlService for unit-testing _maybe_dispatch_review_crawl directly."""
    cfg = SteamPulseConfig(
        **{**_REQUIRED_FIELDS, "REFRESH_REVIEWS_ENABLED": refresh_reviews_enabled}
    )
    return CrawlService(
        game_repo=MagicMock(),
        review_repo=MagicMock(),
        catalog_repo=MagicMock(),
        tag_repo=MagicMock(),
        steam=MagicMock(),
        sqs_client=sqs_client,
        review_queue_url=review_queue_url,
        sns_client=_mock_sns(),
        config=cfg,
        sfn_arn=None,
        sfn_client=None,
        s3_client=None,
        archive_bucket=None,
        game_events_topic_arn="arn:aws:sns:us-east-1:123456789012:game-events",
        content_events_topic_arn="arn:aws:sns:us-east-1:123456789012:content-events",
    )


def _read_queue_messages(sqs_client: object, queue_url: str) -> list[dict]:
    """Drain whatever messages are currently in the queue (max 10) and return parsed bodies."""
    resp = sqs_client.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=0)
    return [json.loads(m["Body"]) for m in resp.get("Messages", [])]


def test_maybe_dispatch_kill_switch_off_never_dispatches() -> None:
    """REFRESH_REVIEWS_ENABLED=False short-circuits before any gate check."""
    import boto3

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="rcq-killswitch")["QueueUrl"]
        svc = _make_service_for_dispatch(
            refresh_reviews_enabled=False, sqs_client=sqs, review_queue_url=queue_url
        )
        # Conditions that would otherwise dispatch (first-fetch eligible game)
        svc._maybe_dispatch_review_crawl(
            appid=440,
            existing=None,
            game_data={
                "review_count": 10_000,
                "review_count_english": 10_000,
                "coming_soon": False,
            },
        )
        assert _read_queue_messages(sqs, queue_url) == []


def test_maybe_dispatch_below_tier_b_threshold_no_dispatch() -> None:
    """Below the tier-B (=eligibility) threshold on TOTAL review_count means tier C."""
    import boto3

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="rcq-below-b")["QueueUrl"]
        svc = _make_service_for_dispatch(
            refresh_reviews_enabled=True, sqs_client=sqs, review_queue_url=queue_url
        )
        # Threshold defaults to 50 (REVIEW_ELIGIBILITY_THRESHOLD). Eligibility gates on
        # review_count (total all-language), matching find_due_reviews().
        svc._maybe_dispatch_review_crawl(
            appid=440,
            existing=None,
            game_data={"review_count": 49, "review_count_english": 49, "coming_soon": False},
        )
        assert _read_queue_messages(sqs, queue_url) == []


def test_maybe_dispatch_eligible_by_total_review_count_even_when_english_below_threshold() -> None:
    """Tier B eligibility uses TOTAL review_count, not English — matches find_due_reviews()."""
    import boto3

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="rcq-total-vs-eng")["QueueUrl"]
        svc = _make_service_for_dispatch(
            refresh_reviews_enabled=True, sqs_client=sqs, review_queue_url=queue_url
        )
        # 60 total reviews ≥ 50 threshold → tier B eligible. Only 30 English — irrelevant
        # for the eligibility gate; would have been wrongly skipped if gate used English.
        svc._maybe_dispatch_review_crawl(
            appid=440,
            existing=None,
            game_data={"review_count": 60, "review_count_english": 30, "coming_soon": False},
        )
        msgs = _read_queue_messages(sqs, queue_url)
        assert len(msgs) == 1
        assert msgs[0]["appid"] == 440


def test_maybe_dispatch_coming_soon_no_dispatch() -> None:
    """Pre-launch games have no reviews to refresh."""
    import boto3

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="rcq-coming-soon")["QueueUrl"]
        svc = _make_service_for_dispatch(
            refresh_reviews_enabled=True, sqs_client=sqs, review_queue_url=queue_url
        )
        svc._maybe_dispatch_review_crawl(
            appid=440,
            existing=None,
            game_data={
                "review_count": 10_000,
                "review_count_english": 10_000,
                "coming_soon": True,
            },
        )
        assert _read_queue_messages(sqs, queue_url) == []


def test_maybe_dispatch_first_fetch_dispatches_when_existing_is_none() -> None:
    """Brand-new game (no prior row) is a first fetch — dispatch."""
    import boto3

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="rcq-first-none")["QueueUrl"]
        svc = _make_service_for_dispatch(
            refresh_reviews_enabled=True, sqs_client=sqs, review_queue_url=queue_url
        )
        svc._maybe_dispatch_review_crawl(
            appid=440,
            existing=None,
            game_data={"review_count": 200, "review_count_english": 200, "coming_soon": False},
        )
        msgs = _read_queue_messages(sqs, queue_url)
        assert len(msgs) == 1
        assert msgs[0]["appid"] == 440
        assert msgs[0]["source"] == "refresh"


def test_maybe_dispatch_first_fetch_dispatches_when_review_crawled_at_is_none() -> None:
    """Existing game with no app_catalog row (LEFT JOIN nulls) is also a first fetch."""
    import boto3

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="rcq-first-null-rca")["QueueUrl"]
        svc = _make_service_for_dispatch(
            refresh_reviews_enabled=True, sqs_client=sqs, review_queue_url=queue_url
        )
        svc._maybe_dispatch_review_crawl(
            appid=440,
            existing={
                "coming_soon": False,
                "review_count_english": 200,
                "review_crawled_at": None,
                "review_count_at_last_fetch": None,
            },
            game_data={"review_count": 200, "review_count_english": 200, "coming_soon": False},
        )
        msgs = _read_queue_messages(sqs, queue_url)
        assert len(msgs) == 1
        assert msgs[0]["appid"] == 440


def test_maybe_dispatch_delta_below_min_and_not_stale_no_dispatch() -> None:
    """Cumulative delta below MIN_DELTA on a recently-fetched game is a no-op."""
    from datetime import UTC, datetime, timedelta

    import boto3

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="rcq-delta-low")["QueueUrl"]
        svc = _make_service_for_dispatch(
            refresh_reviews_enabled=True, sqs_client=sqs, review_queue_url=queue_url
        )
        # MIN_DELTA defaults to 1000; delta = 5000 - 4500 = 500 < 1000.
        # Last fetch 5 days ago — not stale (< 30d).
        svc._maybe_dispatch_review_crawl(
            appid=440,
            existing={
                "coming_soon": False,
                "review_count_english": 4500,
                "review_crawled_at": datetime.now(tz=UTC) - timedelta(days=5),
                "review_count_at_last_fetch": 4500,
            },
            game_data={"review_count": 5000, "review_count_english": 5000, "coming_soon": False},
        )
        assert _read_queue_messages(sqs, queue_url) == []


def test_maybe_dispatch_delta_meets_min_dispatches() -> None:
    """Cumulative delta crossing MIN_DELTA dispatches even on a recently-fetched game."""
    from datetime import UTC, datetime, timedelta

    import boto3

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="rcq-delta-met")["QueueUrl"]
        svc = _make_service_for_dispatch(
            refresh_reviews_enabled=True, sqs_client=sqs, review_queue_url=queue_url
        )
        # delta = 6000 - 4500 = 1500 ≥ 1000 default MIN_DELTA.
        svc._maybe_dispatch_review_crawl(
            appid=440,
            existing={
                "coming_soon": False,
                "review_count_english": 4500,
                "review_crawled_at": datetime.now(tz=UTC) - timedelta(days=2),
                "review_count_at_last_fetch": 4500,
            },
            game_data={"review_count": 6000, "review_count_english": 6000, "coming_soon": False},
        )
        msgs = _read_queue_messages(sqs, queue_url)
        assert len(msgs) == 1
        assert msgs[0]["appid"] == 440


def test_maybe_dispatch_stale_dispatches_even_below_min_delta() -> None:
    """30-day staleness floor fires even when delta is small — safety net for slow growers."""
    from datetime import UTC, datetime, timedelta

    import boto3

    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue_url = sqs.create_queue(QueueName="rcq-stale")["QueueUrl"]
        svc = _make_service_for_dispatch(
            refresh_reviews_enabled=True, sqs_client=sqs, review_queue_url=queue_url
        )
        svc._maybe_dispatch_review_crawl(
            appid=440,
            existing={
                "coming_soon": False,
                "review_count_english": 800,
                "review_crawled_at": datetime.now(tz=UTC) - timedelta(days=31),
                "review_count_at_last_fetch": 800,
            },
            game_data={"review_count": 805, "review_count_english": 805, "coming_soon": False},
        )
        msgs = _read_queue_messages(sqs, queue_url)
        assert len(msgs) == 1
        assert msgs[0]["appid"] == 440
