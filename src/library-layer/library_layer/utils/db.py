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
    """Return a cached psycopg2 connection, reconnecting if closed."""
    if "conn" not in _state or _state["conn"].closed:
        _state["conn"] = psycopg2.connect(get_db_url(), cursor_factory=cursor_factory)
    return _state["conn"]  # type: ignore[return-value]
