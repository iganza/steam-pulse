"""Unit tests for `utils/db.py` connect retry + transient-error decorator.

Covers behavior introduced to mitigate cold-start ENI-acquisition bursts
in batch Lambdas: configurable connect_timeout, limited retry on transient
OperationalErrors, and short-circuit on permanent auth/identity failures.
"""

from unittest.mock import MagicMock

import psycopg2
import pytest
from library_layer.utils import db as db_module
from library_layer.utils.db import get_conn, retry_on_transient_db_error


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


def test_write_retry_on_transient_operational_error() -> None:
    calls: list[int] = []

    @retry_on_transient_db_error()
    def write() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise psycopg2.OperationalError("connection reset")
        return "ok"

    assert write() == "ok"
    assert len(calls) == 2


def test_write_retry_does_not_retry_integrity_error() -> None:
    calls: list[int] = []

    @retry_on_transient_db_error()
    def write() -> None:
        calls.append(1)
        raise psycopg2.errors.UniqueViolation("duplicate key")

    with pytest.raises(psycopg2.errors.UniqueViolation, match="duplicate key"):
        write()
    assert len(calls) == 1


def test_write_retry_rolls_back_before_retry_on_serialization_failure() -> None:
    """SerializationFailure aborts the tx — the decorator must rollback before retrying."""
    calls: list[int] = []
    mock_conn = MagicMock(spec=psycopg2.extensions.connection)

    class FakeRepo:
        conn = mock_conn

        @retry_on_transient_db_error()
        def write(self) -> str:
            calls.append(1)
            if len(calls) == 1:
                raise psycopg2.errors.SerializationFailure(
                    "could not serialize access due to concurrent update"
                )
            return "ok"

    assert FakeRepo().write() == "ok"
    assert len(calls) == 2
    mock_conn.rollback.assert_called_once_with()
