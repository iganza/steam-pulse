"""Shared database connection utilities for all Lambda functions."""

import json
import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

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


def _connect(
    url: str,
    cursor_factory: Any,
    connect_timeout: int,
    max_attempts: int,
) -> psycopg2.extensions.connection:
    @retry(
        retry=retry_if_exception(_is_transient_connect_error),
        stop=stop_after_attempt(max_attempts),
        # Positive-only jitter: base wait is always ≥1s, but guarding
        # against accidental ValueError from time.sleep if min is ever
        # lowered below 0.5s is cheap insurance.
        wait=wait_exponential(multiplier=1, min=1, max=2) + wait_random(0, 0.5),
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
    connect_timeout: int = 5,
    max_connect_attempts: int = 1,
) -> psycopg2.extensions.connection:
    """Return a cached psycopg2 connection, reconnecting if stale.

    Validates the connection with a lightweight SELECT 1 to detect
    server-side disconnects (RDS maintenance, failover) that psycopg2's
    .closed flag doesn't catch.

    The first caller's `connect_timeout` / `max_connect_attempts` determine
    the warm-instance connection config; subsequent queries are unaffected
    since these only apply to the initial handshake. Defaults are tuned
    for latency-sensitive API callers (single attempt, 5s — fails fast so
    upstream retry layers recover quickly instead of the API burning its
    whole Lambda budget on a slow connect). Batch Lambdas opt in to retries
    by passing `max_connect_attempts=3` with a longer per-attempt
    `connect_timeout` sized to fit their Lambda timeout budget.
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

    _state["conn"] = _connect(
        get_db_url(), cursor_factory, connect_timeout, max_connect_attempts
    )
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
    # Tuple form (not PEP-604 union) is intentional: isinstance prefers
    # tuples, and some static-analysis tooling still misreads unions here.
    return isinstance(  # noqa: UP038
        exc,
        (
            psycopg2.OperationalError,
            psycopg2.errors.SerializationFailure,
            psycopg2.errors.DeadlockDetected,
        ),
    )


T = TypeVar("T")


@contextmanager
def transaction(conn: psycopg2.extensions.connection) -> Iterator[None]:
    """Commit on clean exit, rollback on any exception — including commit-time.

    Handlers own the transaction boundary; repository write methods no
    longer commit themselves. Wrap each business unit-of-work in one
    `with transaction(get_conn()):` block so a handler's 3-5 repo calls
    close with a single commit (one WAL fsync) instead of N.

    The commit is inside the try block so a SerializationFailure or
    OperationalError at commit time triggers rollback and re-raises,
    leaving the connection in a clean state instead of an aborted tx
    that would poison the next caller.
    """
    try:
        yield
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            # Rollback itself failed (dead connection). Don't mask the
            # original exception with the rollback error.
            pass
        raise


def run_with_retrying_transaction(
    conn: psycopg2.extensions.connection,
    fn: Callable[[], T],
    max_attempts: int = 3,
) -> T:
    """Run `fn` inside a transaction(conn), retrying the whole unit-of-work
    on transient DB errors (SerializationFailure, DeadlockDetected,
    OperationalError). `fn` must be idempotent — the entire body replays
    on retry. Use when a handler touches multiple idempotent upserts and
    wants resilience without the correctness hazard of per-method retry
    (which would roll back earlier writes in the same transaction).
    """

    def _before_sleep(retry_state: RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        logger.warning(
            "db_tx_retry attempt=%d exc=%s",
            retry_state.attempt_number,
            exc,
        )

    @retry(
        retry=retry_if_exception(_is_transient_write_error),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=2) + wait_random(0, 0.25),
        before_sleep=_before_sleep,
        reraise=True,
    )
    def _attempt() -> T:
        with transaction(conn):
            return fn()

    return _attempt()
