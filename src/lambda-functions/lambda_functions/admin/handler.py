"""Admin Lambda — lightweight DB operations invoked by sp.py.

Actions:
  {"action": "init"}     — run create_all() to create/migrate tables
  {"action": "status"}   — return table names and row counts
  {"action": "query", "sql": "SELECT ..."}  — run a read-only SQL query

This Lambda is in the VPC with DB access. No public exposure.
"""

import json
import logging

from library_layer.schema import create_all
from library_layer.utils.db import get_conn

logger = logging.getLogger("admin")
logger.setLevel(logging.INFO)

_conn = get_conn()


def handler(event: dict, context: object) -> dict:
    action = event.get("action", "")

    if action == "init":
        create_all(_conn)
        return {"status": "ok", "message": "Schema initialised"}

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
                cur.execute(f"SELECT COUNT(*) AS cnt FROM {table_name}")  # noqa: S608
                count = cur.fetchone()["cnt"]
                result.append({"table": table_name, "rows": count})
        return {"status": "ok", "tables": result}

    if action == "query":
        sql = event.get("sql", "").strip()
        if not sql:
            return {"status": "error", "message": "No SQL provided"}
        # Safety: only allow read-only statements
        first_word = sql.split()[0].upper() if sql else ""
        if first_word not in ("SELECT", "EXPLAIN", "SHOW", "WITH"):
            return {"status": "error", "message": f"Only read-only queries allowed, got: {first_word}"}
        with _conn.cursor() as cur:
            cur.execute(sql)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = cur.fetchall()
            # RealDictCursor returns dicts, serialise cleanly
            serialised = [dict(row) for row in rows]
        return {"status": "ok", "columns": columns, "rows": serialised, "count": len(rows)}

    return {"status": "error", "message": f"Unknown action: {action}"}
