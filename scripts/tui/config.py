"""TUI configuration — DB connection and AWS client lifecycle."""

import json
import os

import psycopg2
import psycopg2.extras


def connect_db(env: str | None) -> psycopg2.extensions.connection | None:
    """Establish a DB connection based on environment.

    Local (env=None): uses DATABASE_URL from .env.
    Staging/Production: resolves credentials from Secrets Manager, connects via SSH tunnel.
    Returns None if connection fails (caller shows error in UI).
    """
    try:
        if env is None:
            from library_layer.utils.db import get_conn

            return get_conn()

        import boto3

        sm = boto3.client("secretsmanager", region_name="us-west-2")
        secret = json.loads(
            sm.get_secret_value(SecretId=f"steampulse/{env}/db-credentials")["SecretString"]
        )
        default_port = "5434" if env == "production" else "5433"
        port = int(os.environ.get("DB_TUNNEL_PORT", default_port))
        return psycopg2.connect(
            host="127.0.0.1",
            port=port,
            dbname=secret["dbname"],
            user=secret["username"],
            password=secret["password"],
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    except Exception as exc:  # noqa: BLE001
        # Return None — the app will show a DB error indicator
        import sys

        print(f"DB connection failed: {exc}", file=sys.stderr)
        return None
