"""Storage backends — InMemory (local dev) and PostgreSQL (production)."""

import logging
import os
import re
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

TTL_SECONDS = 86400  # 24 hours


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class BaseStorage(ABC):
    # ------------------------------------------------------------------
    # Legacy sync methods — used by CLI (main.py) path
    # ------------------------------------------------------------------

    @abstractmethod
    def get_analysis(self, appid: int) -> dict | None: ...

    @abstractmethod
    def store_analysis(self, appid: int, result: dict) -> None: ...

    # ------------------------------------------------------------------
    # New async methods — used by api.py
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_report(self, appid: int) -> dict | None: ...

    @abstractmethod
    async def upsert_report(self, appid: int, report: dict) -> None: ...

    @abstractmethod
    async def get_game(self, appid: int) -> dict | None: ...

    @abstractmethod
    async def upsert_game(self, appid: int, data: dict) -> None: ...

    @abstractmethod
    async def get_analysis_job(self, job_id: str) -> dict | None: ...

    @abstractmethod
    async def set_analysis_job(self, job_id: str, status: str, appid: int) -> None: ...

    # ------------------------------------------------------------------
    # Concrete helpers — overridden by PostgresStorage where applicable
    # ------------------------------------------------------------------

    def query_catalog(self, sql: str, params: tuple = ()) -> list:
        return []

    def backend_name(self) -> str:
        return "unknown"


class InMemoryStorage(BaseStorage):
    """Simple in-memory store. Resets on restart — acceptable for local dev."""

    def __init__(self) -> None:
        # Legacy CLI store (TTL-aware)
        self._store: dict[int, dict] = {}
        self._timestamps: dict[int, float] = {}
        # API stores
        self._reports: dict[int, dict] = {}
        self._games: dict[int, dict] = {}
        self._jobs: dict[str, dict] = {}

    # Legacy sync

    def get_analysis(self, appid: int) -> dict | None:
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

    # New async

    async def get_report(self, appid: int) -> dict | None:
        return self._reports.get(appid)

    async def upsert_report(self, appid: int, report: dict) -> None:
        self._reports[appid] = report

    async def get_game(self, appid: int) -> dict | None:
        return self._games.get(appid)

    async def upsert_game(self, appid: int, data: dict) -> None:
        self._games[appid] = data

    async def get_analysis_job(self, job_id: str) -> dict | None:
        return self._jobs.get(job_id)

    async def set_analysis_job(self, job_id: str, status: str, appid: int) -> None:
        self._jobs[job_id] = {"job_id": job_id, "status": status, "appid": appid}

    def backend_name(self) -> str:
        return "memory"


class PostgresStorage(BaseStorage):
    """Full PostgreSQL backend using psycopg2."""

    # Tables are created in dependency order.
    _DDL: tuple[str, ...] = (
        """
        CREATE TABLE IF NOT EXISTS games (
            appid            INTEGER PRIMARY KEY,
            name             TEXT NOT NULL,
            slug             TEXT UNIQUE NOT NULL,
            -- identity
            type             TEXT DEFAULT 'game',        -- game | dlc | demo | music | tool
            developer        TEXT,                        -- primary developer (display)
            publisher        TEXT,                        -- primary publisher (display)
            developers       JSONB,                       -- full array from Steam API
            publishers       JSONB,                       -- full array from Steam API
            website          TEXT,
            -- dates / status
            release_date     DATE,
            coming_soon      BOOLEAN DEFAULT FALSE,
            -- pricing
            price_usd        NUMERIC(8,2),
            is_free          BOOLEAN DEFAULT FALSE,
            -- descriptions
            short_desc       TEXT,
            detailed_description TEXT,                   -- main long HTML description
            about_the_game   TEXT,                       -- "About the Game" section
            -- review metrics
            review_count     INTEGER,                    -- total reviews (positive + negative)
            total_positive   INTEGER,
            total_negative   INTEGER,
            positive_pct     INTEGER,
            review_score_desc TEXT,                      -- "Very Positive", "Mixed", etc.
            steamspy_owners  TEXT,                       -- SteamSpy owner estimate range
            -- media
            header_image     TEXT,
            background_image TEXT,
            -- platform / audience
            required_age     INTEGER DEFAULT 0,
            platforms        JSONB,                      -- {windows: bool, mac: bool, linux: bool}
            supported_languages TEXT,
            -- engagement
            achievements_total INTEGER,
            metacritic_score INTEGER,
            -- meta
            crawled_at       TIMESTAMPTZ,
            data_source      TEXT DEFAULT 'steam_direct'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tags (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            slug TEXT UNIQUE NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS game_tags (
            appid INTEGER REFERENCES games(appid),
            tag_id INTEGER REFERENCES tags(id),
            votes INTEGER DEFAULT 0,
            PRIMARY KEY (appid, tag_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS genres (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            slug TEXT UNIQUE NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS game_genres (
            appid INTEGER REFERENCES games(appid),
            genre_id INTEGER REFERENCES genres(id),
            PRIMARY KEY (appid, genre_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS game_categories (
            appid         INTEGER REFERENCES games(appid),
            category_id   INTEGER NOT NULL,
            category_name TEXT NOT NULL,
            PRIMARY KEY (appid, category_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reviews (
            id BIGSERIAL PRIMARY KEY,
            appid INTEGER REFERENCES games(appid),
            steam_review_id TEXT UNIQUE,
            author_steamid TEXT,
            voted_up BOOLEAN,
            playtime_hours INTEGER,
            body TEXT,
            posted_at TIMESTAMPTZ,
            crawled_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reports (
            appid INTEGER PRIMARY KEY REFERENCES games(appid),
            report_json JSONB NOT NULL,
            reviews_analyzed INTEGER,
            analysis_version TEXT DEFAULT '1.0',
            is_public BOOLEAN DEFAULT TRUE,
            seo_title TEXT,
            seo_description TEXT,
            featured_at TIMESTAMPTZ,
            last_analyzed TIMESTAMPTZ DEFAULT NOW(),
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS game_relations (
            appid_a INTEGER REFERENCES games(appid),
            appid_b INTEGER REFERENCES games(appid),
            relation TEXT DEFAULT 'competitive_mention',
            PRIMARY KEY (appid_a, appid_b)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS index_insights (
            id SERIAL PRIMARY KEY,
            type TEXT NOT NULL,
            slug TEXT NOT NULL,
            insight_json JSONB,
            computed_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(type, slug)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS rate_limits (
            ip_hash TEXT PRIMARY KEY,
            count INTEGER DEFAULT 1,
            window_start TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS analysis_jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            appid INTEGER,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        # Legacy table — kept for CLI backward compatibility
        """
        CREATE TABLE IF NOT EXISTS review_summaries (
            appid INTEGER PRIMARY KEY,
            summary JSONB,
            last_analyzed TIMESTAMP
        )
        """,
        # --- Future migrations ---
        # When adding a new column to an existing deployed database, append entries here:
        #   "ALTER TABLE games ADD COLUMN IF NOT EXISTS my_new_col TEXT",
        # These run on every startup and are idempotent (IF NOT EXISTS).
        # No migration framework needed — just append and deploy.
    )

    def __init__(self, database_url: str) -> None:
        import psycopg2
        import psycopg2.extras

        self._dsn = database_url
        self._psycopg2 = psycopg2
        self._extras = psycopg2.extras
        self._ensure_schema()

    def _connect(self):  # type: ignore[return]
        return self._psycopg2.connect(self._dsn)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                for ddl in self._DDL:
                    cur.execute(ddl)
            conn.commit()

    # ------------------------------------------------------------------
    # Legacy sync (CLI / main.py path)
    # ------------------------------------------------------------------

    def get_analysis(self, appid: int) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT summary FROM review_summaries WHERE appid = %s", (appid,)
                )
                row = cur.fetchone()
                return dict(row["summary"]) if row else None

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

    # ------------------------------------------------------------------
    # New async (api.py path)
    # ------------------------------------------------------------------

    async def get_report(self, appid: int) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT report_json FROM reports WHERE appid = %s", (appid,)
                )
                row = cur.fetchone()
                return dict(row["report_json"]) if row else None

    async def upsert_report(self, appid: int, report: dict) -> None:
        import json

        name = report.get("game_name", f"app-{appid}")
        slug = _slugify(name) or f"app-{appid}"
        reviews_analyzed = report.get("total_reviews_analyzed")

        with self._connect() as conn:
            with conn.cursor() as cur:
                # Ensure game row exists (minimal upsert)
                cur.execute(
                    """
                    INSERT INTO games (appid, name, slug)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (appid) DO UPDATE SET name = EXCLUDED.name
                    """,
                    (appid, name, slug),
                )
                cur.execute(
                    """
                    INSERT INTO reports (appid, report_json, reviews_analyzed, last_analyzed)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (appid) DO UPDATE
                        SET report_json = EXCLUDED.report_json,
                            reviews_analyzed = EXCLUDED.reviews_analyzed,
                            last_analyzed = NOW()
                    """,
                    (appid, json.dumps(report), reviews_analyzed),
                )
            conn.commit()

    async def get_game(self, appid: int) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM games WHERE appid = %s", (appid,))
                row = cur.fetchone()
                return dict(row) if row else None

    async def upsert_game(self, appid: int, data: dict) -> None:
        import json

        name = data.get("name", f"app-{appid}")
        slug = _slugify(name) or f"app-{appid}"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO games (
                        appid, name, slug, type,
                        developer, publisher, developers, publishers, website,
                        release_date, coming_soon,
                        price_usd, is_free,
                        short_desc, detailed_description, about_the_game,
                        review_count, total_positive, total_negative,
                        positive_pct, review_score_desc, steamspy_owners,
                        header_image, background_image,
                        required_age, platforms, supported_languages,
                        achievements_total, metacritic_score,
                        crawled_at, data_source
                    ) VALUES (
                        %(appid)s, %(name)s, %(slug)s, %(type)s,
                        %(developer)s, %(publisher)s, %(developers)s, %(publishers)s, %(website)s,
                        %(release_date)s, %(coming_soon)s,
                        %(price_usd)s, %(is_free)s,
                        %(short_desc)s, %(detailed_description)s, %(about_the_game)s,
                        %(review_count)s, %(total_positive)s, %(total_negative)s,
                        %(positive_pct)s, %(review_score_desc)s, %(steamspy_owners)s,
                        %(header_image)s, %(background_image)s,
                        %(required_age)s, %(platforms)s, %(supported_languages)s,
                        %(achievements_total)s, %(metacritic_score)s,
                        NOW(), %(data_source)s
                    )
                    ON CONFLICT (appid) DO UPDATE SET
                        name                 = EXCLUDED.name,
                        slug                 = EXCLUDED.slug,
                        type                 = EXCLUDED.type,
                        developer            = EXCLUDED.developer,
                        publisher            = EXCLUDED.publisher,
                        developers           = EXCLUDED.developers,
                        publishers           = EXCLUDED.publishers,
                        website              = EXCLUDED.website,
                        release_date         = EXCLUDED.release_date,
                        coming_soon          = EXCLUDED.coming_soon,
                        price_usd            = EXCLUDED.price_usd,
                        is_free              = EXCLUDED.is_free,
                        short_desc           = EXCLUDED.short_desc,
                        detailed_description = EXCLUDED.detailed_description,
                        about_the_game       = EXCLUDED.about_the_game,
                        review_count         = EXCLUDED.review_count,
                        total_positive       = EXCLUDED.total_positive,
                        total_negative       = EXCLUDED.total_negative,
                        positive_pct         = EXCLUDED.positive_pct,
                        review_score_desc    = EXCLUDED.review_score_desc,
                        steamspy_owners      = EXCLUDED.steamspy_owners,
                        header_image         = EXCLUDED.header_image,
                        background_image     = EXCLUDED.background_image,
                        required_age         = EXCLUDED.required_age,
                        platforms            = EXCLUDED.platforms,
                        supported_languages  = EXCLUDED.supported_languages,
                        achievements_total   = EXCLUDED.achievements_total,
                        metacritic_score     = EXCLUDED.metacritic_score,
                        crawled_at           = NOW(),
                        data_source          = EXCLUDED.data_source
                    """,
                    {
                        "appid": appid,
                        "name": name,
                        "slug": slug,
                        "type": data.get("type", "game"),
                        "developer": data.get("developer"),
                        "publisher": data.get("publisher"),
                        "developers": json.dumps(data["developers"]) if data.get("developers") else None,
                        "publishers": json.dumps(data["publishers"]) if data.get("publishers") else None,
                        "website": data.get("website"),
                        "release_date": data.get("release_date"),
                        "coming_soon": data.get("coming_soon", False),
                        "price_usd": data.get("price_usd"),
                        "is_free": data.get("is_free", False),
                        "short_desc": data.get("short_desc"),
                        "detailed_description": data.get("detailed_description"),
                        "about_the_game": data.get("about_the_game"),
                        "review_count": data.get("review_count"),
                        "total_positive": data.get("total_positive"),
                        "total_negative": data.get("total_negative"),
                        "positive_pct": data.get("positive_pct"),
                        "review_score_desc": data.get("review_score_desc"),
                        "steamspy_owners": data.get("steamspy_owners"),
                        "header_image": data.get("header_image"),
                        "background_image": data.get("background_image"),
                        "required_age": data.get("required_age", 0),
                        "platforms": json.dumps(data["platforms"]) if data.get("platforms") else None,
                        "supported_languages": data.get("supported_languages"),
                        "achievements_total": data.get("achievements_total"),
                        "metacritic_score": data.get("metacritic_score"),
                        "data_source": data.get("data_source", "steam_direct"),
                    },
                )
            conn.commit()

    async def get_analysis_job(self, job_id: str) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT job_id, status, appid FROM analysis_jobs WHERE job_id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    async def set_analysis_job(self, job_id: str, status: str, appid: int) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO analysis_jobs (job_id, status, appid, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (job_id) DO UPDATE
                        SET status = EXCLUDED.status,
                            updated_at = NOW()
                    """,
                    (job_id, status, appid),
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
        except Exception as exc:
            logger.warning("PostgreSQL unavailable (%s) — falling back to memory", exc)
    return InMemoryStorage()


storage = get_storage()
