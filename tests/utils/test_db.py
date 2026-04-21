"""Unit tests for `utils/db.py` connect retry + transient-error decorator.

Covers behavior introduced to mitigate cold-start ENI-acquisition bursts
in batch Lambdas: configurable connect_timeout, limited retry on transient
OperationalErrors, and short-circuit on permanent auth/identity failures.
"""

from unittest.mock import MagicMock

import psycopg2
import pytest
from library_layer.utils import db as db_module
from library_layer.utils.db import get_conn, run_with_retrying_transaction, transaction


@pytest.fixture(autouse=True)
def _clear_conn_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the module-level connection cache between tests."""
    monkeypatch.setattr(db_module, "_state", {})
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused:unused@localhost:5432/unused")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make tenacity waits instant so retry tests run fast."""
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda _s: None)


def test_connect_default_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """API callers (latency-sensitive) get the default: single attempt, no retry."""
    calls: list[int] = []

    def fake_connect(*_args: object, **_kwargs: object) -> psycopg2.extensions.connection:
        calls.append(1)
        raise psycopg2.OperationalError("timeout expired")

    monkeypatch.setattr(psycopg2, "connect", fake_connect)

    with pytest.raises(psycopg2.OperationalError, match="timeout expired"):
        get_conn()
    assert len(calls) == 1


def test_connect_retry_on_transient_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = MagicMock(spec=psycopg2.extensions.connection)
    mock_conn.closed = False
    calls: list[int] = []

    def fake_connect(*_args: object, **_kwargs: object) -> psycopg2.extensions.connection:
        calls.append(1)
        if len(calls) < 3:
            raise psycopg2.OperationalError("timeout expired")
        return mock_conn

    monkeypatch.setattr(psycopg2, "connect", fake_connect)

    result = get_conn(max_connect_attempts=3)
    assert result is mock_conn
    assert len(calls) == 3


def test_connect_retry_exhaustion_raises_operational_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def fake_connect(*_args: object, **_kwargs: object) -> psycopg2.extensions.connection:
        calls.append(1)
        raise psycopg2.OperationalError("timeout expired")

    monkeypatch.setattr(psycopg2, "connect", fake_connect)

    with pytest.raises(psycopg2.OperationalError, match="timeout expired"):
        get_conn(max_connect_attempts=3)
    assert len(calls) == 3


def test_connect_auth_failure_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_connect(*_args: object, **_kwargs: object) -> psycopg2.extensions.connection:
        calls.append(1)
        raise psycopg2.OperationalError(
            "FATAL: password authentication failed for user \"steampulse\""
        )

    monkeypatch.setattr(psycopg2, "connect", fake_connect)

    with pytest.raises(psycopg2.OperationalError, match="password authentication failed"):
        get_conn(max_connect_attempts=3)
    assert len(calls) == 1


def test_transaction_commits_on_clean_exit() -> None:
    mock_conn = MagicMock(spec=psycopg2.extensions.connection)
    with transaction(mock_conn):
        pass
    mock_conn.commit.assert_called_once_with()
    mock_conn.rollback.assert_not_called()


def test_transaction_rolls_back_on_exception() -> None:
    mock_conn = MagicMock(spec=psycopg2.extensions.connection)
    with pytest.raises(RuntimeError, match="boom"):
        with transaction(mock_conn):
            raise RuntimeError("boom")
    mock_conn.rollback.assert_called_once_with()
    mock_conn.commit.assert_not_called()


def test_run_with_retrying_transaction_retries_transient_operational_error() -> None:
    mock_conn = MagicMock(spec=psycopg2.extensions.connection)
    calls: list[int] = []

    def work() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise psycopg2.OperationalError("connection reset")
        return "ok"

    assert run_with_retrying_transaction(mock_conn, work) == "ok"
    assert len(calls) == 2
    # First attempt rolled back on exception, second attempt committed.
    assert mock_conn.rollback.call_count == 1
    assert mock_conn.commit.call_count == 1


def test_run_with_retrying_transaction_does_not_retry_integrity_error() -> None:
    mock_conn = MagicMock(spec=psycopg2.extensions.connection)
    calls: list[int] = []

    def work() -> None:
        calls.append(1)
        raise psycopg2.errors.UniqueViolation("duplicate key")

    with pytest.raises(psycopg2.errors.UniqueViolation, match="duplicate key"):
        run_with_retrying_transaction(mock_conn, work)
    assert len(calls) == 1
    mock_conn.rollback.assert_called_once_with()


def test_run_with_retrying_transaction_rolls_back_before_retry_on_serialization_failure() -> None:
    """SerializationFailure aborts the tx — the context manager must rollback before retrying."""
    mock_conn = MagicMock(spec=psycopg2.extensions.connection)
    calls: list[int] = []

    def work() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise psycopg2.errors.SerializationFailure(
                "could not serialize access due to concurrent update"
            )
        return "ok"

    assert run_with_retrying_transaction(mock_conn, work) == "ok"
    assert len(calls) == 2
    assert mock_conn.rollback.call_count == 1
    assert mock_conn.commit.call_count == 1
