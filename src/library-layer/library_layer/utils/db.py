"""Shared database connection utilities for all Lambda functions."""

import json
import logging
import os
from collections.abc import Callable
from functools import wraps
from typing import Any

import psycopg2
import psycopg2.errors
import psycopg2.extras
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

logger = logging.getLogger(__name__)

_state: dict[str, Any] = {}


def get_db_url() -> str:
    """Resolve the PostgreSQL connection URL.

    Tries DATABASE_URL first (local dev / CI).
    Falls back to DB_SECRET_NAME (Lambda production — fetches from Secrets Manager).
    Raises RuntimeError if neither is set.
    """
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    secret_name = os.getenv("DB_SECRET_NAME")
    if secret_name:
        import boto3  # type: ignore[import-untyped]

        sm = boto3.client("secretsmanager")
        secret = json.loads(sm.get_secret_value(SecretId=secret_name)["SecretString"])
        return (
            f"postgresql://{secret['username']}:{secret['password']}"
            f"@{secret['host']}:{secret['port']}/{secret['dbname']}"
        )
    raise RuntimeError("No DATABASE_URL or DB_SECRET_NAME configured")


def _is_transient_connect_error(exc: BaseException) -> bool:
    """Retry transient OperationalErrors; short-circuit permanent auth/identity failures."""
    if not isinstance(exc, psycopg2.OperationalError):
        return False
    msg = str(exc).lower()
    if "password authentication failed" in msg:
        return False
    if "role " in msg and "does not exist" in msg:
        return False
    if "database " in msg and "does not exist" in msg:
        return False
    return True


def _log_connect_retry(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "db_connect_retry attempt=%d exc=%s",
        retry_state.attempt_number,
        exc,
    )


def _connect(url: str, cursor_factory: Any, connect_timeout: int) -> psycopg2.extensions.connection:
    @retry(
        retry=retry_if_exception(_is_transient_connect_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=2) + wait_random(-0.5, 0.5),
        before_sleep=_log_connect_retry,
        reraise=True,
    )
    def _do_connect() -> psycopg2.extensions.connection:
        return psycopg2.connect(
            url,
            cursor_factory=cursor_factory,
            connect_timeout=connect_timeout,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
        )

    return _do_connect()


def get_conn(
    cursor_factory: Any = psycopg2.extras.RealDictCursor,
    connect_timeout: int = 30,
) -> psycopg2.extensions.connection:
    """Return a cached psycopg2 connection, reconnecting if stale.

    Validates the connection with a lightweight SELECT 1 to detect
    server-side disconnects (RDS maintenance, failover) that psycopg2's
    .closed flag doesn't catch.

    The first caller's `connect_timeout` determines the warm-instance
    connection; subsequent queries are unaffected since `connect_timeout`
    only applies to the initial handshake. Batch Lambdas should pass 60s
    to tolerate cold-start ENI-acquisition bursts.
    """
    if "conn" in _state and not _state["conn"].closed:
        conn = _state["conn"]
        try:
            # Skip health check if a transaction is in progress — don't
            # commit/rollback caller's work.
            if conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                return conn  # type: ignore[return-value]

            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            if not conn.autocommit:
                conn.rollback()  # clean up — never commit caller's work
            return conn  # type: ignore[return-value]
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    _state["conn"] = _connect(get_db_url(), cursor_factory, connect_timeout)
    return _state["conn"]  # type: ignore[return-value]


_PERMANENT_WRITE_ERRORS: tuple[type[BaseException], ...] = (
    psycopg2.IntegrityError,
    psycopg2.ProgrammingError,
    psycopg2.DataError,
)


def _is_transient_write_error(exc: BaseException) -> bool:
    # IntegrityError / ProgrammingError / DataError are permanent:
    # retrying a UniqueViolation, syntax error, or bad-type cast just
    # burns Lambda budget. OperationalError / SerializationFailure /
    # DeadlockDetected are transient: the DB momentarily refused the
    # write and a second attempt is meaningful.
    if isinstance(exc, _PERMANENT_WRITE_ERRORS):
        return False
    return isinstance(
        exc,
        psycopg2.OperationalError
        | psycopg2.errors.SerializationFailure
        | psycopg2.errors.DeadlockDetected,
    )


def _rollback_before_retry(retry_state: RetryCallState) -> None:
    # SerializationFailure / DeadlockDetected abort the active psycopg2
    # transaction — without an explicit ROLLBACK the next attempt hits
    # "current transaction is aborted" (a ProgrammingError, which is NOT
    # retried). The health-check path in get_conn() short-circuits on
    # non-IDLE transaction status, so it cannot recover an aborted tx
    # on its own.
    if not retry_state.args:
        return
    self_obj = retry_state.args[0]
    try:
        conn = getattr(self_obj, "conn", None)
    except Exception:
        return
    if conn is None:
        return
    try:
        conn.rollback()
    except Exception:
        pass


def retry_on_transient_db_error(max_attempts: int = 3) -> Callable[..., Any]:
    """Decorator that retries a DB write on transient errors only.

    Transient (retried): OperationalError, SerializationFailure, DeadlockDetected.
    Permanent (re-raised): IntegrityError, ProgrammingError, DataError.

    Before each retry, calls `self.conn.rollback()` if the wrapped callable
    is a bound method on a BaseRepository-style object, so transactions
    aborted by SerializationFailure/DeadlockDetected are reset.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        def _before_sleep(retry_state: RetryCallState) -> None:
            _rollback_before_retry(retry_state)
            exc = retry_state.outcome.exception() if retry_state.outcome else None
            logger.warning(
                "db_write_retry fn=%s attempt=%d exc=%s",
                fn.__name__,
                retry_state.attempt_number,
                exc,
            )

        wrapped = retry(
            retry=retry_if_exception(_is_transient_write_error),
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=2) + wait_random(0, 0.25),
            before_sleep=_before_sleep,
            reraise=True,
        )(fn)

        @wraps(fn)
        def inner(*args: Any, **kwargs: Any) -> Any:
            return wrapped(*args, **kwargs)

        return inner

    return decorator
