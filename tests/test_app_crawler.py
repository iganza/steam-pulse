"""Tests for app_crawler Lambda handler."""

import json
import os
import re
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws
from pytest_httpx import HTTPXMock


def make_sqs_event(appids: list[int]) -> dict:
    return {
        "Records": [
            {
                "messageId": f"msg-{appid}",
                "body": json.dumps({"appid": appid}),
                "receiptHandle": "receipt",
            }
            for appid in appids
        ]
    }


def _mock_db_conn() -> tuple[MagicMock, MagicMock]:
    """Return (mock_conn, mock_cursor) with fetchone returning None by default."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = None  # no existing game row → old_review_count = 0
    return mock_conn, mock_cursor


@mock_aws
def test_handler_processes_single_appid(
    httpx_mock: HTTPXMock,
    steam_appdetails_440: dict,
    steamspy_appinfo_440: dict,
) -> None:
    """Handler fetches Steam + SteamSpy data, writes to DB, queues for review crawl."""
    # Create moto SQS queue for review crawl
    sqs = boto3.client("sqs", region_name="us-east-1")
    queue = sqs.create_queue(QueueName="test-review-queue")
    queue_url = queue["QueueUrl"]

    os.environ["REVIEW_CRAWL_QUEUE_URL"] = queue_url
    os.environ["DATABASE_URL"] = "postgresql://test:test@localhost/test"

    # Register httpx responses
    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
        json=steam_appdetails_440,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://steamspy\.com/api\.php"),
        json=steamspy_appinfo_440,
    )

    mock_conn, mock_cursor = _mock_db_conn()
    with patch("psycopg2.connect", return_value=mock_conn):
        from lambda_functions.app_crawler.handler import handler

        result = handler(make_sqs_event([440]), {})

    assert result["success"] == 1
    assert result["failure"] == 0

    # DB write attempted — INSERT INTO games was executed
    execute_calls = [str(c) for c in mock_cursor.execute.call_args_list]
    assert any("INSERT INTO games" in c for c in execute_calls), (
        "Expected INSERT INTO games but got: " + str(execute_calls)
    )

    # appid 440 queued to review-crawl-queue
    msgs = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10)
    assert len(msgs.get("Messages", [])) >= 1
    body = json.loads(msgs["Messages"][0]["Body"])
    assert body["appid"] == 440


@mock_aws
def test_handler_skips_on_steam_api_failure(httpx_mock: HTTPXMock) -> None:
    """When Steam Store returns 500, handler logs error, does NOT write to DB."""
    os.environ["DATABASE_URL"] = "postgresql://test:test@localhost/test"
    os.environ.pop("REVIEW_CRAWL_QUEUE_URL", None)

    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
        status_code=500,
    )

    mock_conn, mock_cursor = _mock_db_conn()
    with patch("psycopg2.connect", return_value=mock_conn):
        from lambda_functions.app_crawler.handler import handler

        result = handler(make_sqs_event([440]), {})

    assert result["failure"] == 1
    assert result["success"] == 0

    # No DB writes attempted
    assert mock_cursor.execute.call_count == 0


@mock_aws
def test_handler_processes_batch(
    httpx_mock: HTTPXMock,
    steam_appdetails_440: dict,
    steamspy_appinfo_440: dict,
) -> None:
    """Batch of 3 appids: all succeed, DB write called 3 times."""
    sqs = boto3.client("sqs", region_name="us-east-1")
    queue = sqs.create_queue(QueueName="batch-review-queue")
    os.environ["REVIEW_CRAWL_QUEUE_URL"] = queue["QueueUrl"]
    os.environ["DATABASE_URL"] = "postgresql://test:test@localhost/test"

    # Register responses for each appid (3 each for app_details + steamspy)
    for _ in range(3):
        httpx_mock.add_response(
            url=re.compile(r"https://store\.steampowered\.com/api/appdetails"),
            json=steam_appdetails_440,
        )
        httpx_mock.add_response(
            url=re.compile(r"https://steamspy\.com/api\.php"),
            json=steamspy_appinfo_440,
        )

    mock_conn, mock_cursor = _mock_db_conn()
    with patch("psycopg2.connect", return_value=mock_conn):
        from lambda_functions.app_crawler.handler import handler

        result = handler(make_sqs_event([440, 440, 440]), {})

    assert result["success"] == 3
    assert result["failure"] == 0

    # INSERT INTO games called once per appid
    games_inserts = [
        c for c in mock_cursor.execute.call_args_list
        if "INSERT INTO games" in str(c)
    ]
    assert len(games_inserts) == 3
