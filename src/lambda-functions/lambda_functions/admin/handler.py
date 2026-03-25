"""Admin Lambda — lightweight DB operations invoked by sp.py.

Actions:
  {"action": "init"}     — no-op placeholder (schema and indexes managed by yoyo migrations)
  {"action": "status"}   — return table names and row counts
  {"action": "query", "sql": "SELECT ..."}  — run a read-only SQL query

This Lambda is in the VPC with DB access. No public exposure.
"""

import logging

import psycopg2.sql

from library_layer.utils.db import get_conn

logger = logging.getLogger("admin")
logger.setLevel(logging.INFO)

MAX_QUERY_ROWS = 500

_conn = get_conn()
# Use autocommit so reads don't hold open transactions across warm invocations.
_conn.autocommit = True

_FORBIDDEN_CTE_KEYWORDS = (
    " INSERT ", " UPDATE ", " DELETE ", " MERGE ",
    " CREATE ", " ALTER ", " DROP ",
)


def _check_sql_safe(sql: str) -> str | None:
    """Return an error message if the SQL is not allowed, else None."""
    if ";" in sql:
        return "Multiple SQL statements are not allowed"
    sql_upper = " " + " ".join(sql.split()).upper() + " "
    first_word = sql_upper.strip().split()[0] if sql_upper.strip() else ""
    if first_word not in ("SELECT", "EXPLAIN", "SHOW", "WITH"):
        return f"Only read-only queries allowed, got: {first_word}"
    if first_word == "EXPLAIN" and sql_upper.lstrip().startswith("EXPLAIN ANALYZE"):
        return "EXPLAIN ANALYZE is not allowed in read-only mode"
    # Normalize non-word chars to spaces so "(DELETE" is caught as "DELETE".
    import re
    sql_words = " " + re.sub(r"[^\w]", " ", sql_upper) + " "
    if first_word == "WITH" and any(kw in sql_words for kw in _FORBIDDEN_CTE_KEYWORDS):
        return "Only read-only WITH queries are allowed"
    return None


def handler(event: dict, context: object) -> dict:
    action = event.get("action", "")

    if action == "init":
        # Schema and indexes managed by yoyo migrations — see src/lambda-functions/migrations/
        # Invoke the MigrationFn Lambda (or run migrate.sh locally) to apply pending migrations.
        return {"status": "ok", "message": "Schema managed by yoyo migrations"}

    if action == "status":
        with _conn.cursor() as cur:
            cur.execute("""
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY tablename
            """)
            tables = [row["tablename"] for row in cur.fetchall()]

            result = []
            for table_name in tables:
                cur.execute(
                    psycopg2.sql.SQL("SELECT COUNT(*) AS cnt FROM {}").format(
                        psycopg2.sql.Identifier(table_name)
                    )
                )
                count = cur.fetchone()["cnt"]
                result.append({"table": table_name, "rows": count})
        return {"status": "ok", "tables": result}

    if action == "query":
        sql = event.get("sql", "").strip()
        if not sql:
            return {"status": "error", "message": "No SQL provided"}
        error = _check_sql_safe(sql)
        if error:
            return {"status": "error", "message": error}
        with _conn.cursor() as cur:
            cur.execute("SET statement_timeout = '10s'")
            cur.execute(sql)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = cur.fetchmany(MAX_QUERY_ROWS)
            total = len(rows)
            # Convert to JSON-safe types (datetime, Decimal, UUID, etc.)
            import json
            serialised = json.loads(
                json.dumps([dict(row) for row in rows], default=str)
            )
        truncated = total == MAX_QUERY_ROWS
        return {
            "status": "ok",
            "columns": columns,
            "rows": serialised,
            "count": total,
            "truncated": truncated,
        }

    return {"status": "error", "message": f"Unknown action: {action}"}
