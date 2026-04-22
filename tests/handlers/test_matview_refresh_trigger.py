"""Tests for matview_refresh/trigger.py — SQS shell that starts the SFN."""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from tests.conftest import MockLambdaContext


def _make_sqs_event(event_type: str) -> dict:
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


@pytest.mark.parametrize(
    "event_type,expected_force,expected_trigger_event",
    [
        ("batch-analysis-complete", True, "batch-analysis-complete"),
        ("report-ready", False, "report-ready"),
        ("catalog-refresh-complete", False, "catalog-refresh-complete"),
    ],
)
def test_classified_event_produces_expected_sfn_input(
    event_type: str,
    expected_force: bool,
    expected_trigger_event: str,
) -> None:
    """SQS event carrying a known event_type yields matching force + trigger_event."""
    sfn = _stub_sfn()
    ssm = _stub_ssm()
    mod = _get_module(sfn, ssm)

    mod.handler(_make_sqs_event(event_type), MockLambdaContext())

    sfn.start_execution.assert_called_once()
    payload = json.loads(sfn.start_execution.call_args.kwargs["input"])
    assert payload == {"force": expected_force, "trigger_event": expected_trigger_event}


def test_unknown_event_type_yields_empty_trigger_event() -> None:
    """Unrecognised event_type → force=false, trigger_event=''."""
    sfn = _stub_sfn()
    ssm = _stub_ssm()
    mod = _get_module(sfn, ssm)

    mod.handler(_make_sqs_event("mystery-event"), MockLambdaContext())

    payload = json.loads(sfn.start_execution.call_args.kwargs["input"])
    assert payload == {"force": False, "trigger_event": ""}


def test_batch_analysis_wins_over_other_events_in_same_batch() -> None:
    """A mixed batch with batch-analysis-complete → force=true wins over report-ready."""
    sfn = _stub_sfn()
    ssm = _stub_ssm()
    mod = _get_module(sfn, ssm)

    rr = json.dumps({"Message": json.dumps({"event_type": "report-ready"})})
    bac = json.dumps({"Message": json.dumps({"event_type": "batch-analysis-complete"})})
    event = {
        "Records": [
            {"messageId": "m1", "body": rr},
            {"messageId": "m2", "body": bac},
        ]
    }
    mod.handler(event, MockLambdaContext())

    payload = json.loads(sfn.start_execution.call_args.kwargs["input"])
    assert payload == {"force": True, "trigger_event": "batch-analysis-complete"}


def test_catalog_refresh_upgrades_report_ready_in_mixed_batch() -> None:
    """report-ready seen first, catalog-refresh-complete seen later → the broader event wins."""
    sfn = _stub_sfn()
    ssm = _stub_ssm()
    mod = _get_module(sfn, ssm)

    rr = json.dumps({"Message": json.dumps({"event_type": "report-ready"})})
    crc = json.dumps({"Message": json.dumps({"event_type": "catalog-refresh-complete"})})
    event = {
        "Records": [
            {"messageId": "m1", "body": rr},
            {"messageId": "m2", "body": crc},
        ]
    }
    mod.handler(event, MockLambdaContext())

    payload = json.loads(sfn.start_execution.call_args.kwargs["input"])
    assert payload == {"force": False, "trigger_event": "catalog-refresh-complete"}


def test_malformed_record_does_not_crash() -> None:
    """Malformed SQS records are skipped; a valid record in the same batch still fires."""
    sfn = _stub_sfn()
    ssm = _stub_ssm()
    mod = _get_module(sfn, ssm)

    event = {
        "Records": [
            {"messageId": "bad", "body": "not-json"},
            {"messageId": "ok", "body": json.dumps({"Message": json.dumps({"event_type": "report-ready"})})},
        ]
    }
    result = mod.handler(event, MockLambdaContext())

    assert "execution_arn" in result
    sfn.start_execution.assert_called_once()
    payload = json.loads(sfn.start_execution.call_args.kwargs["input"])
    assert payload == {"force": False, "trigger_event": "report-ready"}


def test_execution_name_deterministic_per_batch() -> None:
    """Same SQS batch → same execution name so Lambda retries are idempotent."""
    sfn = _stub_sfn()
    ssm = _stub_ssm()
    mod = _get_module(sfn, ssm)

    event = _make_sqs_event("report-ready")
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

    body = json.dumps({"Message": json.dumps({"event_type": "report-ready"})})
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

    result = mod.handler(_make_sqs_event("report-ready"), MockLambdaContext())

    assert result["duplicate"] is True
    assert "execution_name" in result
