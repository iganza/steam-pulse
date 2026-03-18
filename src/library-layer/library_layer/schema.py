"""Database schema — all CREATE TABLE DDL in dependency order.

Extracted from storage.py. Call create_all(conn) once per cold start (or test
session) to ensure all tables exist. Statements are idempotent (IF NOT EXISTS).
"""

TABLES: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS games (
        appid            INTEGER PRIMARY KEY,
        name             TEXT NOT NULL,
        slug             TEXT UNIQUE NOT NULL,
        -- identity
        type             TEXT DEFAULT 'game',        -- game | dlc | demo | music | tool
        developer        TEXT,                        -- primary developer (display)
        developer_slug   TEXT,                        -- slugified developer for URL routing
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
    CREATE TABLE IF NOT EXISTS app_catalog (
        appid             INTEGER PRIMARY KEY,
        name              TEXT NOT NULL,
        -- phase 1: metadata crawl
        meta_status       TEXT NOT NULL DEFAULT 'pending',  -- pending | done | failed | skipped
        meta_crawled_at   TIMESTAMPTZ,
        -- phase 2: review crawl (only for games with 500+ reviews)
        review_count      INTEGER,                          -- populated after meta crawl
        review_status     TEXT NOT NULL DEFAULT 'pending',  -- pending | done | failed | skipped | ineligible
        review_crawled_at TIMESTAMPTZ,
        -- housekeeping
        discovered_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
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


def create_all(conn: object) -> None:
    """Execute all DDL statements idempotently.

    Safe to call on every cold start — all statements use IF NOT EXISTS.
    """
    with conn.cursor() as cur:  # type: ignore[union-attr]
        for ddl in TABLES:
            cur.execute(ddl)
    conn.commit()  # type: ignore[union-attr]
