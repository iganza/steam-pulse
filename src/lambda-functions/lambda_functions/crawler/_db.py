import json
import os

import psycopg2

_conn = None


def get_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    secret_arn = os.getenv("DB_SECRET_ARN")
    if secret_arn:
        import boto3  # type: ignore[import-untyped]
        sm = boto3.client("secretsmanager")
        secret = json.loads(sm.get_secret_value(SecretId=secret_arn)["SecretString"])
        return f"postgresql://{secret['username']}:{secret['password']}@{secret['host']}:{secret['port']}/{secret['dbname']}"
    raise RuntimeError("No DATABASE_URL or DB_SECRET_ARN configured")


def get_conn() -> object:
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(get_db_url())
    return _conn
