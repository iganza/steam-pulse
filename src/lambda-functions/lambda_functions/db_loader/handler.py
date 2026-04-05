"""DB Loader Lambda — restores a plain pg_dump SQL file from S3 into RDS.

Event: {"key": "..."}
The key must be under db-snapshots/ or db-dumps/. The bucket is derived
from the ENVIRONMENT env var — it cannot be overridden by the caller.

Strategy:
  1. Stream directly from S3 (no /tmp staging) through gzip into line-by-line
     SQL parsing — avoids downloading or holding the full dump in memory.
  2. Execute the entire restore in one transaction: DROP schema, then let
     the dump recreate it — load all statements and COPY blocks, commit
     only on full success. Any failure rolls back, leaving the DB unchanged.

Failures raise — the Lambda emits errorMessage so push-to-staging.sh detects
the failure via its existing "errorMessage" check.
"""

import gzip
import logging
import os
import re
from typing import IO, Iterator  # IO used in _execute_dump signature

import boto3  # type: ignore[import-untyped]
import psycopg2

from library_layer.utils.db import get_conn

logger = logging.getLogger("db-loader")
logger.setLevel(logging.INFO)

_s3 = boto3.client("s3")
_COPY_RE = re.compile(r"COPY\s+", re.IGNORECASE)
# Matches the opening of a dollar-quote tag, e.g. $$ or $tag$
_DOLLAR_QUOTE_RE = re.compile(r"\$([^$]*)\$")
_ALLOWED_KEY_PREFIXES = ("db-snapshots/", "db-dumps/")


class _CopyStream:
    """File-like adapter that streams COPY data from the dump line iterator.

    Passes lines to psycopg2 copy_expert() on demand — avoids buffering the
    entire COPY block in memory, which matters for large tables (games, reports).
    Reads until the pg_dump block terminator '\.' is encountered.
    """

    def __init__(self, lines: Iterator[str]) -> None:
        self._lines = lines
        self._overflow = ""
        self._done = False

    def read(self, size: int = -1) -> str:
        if self._done and not self._overflow:
            return ""

        # Accumulate into a list and join once to avoid quadratic string concat
        # on large COPY blocks.
        chunks: list[str] = [self._overflow]
        self._overflow = ""
        total = len(chunks[0])

        while not self._done and (size == -1 or total < size):
            try:
                line = next(self._lines)
            except StopIteration:
                self._done = True
                break
            if line.rstrip("\n") == "\\.":
                self._done = True
                break
            chunks.append(line)
            total += len(line)

        buf = "".join(chunks)
        if size != -1 and len(buf) > size:
            self._overflow = buf[size:]
            return buf[:size]
        return buf


def _execute_dump(conn: psycopg2.extensions.connection, f: IO[str]) -> None:
    """Execute a plain pg_dump from a text file object, streaming line by line.

    The entire restore runs inside a single transaction. Either everything
    commits or nothing does. On any error the transaction is rolled back,
    leaving the DB in its pre-restore state.

    Handles COPY...FROM stdin blocks via copy_expert().
    Dollar-quoted blocks (e.g. CREATE FUNCTION ... $$ ... $$;) are tracked so
    that semicolons inside the body do not prematurely flush the statement.
    """
    with conn.cursor() as cur:
        # Drop the schema so the dump loads into a clean state.
        # Do NOT pre-create it — the dump contains its own CREATE SCHEMA PUBLIC
        # and a second CREATE would error with "already exists".
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE")

        stmt_buf: list[str] = []
        total_stmts = 0
        total_copy_blocks = 0
        dollar_quote_tag: str | None = None  # None = not inside a dollar-quoted block

        lines = iter(f)

        for line in lines:
            stripped = line.strip()

            # COPY ... FROM stdin block — stream directly to copy_expert, no buffering
            if not stmt_buf and _COPY_RE.match(stripped) and "from stdin" in stripped.lower():
                cur.copy_expert(stripped, _CopyStream(lines))
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
            if (
                stripped.endswith(";")
                and not stripped.startswith("--")
                and dollar_quote_tag is None
            ):
                stmt = "".join(stmt_buf).strip()
                if stmt:
                    cur.execute(stmt)
                    total_stmts += 1
                stmt_buf = []

        # Flush any trailing content (statements not ending with ';')
        if stmt_buf:
            stmt = "".join(stmt_buf).strip()
            if stmt and not stmt.startswith("--"):
                cur.execute(stmt)
                total_stmts += 1

    conn.commit()
    logger.info(
        "Load complete: %d statements, %d COPY blocks",
        total_stmts,
        total_copy_blocks,
    )


def handler(event: dict, context: object) -> dict:
    key = event.get("key", "")

    if not key:
        raise ValueError("Missing required field: key")

    if not any(key.startswith(p) for p in _ALLOWED_KEY_PREFIXES):
        raise ValueError(f"key must be under one of {_ALLOWED_KEY_PREFIXES}, got: {key!r}")

    # Derive bucket from the runtime environment rather than trusting event input.
    # This prevents the function being mis-directed at an unexpected bucket.
    bucket = f"steampulse-assets-{os.environ['ENVIRONMENT']}"

    logger.info("Loading dump from s3://%s/%s", bucket, key)

    response = _s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"]  # StreamingBody — no /tmp staging needed

    conn = get_conn(cursor_factory=None)
    conn.autocommit = False

    try:
        with gzip.open(body, "rt", encoding="utf-8") as f:
            _execute_dump(conn, f)
    except Exception:
        conn.rollback()
        raise

    return {"status": "ok", "message": f"Loaded s3://{bucket}/{key}"}
