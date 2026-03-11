"""Storage backends — InMemory (V1) and PostgreSQL (V2)."""

import os
import time
from abc import ABC, abstractmethod
from typing import Optional

TTL_SECONDS = 86400  # 24 hours


class BaseStorage(ABC):
    @abstractmethod
    def get_analysis(self, appid: int) -> Optional[dict]:
        ...

    @abstractmethod
    def store_analysis(self, appid: int, result: dict) -> None:
        ...

    # V2 methods — no-op in V1
    def get_game(self, appid: int) -> Optional[dict]:
        return None

    def store_game(self, appid: int, data: dict) -> None:
        pass

    def query_catalog(self, sql: str, params: tuple = ()) -> list:
        return []

    def backend_name(self) -> str:
        return "unknown"


class InMemoryStorage(BaseStorage):
    """Simple dict cache with 24-hour TTL. Resets on restart — acceptable for V1."""

    def __init__(self):
        self._store: dict[int, dict] = {}
        self._timestamps: dict[int, float] = {}

    def get_analysis(self, appid: int) -> Optional[dict]:
        if appid not in self._store:
            return None
        age = time.time() - self._timestamps.get(appid, 0)
        if age > TTL_SECONDS:
            del self._store[appid]
            del self._timestamps[appid]
            return None
        return self._store[appid]

    def store_analysis(self, appid: int, result: dict) -> None:
        self._store[appid] = result
        self._timestamps[appid] = time.time()

    def backend_name(self) -> str:
        return "memory"


class PostgresStorage(BaseStorage):
    """Full PostgreSQL backend using psycopg2."""

    CREATE_GAMES = """
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
    """

    CREATE_GAME_TAGS = """
    CREATE TABLE IF NOT EXISTS game_tags (
        appid INTEGER,
        tag TEXT,
        PRIMARY KEY (appid, tag)
    );
    """

    CREATE_GAME_GENRES = """
    CREATE TABLE IF NOT EXISTS game_genres (
        appid INTEGER,
        genre TEXT,
        PRIMARY KEY (appid, genre)
    );
    """

    CREATE_GAME_CATEGORIES = """
    CREATE TABLE IF NOT EXISTS game_categories (
        appid INTEGER,
        category TEXT,
        PRIMARY KEY (appid, category)
    );
    """

    CREATE_REVIEW_SUMMARIES = """
    CREATE TABLE IF NOT EXISTS review_summaries (
        appid INTEGER PRIMARY KEY,
        summary JSONB,
        last_analyzed TIMESTAMP
    );
    """

    def __init__(self, database_url: str):
        import psycopg2
        import psycopg2.extras

        self._dsn = database_url
        self._psycopg2 = psycopg2
        self._extras = psycopg2.extras
        self._ensure_schema()

    def _connect(self):
        return self._psycopg2.connect(self._dsn)

    def _ensure_schema(self):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(self.CREATE_GAMES)
                cur.execute(self.CREATE_GAME_TAGS)
                cur.execute(self.CREATE_GAME_GENRES)
                cur.execute(self.CREATE_GAME_CATEGORIES)
                cur.execute(self.CREATE_REVIEW_SUMMARIES)
            conn.commit()

    def get_analysis(self, appid: int) -> Optional[dict]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT summary FROM review_summaries WHERE appid = %s",
                    (appid,),
                )
                row = cur.fetchone()
                if row:
                    return dict(row["summary"])
                return None

    def store_analysis(self, appid: int, result: dict) -> None:
        import json
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO review_summaries (appid, summary, last_analyzed)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (appid) DO UPDATE
                        SET summary = EXCLUDED.summary,
                            last_analyzed = EXCLUDED.last_analyzed
                    """,
                    (appid, json.dumps(result)),
                )
            conn.commit()

    def get_game(self, appid: int) -> Optional[dict]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM games WHERE appid = %s", (appid,))
                row = cur.fetchone()
                return dict(row) if row else None

    def store_game(self, appid: int, data: dict) -> None:
        import json
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO games (
                        appid, name, type, release_date, price_usd, is_free,
                        metacritic_score, total_positive, total_negative,
                        review_score_desc, short_description, developers,
                        publishers, platforms, last_crawled
                    ) VALUES (
                        %(appid)s, %(name)s, %(type)s, %(release_date)s,
                        %(price_usd)s, %(is_free)s, %(metacritic_score)s,
                        %(total_positive)s, %(total_negative)s,
                        %(review_score_desc)s, %(short_description)s,
                        %(developers)s, %(publishers)s, %(platforms)s, NOW()
                    )
                    ON CONFLICT (appid) DO UPDATE SET
                        name = EXCLUDED.name,
                        type = EXCLUDED.type,
                        release_date = EXCLUDED.release_date,
                        price_usd = EXCLUDED.price_usd,
                        is_free = EXCLUDED.is_free,
                        metacritic_score = EXCLUDED.metacritic_score,
                        total_positive = EXCLUDED.total_positive,
                        total_negative = EXCLUDED.total_negative,
                        review_score_desc = EXCLUDED.review_score_desc,
                        short_description = EXCLUDED.short_description,
                        developers = EXCLUDED.developers,
                        publishers = EXCLUDED.publishers,
                        platforms = EXCLUDED.platforms,
                        last_crawled = NOW()
                    """,
                    {
                        **data,
                        "platforms": json.dumps(data.get("platforms", {})),
                        "developers": data.get("developers", []),
                        "publishers": data.get("publishers", []),
                    },
                )
            conn.commit()

    def query_catalog(self, sql: str, params: tuple = ()) -> list:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]

    def backend_name(self) -> str:
        return "postgres"


def get_storage() -> BaseStorage:
    """Auto-select backend based on DATABASE_URL env var."""
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        try:
            return PostgresStorage(db_url)
        except Exception as e:
            print(f"[storage] PostgreSQL unavailable ({e}), falling back to memory")
    return InMemoryStorage()


storage = get_storage()
