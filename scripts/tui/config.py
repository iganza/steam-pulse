"""TUI configuration — DB connection and AWS client lifecycle."""

import json
import os

import psycopg2
import psycopg2.extras


def _resolve_db_dsn(env: str | None) -> str | None:
    """Resolve DB connection string. Returns None if unavailable."""
    try:
        if env is None:
            url = os.getenv("DATABASE_URL")
            if url:
                return url
            raise RuntimeError("No DATABASE_URL configured")

        import boto3

        sm = boto3.client("secretsmanager", region_name="us-west-2")
        secret = json.loads(
            sm.get_secret_value(SecretId=f"steampulse/{env}/db-credentials")["SecretString"]
        )
        port = int(os.environ.get("DB_TUNNEL_PORT", "5433"))
        return (
            f"postgresql://{secret['username']}:{secret['password']}"
            f"@127.0.0.1:{port}/{secret['dbname']}"
        )
    except Exception as exc:  # noqa: BLE001
        import sys

        print(f"DB connection failed: {exc}", file=sys.stderr)
        return None


def connect_db(env: str | None) -> psycopg2.extensions.connection | None:
    """Create a single connection for startup validation."""
    dsn = _resolve_db_dsn(env)
    if not dsn:
        return None
    try:
        return psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
    except Exception as exc:  # noqa: BLE001
        import sys

        print(f"DB connection failed: {exc}", file=sys.stderr)
        return None


def new_connection(dsn: str) -> psycopg2.extensions.connection:
    """Create a fresh DB connection for use in a worker thread."""
    return psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
