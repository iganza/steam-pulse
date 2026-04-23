"""Shared pytest fixtures and path setup."""

import json
import os
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
import pytest
from psycopg2 import sql as psql

# Expose library_layer and lambda_functions packages to tests
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "library-layer"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "lambda-functions"))

from library_layer.repositories.analytics_repo import AnalyticsRepository
from library_layer.repositories.catalog_repo import CatalogRepository
from library_layer.repositories.chunk_summary_repo import ChunkSummaryRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.job_repo import JobRepository
from library_layer.repositories.matview_repo import MATVIEW_NAMES, MatviewRepository
from library_layer.repositories.merged_summary_repo import MergedSummaryRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.schema import create_all, create_indexes, create_matviews

_TEST_DB_DEFAULT = "postgresql://steampulse:dev@localhost:5432/steampulse_test"


def _safe_test_db_url() -> str:
    """Return the test DB URL, refusing to use a non-test database."""
    url = os.environ.get("TEST_DATABASE_URL") or _TEST_DB_DEFAULT
    # Safety: abort hard if the URL doesn't look like a test database.
    db_name = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    if "test" not in db_name:
        pytest.exit(
            f"\n\n💥 REFUSING TO RUN TESTS: '{db_name}' does not contain 'test'.\n"
            "Set TEST_DATABASE_URL to a dedicated test database, e.g.:\n"
            "  TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/steampulse_test\n"
            "Never point TEST_DATABASE_URL at a production or dev database.\n",
            returncode=1,
        )
    return url


# Set DATABASE_URL so that handler module-level init (get_db_url()) uses the
# test database. This must happen before any handler import.
os.environ.setdefault("DATABASE_URL", _safe_test_db_url())

# Set all required SteamPulseConfig env vars before handler imports trigger
# module-level SteamPulseConfig() construction.
_TEST_ENV_DEFAULTS = {
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_SESSION_TOKEN": "testing",
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
    "RESEND_API_KEY_SECRET_NAME": "steampulse/test/resend-api-key",
    "EMAIL_QUEUE_PARAM_NAME": "/steampulse/test/messaging/email-queue-url",
    "LLM_MODEL__CHUNKING": "anthropic.claude-haiku-test-v1:0",
    "LLM_MODEL__MERGING": "anthropic.claude-sonnet-test-v1:0",
    "LLM_MODEL__SUMMARIZER": "anthropic.claude-sonnet-test-v1:0",
    "LLM_MODEL__GENRE_SYNTHESIS": "anthropic.claude-sonnet-test-v1:0",
    "BATCH_BUCKET_NAME": "test-batch-bucket",
    "BEDROCK_BATCH_ROLE_ARN": "arn:aws:iam::123456789012:role/test-bedrock-role",
    "PRIMARY_REGION": "us-east-1",
    "SPOKE_RESULTS_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/spoke-results",
    "SPOKE_REGIONS": "us-east-1",
    "SPOKE_CRAWL_QUEUE_URLS": "https://sqs.us-east-1.amazonaws.com/123456789012/steampulse-spoke-crawl-us-east-1-test",
}
for _k, _v in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_k, _v)


@pytest.fixture(scope="session")
def db_conn() -> Generator[Any, None, None]:
    url = _safe_test_db_url()
    try:
        conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    except Exception:
        pytest.skip("PostgreSQL not available")
    create_all(conn)
    create_indexes(conn)
    create_matviews(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def clean_tables(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Truncate all tables before each test — only when db_conn is available."""
    # Only truncate if the test actually uses the db_conn fixture (directly or
    # indirectly). Tests that don't use it (legacy mock-based tests) should not
    # be affected.
    if "db_conn" not in request.fixturenames:
        yield
        return
    conn = request.getfixturevalue("db_conn")
    with conn.cursor() as cur:
        cur.execute("""
            TRUNCATE games, reviews, tags, game_tags, genres, game_genres,
                     game_categories, reports, app_catalog, rate_limits,
                     analysis_jobs, game_relations, index_insights,
                     chunk_summaries, merged_summaries, mv_genre_synthesis,
                     matview_refresh_log
            RESTART IDENTITY CASCADE
        """)
    conn.commit()
    yield


@pytest.fixture
def refresh_matviews(db_conn: Any) -> Any:
    """Return a callable that refreshes all materialized views.

    Analytics tests that seed data and then query matview-backed methods
    must call this after seeding: ``refresh_matviews()``
    """
    def _refresh() -> None:
        prev = db_conn.autocommit
        db_conn.autocommit = True
        try:
            with db_conn.cursor() as cur:
                for name in MATVIEW_NAMES:
                    cur.execute(
                        psql.SQL("REFRESH MATERIALIZED VIEW CONCURRENTLY {}").format(
                            psql.Identifier(name)
                        )
                    )
        finally:
            db_conn.autocommit = prev

    return _refresh


@pytest.fixture
def matview_repo(db_conn: Any) -> MatviewRepository:
    return MatviewRepository(lambda: db_conn)


@pytest.fixture
def analytics_repo(db_conn: Any) -> AnalyticsRepository:
    return AnalyticsRepository(lambda: db_conn)


@pytest.fixture
def game_repo(db_conn: Any) -> GameRepository:
    return GameRepository(lambda: db_conn)


@pytest.fixture
def review_repo(db_conn: Any) -> ReviewRepository:
    return ReviewRepository(lambda: db_conn)


@pytest.fixture
def catalog_repo(db_conn: Any) -> CatalogRepository:
    return CatalogRepository(lambda: db_conn)


@pytest.fixture
def report_repo(db_conn: Any) -> ReportRepository:
    return ReportRepository(lambda: db_conn)


@pytest.fixture
def chunk_summary_repo(db_conn: Any) -> ChunkSummaryRepository:
    return ChunkSummaryRepository(lambda: db_conn)


@pytest.fixture
def merged_summary_repo(db_conn: Any) -> MergedSummaryRepository:
    return MergedSummaryRepository(lambda: db_conn)


@pytest.fixture
def tag_repo(db_conn: Any) -> TagRepository:
    return TagRepository(lambda: db_conn)


@pytest.fixture
def job_repo(db_conn: Any) -> JobRepository:
    return JobRepository(lambda: db_conn)


@pytest.fixture
def aws_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")


@pytest.fixture
def sqs_client(aws_credentials: None) -> Generator[Any, None, None]:
    from moto import mock_aws

    with mock_aws():
        import boto3

        client = boto3.client("sqs", region_name="us-west-2")
        yield client


@pytest.fixture
def mock_queues(sqs_client: Any) -> dict[str, str]:
    app_q = sqs_client.create_queue(QueueName="app-crawl-queue")["QueueUrl"]
    review_q = sqs_client.create_queue(QueueName="review-crawl-queue")["QueueUrl"]
    return {"app": app_q, "review": review_q}


@pytest.fixture
def sns_client(aws_credentials: None) -> Generator[Any, None, None]:
    from moto import mock_aws

    with mock_aws():
        import boto3

        client = boto3.client("sns", region_name="us-west-2")
        yield client


@pytest.fixture
def sfn_client(aws_credentials: None) -> Generator[Any, None, None]:
    from moto import mock_aws

    with mock_aws():
        import boto3

        client = boto3.client("stepfunctions", region_name="us-west-2")
        yield client


@pytest.fixture
def steam_appdetails_440() -> dict:
    return json.loads((Path(__file__).parent / "fixtures/steam_appdetails_440.json").read_text())


@pytest.fixture
def steam_appdetails_paid_usd() -> dict:
    return json.loads(
        (Path(__file__).parent / "fixtures/steam_appdetails_paid_usd.json").read_text()
    )


@pytest.fixture
def steam_appdetails_paid_clp() -> dict:
    return json.loads(
        (Path(__file__).parent / "fixtures/steam_appdetails_paid_clp.json").read_text()
    )


@pytest.fixture
def steam_reviews_440() -> dict:
    return json.loads((Path(__file__).parent / "fixtures/steam_reviews_440.json").read_text())


@pytest.fixture(autouse=True)
def _set_default_aws_credentials() -> None:
    """Ensure fake AWS credentials are always set — prevents accidental real calls.
    Core values are set at module level in conftest for handler import safety;
    this fixture is retained as a no-op hook in case per-test overrides are needed.
    """


@pytest.fixture(autouse=True)
def fast_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch random.uniform to 0 so asyncio.sleep jitter is instant in tests."""
    monkeypatch.setattr("random.uniform", lambda a, b: 0)


@pytest.fixture(autouse=True)
def mock_deck_compat(request: pytest.FixtureRequest) -> None:
    """Auto-mock the Steam Deck compatibility endpoint for all tests using httpx_mock."""
    if "httpx_mock" not in request.fixturenames:
        return
    import re as _re

    httpx_mock = request.getfixturevalue("httpx_mock")
    httpx_mock.add_response(
        url=_re.compile(
            r"https://store\.steampowered\.com/saleaction/ajaxgetdeckappcompatibilityreport"
        ),
        json={
            "success": 1,
            "results": {
                "appid": 440,
                "resolved_category": 2,
                "resolved_items": [
                    {
                        "display_type": 3,
                        "loc_token": "#SteamDeckVerified_TestResult_DefaultControllerConfigNotFullyFunctional",
                    },
                    {
                        "display_type": 4,
                        "loc_token": "#SteamDeckVerified_TestResult_DefaultConfigurationIsPerformant",
                    },
                ],
            },
        },
        is_optional=True,
    )


class MockLambdaContext:
    function_name = "test-function"
    function_version = "$LATEST"
    memory_limit_in_mb = 128
    invoked_function_arn = "arn:aws:lambda:us-west-2:123456789012:function:test"
    aws_request_id = "test-request-id"
    log_group_name = "/aws/lambda/test-function"
    log_stream_name = "test-stream"

    def get_remaining_time_in_millis(self) -> int:
        return 30000


@pytest.fixture
def lambda_context() -> "MockLambdaContext":
    return MockLambdaContext()
