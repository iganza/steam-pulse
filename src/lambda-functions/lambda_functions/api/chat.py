"""V2 Pro chat — natural language → SQL → natural language answer."""

import json
import os
import re
from typing import Any as BaseStorage  # duck-typed: must have query_catalog(sql, params)

import anthropic

SONNET_MODEL_DEFAULT = "claude-3-5-sonnet-20241022"


def _sonnet_model() -> str:
    return os.getenv("SONNET_MODEL", SONNET_MODEL_DEFAULT)

DB_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS games (
    appid INTEGER PRIMARY KEY,
    name TEXT,
    type TEXT,
    release_date DATE,
    price_usd NUMERIC,
    is_free BOOLEAN,
    metacritic_score INTEGER,
    total_positive INTEGER,
    total_negative INTEGER,
    review_score_desc TEXT,
    short_description TEXT,
    developers TEXT[],
    publishers TEXT[],
    platforms JSONB,
    last_crawled TIMESTAMP
);

CREATE TABLE IF NOT EXISTS game_tags (
    appid INTEGER,
    tag TEXT,
    PRIMARY KEY (appid, tag)
);

CREATE TABLE IF NOT EXISTS game_genres (
    appid INTEGER,
    genre TEXT,
    PRIMARY KEY (appid, genre)
);

CREATE TABLE IF NOT EXISTS game_categories (
    appid INTEGER,
    category TEXT,
    PRIMARY KEY (appid, category)
);

CREATE TABLE IF NOT EXISTS review_summaries (
    appid INTEGER PRIMARY KEY,
    summary JSONB,
    last_analyzed TIMESTAMP
);
"""

SQL_SYSTEM_PROMPT = (
    "You are a Steam game market analyst. You have access to a PostgreSQL database of Steam games.\n"
    "Generate a single valid SQL SELECT query to answer the user's question.\n"
    f"Schema:\n{DB_SCHEMA_DDL}\n"
    "Rules: SELECT only, no INSERT/UPDATE/DELETE, LIMIT 100 max, return only the SQL with no explanation."
)

ANSWER_SYSTEM_PROMPT = (
    "You are a Steam game market analyst. Given a SQL query result, provide a concise, "
    "insightful natural language answer. Be specific with numbers. If the result is empty, "
    "say so clearly."
)


def _get_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key)


def _extract_sql(text: str) -> str:
    """Extract SQL from a response that may contain markdown code fences."""
    # Try code fence first
    match = re.search(r"```(?:sql)?\s*(SELECT[\s\S]+?)```", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # Fallback: find SELECT statement
    match = re.search(r"(SELECT[\s\S]+?);?\s*$", text, re.IGNORECASE)
    if match:
        return match.group(1).strip().rstrip(";")
    return text.strip()


def _is_safe_sql(sql: str) -> bool:
    """Reject any non-SELECT statement."""
    upper = sql.strip().upper()
    return upper.startswith("SELECT") and not any(
        kw in upper for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE")
    )


async def answer_query(message: str, storage: BaseStorage) -> dict:
    """
    1. Send message + DB schema to Sonnet with instruction to generate SQL.
    2. Parse SQL from response.
    3. Execute via storage.query_catalog(sql).
    4. Send results back to Sonnet for natural language formatting.
    5. Return { answer, sql, rows }.
    """
    import asyncio

    client = _get_client()
    loop = asyncio.get_event_loop()

    # Step 1 — generate SQL
    def _gen_sql() -> str:
        resp = client.messages.create(
            model=_sonnet_model(),
            messages=[{"role": "user", "content": message}],
        )
        return resp.content[0].text.strip()

    raw_sql_response = await loop.run_in_executor(None, _gen_sql)
    sql = _extract_sql(raw_sql_response)

    if not _is_safe_sql(sql):
        return {
            "answer": "I can only answer questions using SELECT queries.",
            "sql": sql,
            "rows": [],
        }

    # Enforce LIMIT
    if "LIMIT" not in sql.upper():
        sql = sql.rstrip(";") + " LIMIT 100"

    # Step 2 — execute SQL
    try:
        rows = storage.query_catalog(sql)
    except Exception as e:
        return {
            "answer": f"Query execution failed: {e}",
            "sql": sql,
            "rows": [],
        }

    # Step 3 — format answer
    rows_text = json.dumps(rows[:20], indent=2, default=str)

    def _gen_answer() -> str:
        resp = client.messages.create(
            model=_sonnet_model(),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"User question: {message}\n\n"
                        f"SQL executed: {sql}\n\n"
                        f"Result ({len(rows)} rows total, showing up to 20):\n{rows_text}\n\n"
                        "Provide a concise answer."
                    ),
                }
            ],
        )
        return resp.content[0].text.strip()

    answer = await loop.run_in_executor(None, _gen_answer)

    return {"answer": answer, "sql": sql, "rows": rows}
