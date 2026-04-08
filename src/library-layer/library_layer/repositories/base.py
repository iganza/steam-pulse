"""Base repository with shared psycopg2 cursor helpers."""

from __future__ import annotations

from collections.abc import Callable

import psycopg2
import psycopg2.extras
import psycopg2.sql

# Accepted query shapes: a raw SQL string or a psycopg2.sql Composable
# (SQL/Identifier/Composed) for safely interpolating identifiers like
# table or column names. Both are passed straight through to cur.execute().
SqlQuery = str | psycopg2.sql.Composable


class BaseRepository:
    """Common psycopg2 helpers. Subclasses never open connections themselves.

    Accepts a connection factory (callable) instead of a connection object.
    The factory is called on every access via the `conn` property, ensuring
    stale connections (RDS maintenance, Lambda freeze/thaw) are replaced
    transparently.
    """

    def __init__(self, get_conn: Callable[[], psycopg2.extensions.connection]) -> None:
        self._get_conn = get_conn

    @property
    def conn(self) -> psycopg2.extensions.connection:
        """Get a validated connection — reconnects transparently if stale."""
        return self._get_conn()

    def _execute(self, sql: SqlQuery, params: tuple = ()) -> psycopg2.extensions.cursor:
        """Execute a statement and return the cursor (for rowcount / lastrowid)."""
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur

    def _fetchone(
        self, sql: SqlQuery, params: tuple = ()
    ) -> psycopg2.extras.RealDictRow | None:
        """Execute a SELECT and return the first row as a RealDictRow, or None."""
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone()  # type: ignore[return-value]

    def _fetchall(
        self, sql: SqlQuery, params: tuple = ()
    ) -> list[psycopg2.extras.RealDictRow]:
        """Execute a SELECT and return all rows as RealDictRows."""
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()  # type: ignore[return-value]
