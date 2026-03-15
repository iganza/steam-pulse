"""DB loader Lambda — restores a pg_dump (plain SQL, gzipped) from S3 into Aurora.

Invoked manually via scripts/dev/push-to-staging.sh.
Event: {"bucket": "...", "key": "db-dumps/dump.sql.gz"}

Uses psycopg2 directly (no psql binary needed in Lambda).
The dump must be plain-format SQL (pg_dump --no-owner --no-acl), not custom format.
"""

import gzip
import io
import json
import os

import boto3
import psycopg2


def handler(event: dict, context) -> dict:
    bucket = event["bucket"]
    key = event["key"]

    secret_arn = os.environ["DB_SECRET_ARN"]
    sm = boto3.client("secretsmanager")
    secret = json.loads(sm.get_secret_value(SecretId=secret_arn)["SecretString"])

    dsn = (
        f"host={secret['host']} port={secret.get('port', 5432)} "
        f"dbname={secret['dbname']} user={secret['username']} password={secret['password']}"
    )

    # Download and decompress dump from S3 in memory
    s3 = boto3.client("s3")
    buf = io.BytesIO()
    s3.download_fileobj(bucket, key, buf)
    buf.seek(0)
    sql = gzip.decompress(buf.read()).decode("utf-8")

    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
    finally:
        conn.close()

    return {"status": "ok", "key": key, "bytes": len(sql)}
