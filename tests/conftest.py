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

# Expose library_layer and lambda_functions packages to tests
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "library-layer"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "lambda-functions"))

from library_layer.repositories.catalog_repo import CatalogRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.job_repo import JobRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.schema import create_all


_TEST_DB_DEFAULT = "postgresql://postgres:postgres@localhost:5432/steampulse_test"


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


@pytest.fixture(scope="session")
def db_conn() -> Generator[Any, None, None]:
    url = _safe_test_db_url()
    try:
        conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    except Exception:
        pytest.skip("PostgreSQL not available")
    create_all(conn)
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
                     analysis_jobs, game_relations, index_insights
            RESTART IDENTITY CASCADE
        """)
    conn.commit()
    yield


@pytest.fixture
def game_repo(db_conn: Any) -> GameRepository:
    return GameRepository(db_conn)


@pytest.fixture
def review_repo(db_conn: Any) -> ReviewRepository:
    return ReviewRepository(db_conn)


@pytest.fixture
def catalog_repo(db_conn: Any) -> CatalogRepository:
    return CatalogRepository(db_conn)


@pytest.fixture
def report_repo(db_conn: Any) -> ReportRepository:
    return ReportRepository(db_conn)


@pytest.fixture
def tag_repo(db_conn: Any) -> TagRepository:
    return TagRepository(db_conn)


@pytest.fixture
def job_repo(db_conn: Any) -> JobRepository:
    return JobRepository(db_conn)


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
def sfn_client(aws_credentials: None) -> Generator[Any, None, None]:
    from moto import mock_aws
    with mock_aws():
        import boto3
        client = boto3.client("stepfunctions", region_name="us-west-2")
        yield client


@pytest.fixture
def steam_appdetails_440() -> dict:
    return json.loads(
        (Path(__file__).parent / "fixtures/steam_appdetails_440.json").read_text()
    )


@pytest.fixture
def steam_reviews_440() -> dict:
    return json.loads(
        (Path(__file__).parent / "fixtures/steam_reviews_440.json").read_text()
    )


@pytest.fixture(autouse=True)
def _set_default_aws_credentials() -> None:
    """Ensure fake AWS credentials are always set — prevents accidental real calls."""
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
    os.environ.setdefault("AWS_SESSION_TOKEN", "testing")


@pytest.fixture(autouse=True)
def fast_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch random.uniform to 0 so asyncio.sleep jitter is instant in tests."""
    monkeypatch.setattr("random.uniform", lambda a, b: 0)


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
