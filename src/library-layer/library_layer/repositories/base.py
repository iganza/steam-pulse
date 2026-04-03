"""Base repository with shared psycopg2 cursor helpers."""

from __future__ import annotations

import psycopg2
import psycopg2.extras


class BaseRepository:
    """Common psycopg2 helpers. Subclasses never open connections themselves."""

    def __init__(self, conn: psycopg2.extensions.connection) -> None:
        self.conn = conn

    def _execute(self, sql: str, params: tuple = ()) -> psycopg2.extensions.cursor:
        """Execute a statement and return the cursor (for rowcount / lastrowid)."""
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur

    def _fetchone(
        self, sql: str, params: tuple = ()
    ) -> psycopg2.extras.RealDictRow | None:
        """Execute a SELECT and return the first row as a RealDictRow, or None."""
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone()  # type: ignore[return-value]

    def _fetchall(
        self, sql: str, params: tuple = ()
    ) -> list[psycopg2.extras.RealDictRow]:
        """Execute a SELECT and return all rows as RealDictRows."""
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()  # type: ignore[return-value]
