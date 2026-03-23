"""DB Loader Lambda — restores a plain pg_dump SQL file from S3 into RDS.

Event: {"bucket": "...", "key": "..."}
The key must point at a gzipped plain-format pg_dump file on S3.

Strategy:
  1. Download + stream-decompress from S3
  2. Drop public schema and recreate it (clean slate)
  3. Execute SQL statements; COPY...FROM stdin blocks via copy_expert()
"""

import gzip
import io
import logging
import re

import boto3
import psycopg2

from library_layer.utils.db import get_conn

logger = logging.getLogger("db-loader")
logger.setLevel(logging.INFO)

_s3 = boto3.client("s3")
_COPY_RE = re.compile(r"COPY\s+", re.IGNORECASE)


def _execute_dump(conn: psycopg2.extensions.connection, sql: str) -> None:
    """Execute a plain pg_dump SQL string.

    Handles COPY...FROM stdin blocks via copy_expert().
    All other statements are executed one at a time, flushing on each line
    that ends with ';' (which is how pg_dump terminates statements).
    """
    cur = conn.cursor()

    # Wipe existing schema so the dump loads into a clean state.
    cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
    cur.execute("CREATE SCHEMA public")
    conn.commit()

    lines = sql.splitlines(keepends=True)
    i = 0
    stmt_buf: list[str] = []
    total_stmts = 0
    total_copy_blocks = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # COPY ... FROM stdin block — special handling required
        if _COPY_RE.match(stripped) and "from stdin" in stripped.lower():
            # Flush any pending statement first
            if stmt_buf:
                stmt = "".join(stmt_buf).strip()
                if stmt:
                    cur.execute(stmt)
                    conn.commit()
                    total_stmts += 1
                stmt_buf = []

            copy_cmd = stripped  # e.g. "COPY public.games (id, name) FROM stdin;"
            data_lines: list[str] = []
            i += 1
            while i < len(lines):
                if lines[i].rstrip("\n") == "\\.":
                    break
                data_lines.append(lines[i])
                i += 1

            cur.copy_expert(copy_cmd, io.StringIO("".join(data_lines)))
            conn.commit()
            total_copy_blocks += 1
            i += 1
            continue

        # Skip blank lines and pure comment lines when the buffer is empty
        if not stmt_buf and (not stripped or stripped.startswith("--")):
            i += 1
            continue

        stmt_buf.append(line)

        # pg_dump always terminates statements with ';' at the end of a line
        if stripped.endswith(";") and not stripped.startswith("--"):
            stmt = "".join(stmt_buf).strip()
            if stmt:
                try:
                    cur.execute(stmt)
                    conn.commit()
                    total_stmts += 1
                except psycopg2.Error as exc:
                    logger.warning(
                        "Statement failed (skipping): %s — %.120s",
                        exc,
                        stmt,
                    )
                    conn.rollback()
            stmt_buf = []

        i += 1

    # Flush any trailing content
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
        return {"status": "error", "message": "Missing required fields: bucket, key"}

    logger.info("Loading dump from s3://%s/%s", bucket, key)

    local_path = "/tmp/dump.sql.gz"
    _s3.download_file(bucket, key, local_path)

    with gzip.open(local_path, "rt", encoding="utf-8") as f:
        sql = f.read()

    logger.info("Dump decompressed: %d bytes", len(sql))

    conn = get_conn(cursor_factory=None)
    conn.autocommit = False

    try:
        _execute_dump(conn, sql)
    except Exception as exc:
        logger.error("Load failed: %s", exc)
        try:
            conn.rollback()
        except Exception:
            pass
        return {"status": "error", "message": str(exc)}

    return {"status": "ok", "message": f"Loaded s3://{bucket}/{key}"}
