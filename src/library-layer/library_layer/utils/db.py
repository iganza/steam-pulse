"""Shared database connection utilities for all Lambda functions."""

import json
import os
from typing import Any

import psycopg2
import psycopg2.extras

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


def get_conn(
    cursor_factory: Any = psycopg2.extras.RealDictCursor,
) -> psycopg2.extensions.connection:
    """Return a cached psycopg2 connection, reconnecting if stale.

    Validates the connection with a lightweight SELECT 1 to detect
    server-side disconnects (RDS maintenance, failover) that psycopg2's
    .closed flag doesn't catch.
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

    _state["conn"] = psycopg2.connect(
        get_db_url(),
        cursor_factory=cursor_factory,
        connect_timeout=5,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )
    return _state["conn"]  # type: ignore[return-value]
