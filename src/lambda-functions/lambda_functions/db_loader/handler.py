"""DB Loader Lambda — restores a plain pg_dump SQL file from S3 into RDS.

Event: {"bucket": "...", "key": "..."}
The key must point at a gzipped plain-format pg_dump file on S3.

Strategy:
  1. Download gzipped dump from S3 to /tmp
  2. Stream-decompress line by line — avoids loading the full SQL into memory
  3. Drop public schema and recreate it (clean slate)
  4. Execute SQL statements; COPY...FROM stdin blocks via copy_expert()

Failures abort immediately and raise — the Lambda reports an error payload
so the caller (push-to-staging.sh) can detect and surface the failure.
"""

import gzip
import io
import logging
import re
from typing import IO

import boto3
import psycopg2

from library_layer.utils.db import get_conn

logger = logging.getLogger("db-loader")
logger.setLevel(logging.INFO)

_s3 = boto3.client("s3")
_COPY_RE = re.compile(r"COPY\s+", re.IGNORECASE)
# Matches the opening of a dollar-quote tag, e.g. $$ or $tag$
_DOLLAR_QUOTE_RE = re.compile(r"\$([^$]*)\$")


def _execute_dump(conn: psycopg2.extensions.connection, f: IO[str]) -> None:
    """Execute a plain pg_dump from a text file object, streaming line by line.

    Handles COPY...FROM stdin blocks via copy_expert().
    Fails fast on the first statement error — a partial restore is worse than
    a clean failure.

    Dollar-quoted blocks (e.g. CREATE FUNCTION ... $$ ... $$;) are tracked so
    that semicolons inside the body do not prematurely flush the statement.
    """
    cur = conn.cursor()

    cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
    cur.execute("CREATE SCHEMA public")
    conn.commit()

    stmt_buf: list[str] = []
    total_stmts = 0
    total_copy_blocks = 0
    dollar_quote_tag: str | None = None  # None = not inside a dollar-quoted block

    lines = iter(f)

    for line in lines:
        stripped = line.strip()

        # COPY ... FROM stdin block — special handling required
        if not stmt_buf and _COPY_RE.match(stripped) and "from stdin" in stripped.lower():
            copy_cmd = stripped
            data_lines: list[str] = []
            for data_line in lines:
                if data_line.rstrip("\n") == "\\.":
                    break
                data_lines.append(data_line)
            cur.copy_expert(copy_cmd, io.StringIO("".join(data_lines)))
            conn.commit()
            total_copy_blocks += 1
            continue

        # Skip blank lines and pure comment lines when the buffer is empty
        if not stmt_buf and (not stripped or stripped.startswith("--")):
            continue

        stmt_buf.append(line)

        # Track entry/exit of dollar-quoted blocks so we don't flush mid-body
        for match in _DOLLAR_QUOTE_RE.finditer(stripped):
            tag = match.group(0)  # e.g. "$$" or "$body$"
            if dollar_quote_tag is None:
                dollar_quote_tag = tag
            elif tag == dollar_quote_tag:
                dollar_quote_tag = None

        # Flush when the line ends with ';' and we're not inside a dollar-quote
        if stripped.endswith(";") and not stripped.startswith("--") and dollar_quote_tag is None:
            stmt = "".join(stmt_buf).strip()
            if stmt:
                cur.execute(stmt)
                conn.commit()
                total_stmts += 1
            stmt_buf = []

    # Flush any trailing content (statements not ending with ';')
    if stmt_buf:
        stmt = "".join(stmt_buf).strip()
        if stmt and not stmt.startswith("--"):
            cur.execute(stmt)
            conn.commit()
            total_stmts += 1

    logger.info(
        "Load complete: %d statements, %d COPY blocks",
        total_stmts,
        total_copy_blocks,
    )


def handler(event: dict, context: object) -> dict:
    bucket = event.get("bucket", "")
    key = event.get("key", "")

    if not bucket or not key:
        raise ValueError("Missing required fields: bucket, key")

    logger.info("Loading dump from s3://%s/%s", bucket, key)

    local_path = "/tmp/dump.sql.gz"
    _s3.download_file(bucket, key, local_path)

    conn = get_conn(cursor_factory=None)
    conn.autocommit = False

    with gzip.open(local_path, "rt", encoding="utf-8") as f:
        _execute_dump(conn, f)

    return {"status": "ok", "message": f"Loaded s3://{bucket}/{key}"}
