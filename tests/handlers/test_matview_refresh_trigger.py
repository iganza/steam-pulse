"""Tests for matview_refresh/trigger.py — SQS shell that starts the SFN."""

import json
from typing import Any
from unittest.mock import MagicMock

from tests.conftest import MockLambdaContext


def _make_sqs_event(message_id: str = "msg-1") -> dict:
    """Build an SQS event with an SNS-wrapped message body."""
    sns_message = json.dumps(
        {"event_type": "catalog-refresh-complete", "execution_id": "exec-1"}
    )
    return {
        "Records": [
            {
                "messageId": message_id,
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


def test_handler_starts_sfn_with_empty_input_and_daily_name() -> None:
    """Handler starts SFN with `{}` and a `daily-YYYY-MM-DD` execution name."""
    sfn = _stub_sfn()
    ssm = _stub_ssm()
    mod = _get_module(sfn, ssm)

    mod.handler(_make_sqs_event(), MockLambdaContext())

    sfn.start_execution.assert_called_once()
    kwargs = sfn.start_execution.call_args.kwargs
    assert kwargs["input"] == "{}"
    assert kwargs["name"].startswith("daily-")
    # YYYY-MM-DD shape — 10 chars after the "daily-" prefix.
    assert len(kwargs["name"]) == len("daily-YYYY-MM-DD")


def test_execution_name_is_date_derived_not_batch_derived() -> None:
    """Different SQS batches on the same UTC day produce the same execution name.

    This is the idempotency guard: duplicate `catalog-refresh-complete` publishes
    (crawler retries, manual re-runs) collide on ExecutionAlreadyExists instead of
    kicking off a second full matview refresh in the same day.
    """
    sfn = _stub_sfn()
    ssm = _stub_ssm()
    mod = _get_module(sfn, ssm)

    mod.handler(_make_sqs_event("msg-a"), MockLambdaContext())
    first_name = sfn.start_execution.call_args.kwargs["name"]

    sfn.start_execution.reset_mock()
    mod.handler(_make_sqs_event("msg-b"), MockLambdaContext())
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
    assert result["execution_name"].startswith("daily-")
