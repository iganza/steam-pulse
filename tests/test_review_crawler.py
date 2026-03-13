"""Tests for review_crawler Lambda handler."""

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
                "receiptHandle": "r",
            }
            for appid in appids
        ]
    }


def _mock_db_conn_with_game() -> tuple[MagicMock, MagicMock]:
    """Return (mock_conn, mock_cursor) where game row exists and has name."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    # fetchone calls in order:
    #   1. _ensure_game_row: SELECT 1 FROM games → (1,) means game exists
    #   2. crawl_reviews: SELECT name FROM games → ("Team Fortress 2",)
    mock_cursor.fetchone.side_effect = [(1,), ("Team Fortress 2",)]
    return mock_conn, mock_cursor


@mock_aws
def test_handler_fetches_and_stores_reviews(
    httpx_mock: HTTPXMock,
    steam_reviews_440: dict,
    lambda_context: "MockLambdaContext",
) -> None:
    """Handler fetches reviews, writes to DB, triggers Step Functions."""
    os.environ["DATABASE_URL"] = "postgresql://test:test@localhost/test"

    # Create moto state machine
    sfn_client = boto3.client("stepfunctions", region_name="us-east-1")
    sm = sfn_client.create_state_machine(
        name="test-analysis-machine",
        definition=json.dumps({
            "Comment": "test",
            "StartAt": "Done",
            "States": {"Done": {"Type": "Succeed"}},
        }),
        roleArn="arn:aws:iam::123456789012:role/test-role",
    )
    os.environ["SFN_ARN"] = sm["stateMachineArn"]

    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=steam_reviews_440,
    )

    mock_conn, mock_cursor = _mock_db_conn_with_game()
    with patch("psycopg2.connect", return_value=mock_conn):
        from lambda_functions.review_crawler.handler import handler

        result = handler(make_sqs_event([440]), lambda_context)

    assert result["batchItemFailures"] == []  # no failures
    # reviews were stored (checked via DB mock above)

    # DB write attempted — INSERT INTO reviews was executed
    execute_calls = [str(c) for c in mock_cursor.execute.call_args_list]
    assert any("INSERT INTO reviews" in c for c in execute_calls), (
        "Expected INSERT INTO reviews but got: " + str(execute_calls)
    )

    # Step Functions execution started
    execs = sfn_client.list_executions(stateMachineArn=sm["stateMachineArn"])
    assert len(execs["executions"]) == 1
    exec_arn = execs["executions"][0]["executionArn"]
    described = sfn_client.describe_execution(executionArn=exec_arn)
    payload = json.loads(described["input"])
    assert payload["appid"] == 440
    assert payload["game_name"] == "Team Fortress 2"


@mock_aws
def test_handler_starts_sfn_after_reviews(
    httpx_mock: HTTPXMock,
    steam_reviews_440: dict,
    lambda_context: "MockLambdaContext",
) -> None:
    """Step Functions is triggered with correct ARN and appid in input."""
    os.environ["DATABASE_URL"] = "postgresql://test:test@localhost/test"

    sfn_client = boto3.client("stepfunctions", region_name="us-east-1")
    sm = sfn_client.create_state_machine(
        name="test-analysis-machine-2",
        definition=json.dumps({
            "Comment": "test",
            "StartAt": "Done",
            "States": {"Done": {"Type": "Succeed"}},
        }),
        roleArn="arn:aws:iam::123456789012:role/test-role",
    )
    sfn_arn = sm["stateMachineArn"]
    os.environ["SFN_ARN"] = sfn_arn

    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json=steam_reviews_440,
    )

    mock_conn, mock_cursor = _mock_db_conn_with_game()
    with patch("psycopg2.connect", return_value=mock_conn):
        from lambda_functions.review_crawler.handler import handler

        handler(make_sqs_event([440]), lambda_context)

    execs = sfn_client.list_executions(stateMachineArn=sfn_arn)
    assert len(execs["executions"]) == 1

    exec_arn = execs["executions"][0]["executionArn"]
    described = sfn_client.describe_execution(executionArn=exec_arn)
    assert described["stateMachineArn"] == sfn_arn

    payload = json.loads(described["input"])
    assert payload["appid"] == 440


@mock_aws
def test_handler_tolerates_empty_reviews(
    httpx_mock: HTTPXMock,
    lambda_context: "MockLambdaContext",
) -> None:
    """When reviews API returns 0 reviews, handler completes without error, SFN NOT triggered."""
    os.environ["DATABASE_URL"] = "postgresql://test:test@localhost/test"

    sfn_client = boto3.client("stepfunctions", region_name="us-east-1")
    sm = sfn_client.create_state_machine(
        name="test-analysis-machine-3",
        definition=json.dumps({
            "Comment": "test",
            "StartAt": "Done",
            "States": {"Done": {"Type": "Succeed"}},
        }),
        roleArn="arn:aws:iam::123456789012:role/test-role",
    )
    os.environ["SFN_ARN"] = sm["stateMachineArn"]

    httpx_mock.add_response(
        url=re.compile(r"https://store\.steampowered\.com/appreviews/440"),
        json={"success": 1, "reviews": [], "cursor": ""},
    )

    mock_conn = MagicMock()
    with patch("psycopg2.connect", return_value=mock_conn):
        from lambda_functions.review_crawler.handler import handler

        result = handler(make_sqs_event([440]), lambda_context)

    assert result["batchItemFailures"] == []
    # no reviews: DB insert not called

    # No Step Functions executions triggered
    execs = sfn_client.list_executions(stateMachineArn=sm["stateMachineArn"])
    assert len(execs["executions"]) == 0
