"""Tests for matview_refresh/trigger.py — SQS shell that starts the SFN."""

import json
from typing import Any
from unittest.mock import MagicMock

from tests.conftest import MockLambdaContext


def _make_sqs_event(event_type: str = "catalog-refresh-complete") -> dict:
    """Build an SQS event with an SNS-wrapped message body."""
    sns_message = json.dumps({"event_type": event_type, "execution_id": "exec-1"})
    return {
        "Records": [
            {
                "messageId": "msg-1",
                "body": json.dumps({"Message": sns_message}),
            }
        ]
    }


def _get_module(sfn_client: MagicMock, ssm_client: MagicMock) -> Any:
    import importlib
    import os

    os.environ.setdefault(
        "MATVIEW_REFRESH_SFN_ARN_PARAM_NAME",
        "/steampulse/test/matview-refresh/sfn-arn",
    )
    import lambda_functions.matview_refresh.trigger as mod

    importlib.reload(mod)
    mod._sfn = sfn_client
    mod._ssm = ssm_client
    mod._cached_arn = ""
    return mod


def _stub_ssm(arn: str = "arn:aws:states:us-east-1:123:stateMachine:test") -> MagicMock:
    ssm = MagicMock()
    ssm.get_parameter.return_value = {"Parameter": {"Value": arn}}
    return ssm


class _ExecutionAlreadyExists(Exception):
    pass


def _stub_sfn() -> MagicMock:
    sfn = MagicMock()
    sfn.start_execution.return_value = {
        "executionArn": "arn:aws:states:us-east-1:123:execution:test:run-1"
    }
    sfn.exceptions.ExecutionAlreadyExists = _ExecutionAlreadyExists
    return sfn


def test_handler_starts_sfn_with_empty_input() -> None:
    """Handler starts SFN with `{}` — no event classification, no force flag."""
    sfn = _stub_sfn()
    ssm = _stub_ssm()
    mod = _get_module(sfn, ssm)

    mod.handler(_make_sqs_event(), MockLambdaContext())

    sfn.start_execution.assert_called_once()
    assert sfn.start_execution.call_args.kwargs["input"] == "{}"


def test_execution_name_deterministic_per_batch() -> None:
    """Same SQS batch → same execution name so Lambda retries are idempotent."""
    sfn = _stub_sfn()
    ssm = _stub_ssm()
    mod = _get_module(sfn, ssm)

    event = _make_sqs_event()
    mod.handler(event, MockLambdaContext())
    first_name = sfn.start_execution.call_args.kwargs["name"]

    sfn.start_execution.reset_mock()
    mod.handler(event, MockLambdaContext())
    second_name = sfn.start_execution.call_args.kwargs["name"]

    assert first_name == second_name


def test_execution_name_is_order_independent() -> None:
    """Records reordered on retry must still hash to the same execution name."""
    sfn = _stub_sfn()
    ssm = _stub_ssm()
    mod = _get_module(sfn, ssm)

    body = json.dumps({"Message": json.dumps({"event_type": "catalog-refresh-complete"})})
    records = [
        {"messageId": "msg-a", "body": body},
        {"messageId": "msg-b", "body": body},
    ]
    mod.handler({"Records": records}, MockLambdaContext())
    first_name = sfn.start_execution.call_args.kwargs["name"]

    sfn.start_execution.reset_mock()
    mod.handler({"Records": list(reversed(records))}, MockLambdaContext())
    second_name = sfn.start_execution.call_args.kwargs["name"]

    assert first_name == second_name


def test_execution_already_exists_is_no_op() -> None:
    """ExecutionAlreadyExists → treated as success, no re-raise."""
    sfn = _stub_sfn()
    sfn.start_execution.side_effect = _ExecutionAlreadyExists("already exists")
    ssm = _stub_ssm()
    mod = _get_module(sfn, ssm)

    result = mod.handler(_make_sqs_event(), MockLambdaContext())

    assert result["duplicate"] is True
    assert "execution_name" in result
