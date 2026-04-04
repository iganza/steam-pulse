"""Database schema — source-of-truth reference for all DDL.

Schema and indexes are managed by yoyo migrations in src/lambda-functions/migrations/.
For local dev: bash scripts/dev/migrate.sh
For staging: bash scripts/dev/migrate.sh --stage staging (tunnel must be open)

create_all() is retained for the test suite only — do not call it in Lambda handlers.
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
        review_count     INTEGER,                    -- total reviews all languages (positive + negative)
        review_count_english INTEGER,                -- English reviews only (drives eligibility)
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
        -- steam deck
        deck_compatibility   INTEGER,                 -- 0=unknown, 1=unsupported, 2=playable, 3=verified
        deck_test_results    JSONB,                   -- raw resolved_items array from Steam
        -- meta
        crawled_at       TIMESTAMPTZ,
        data_source      TEXT DEFAULT 'steam_direct',
        -- temporal velocity cache (0009)
        review_velocity_lifetime NUMERIC(10,2),
        last_velocity_computed_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tags (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        steam_tag_id INTEGER,             -- Steam's stable tag ID (0013)
        category TEXT NOT NULL DEFAULT 'Other'  -- Tag category (0014)
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
        language VARCHAR(20),
        votes_helpful INTEGER DEFAULT 0,
        votes_funny INTEGER DEFAULT 0,
        written_during_early_access BOOLEAN DEFAULT FALSE,
        received_for_free BOOLEAN DEFAULT FALSE,
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
        -- phase 2: review crawl
        review_count      INTEGER,                          -- populated after meta crawl
        reviews_completed_at      TIMESTAMPTZ, -- NULL=never fully fetched; non-NULL=when last exhausted
        tags_crawled_at           TIMESTAMPTZ, -- when tags were last fetched
        review_crawled_at         TIMESTAMPTZ, -- when reviews were last fetched (any completion path)
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
    """
    CREATE TABLE IF NOT EXISTS waitlist (
        id          SERIAL PRIMARY KEY,
        email       TEXT UNIQUE NOT NULL,
        created_at  TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    -- Retained for migration chain (0011) — no longer actively written to.
    -- Player tags now come from Steam store page directly (see steam_source.py).
    CREATE TABLE IF NOT EXISTS steamspy_data (
        appid             INTEGER PRIMARY KEY REFERENCES games(appid),
        score_rank        TEXT,
        positive          INTEGER,
        negative          INTEGER,
        userscore         INTEGER,
        owners            TEXT,
        average_forever   INTEGER,
        average_2weeks    INTEGER,
        median_forever    INTEGER,
        median_2weeks     INTEGER,
        price             INTEGER,
        initialprice      INTEGER,
        discount          INTEGER,
        ccu               INTEGER,
        languages         TEXT,
        upserted_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
    # --- Legacy ALTER TABLE stubs (historical reference only) ---
    # These columns are now defined inline in the CREATE TABLE statements above
    # and managed by yoyo migrations (0002–0005). Listed here so create_all()
    # remains idempotent when called from the test suite against a fresh DB.
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS review_count_english INTEGER",
    "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS language VARCHAR(20)",
    "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS votes_helpful INTEGER DEFAULT 0",
    "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS votes_funny INTEGER DEFAULT 0",
    "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS written_during_early_access BOOLEAN DEFAULT FALSE",
    "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS received_for_free BOOLEAN DEFAULT FALSE",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS deck_compatibility INTEGER",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS deck_test_results JSONB",
    "ALTER TABLE app_catalog ADD COLUMN IF NOT EXISTS reviews_completed_at TIMESTAMPTZ",
    # 0009_game_velocity_cache
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS review_velocity_lifetime NUMERIC(10,2)",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS last_velocity_computed_at TIMESTAMPTZ",
    # 0013_add_steam_tag_id
    "ALTER TABLE tags ADD COLUMN IF NOT EXISTS steam_tag_id INTEGER",
    # 0014_add_tag_category
    "ALTER TABLE tags ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'Other'",
)

# Analytics engine indexes — kept for test suite use only.
# Production indexes are managed by yoyo migration 0006_add_analytics_indexes.sql
# which uses CREATE INDEX CONCURRENTLY to avoid write-blocking locks.
INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_reviews_author_appid ON reviews(appid, author_steamid) WHERE author_steamid IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_reviews_appid_playtime ON reviews(appid, playtime_hours, voted_up)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_appid_ea ON reviews(appid, written_during_early_access, voted_up)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_appid_helpful ON reviews(appid, votes_helpful DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_appid_funny ON reviews(appid, votes_funny DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_appid_posted ON reviews(appid, posted_at)",
    "CREATE INDEX IF NOT EXISTS idx_games_developer_slug ON games(developer_slug) WHERE developer_slug IS NOT NULL",
)


def create_all(conn: object) -> None:
    """Execute all DDL statements idempotently. For the test suite only.

    Production schema is managed by yoyo migrations in src/lambda-functions/migrations/.
    Do NOT call this from Lambda handlers — schema is applied by MigrationFn post-deploy.
    """
    with conn.cursor() as cur:  # type: ignore[union-attr]
        for ddl in TABLES:
            cur.execute(ddl)
    conn.commit()  # type: ignore[union-attr]


def create_indexes(conn: object) -> None:
    """Create analytics indexes. For the test suite only.

    Production indexes are managed by yoyo migration 0006_add_analytics_indexes.sql
    which uses CREATE INDEX CONCURRENTLY to avoid write-blocking locks.
    """
    prev_autocommit = conn.autocommit  # type: ignore[union-attr]
    conn.autocommit = True  # type: ignore[union-attr]
    try:
        with conn.cursor() as cur:  # type: ignore[union-attr]
            for ddl in INDEXES:
                cur.execute(ddl)
    finally:
        conn.autocommit = prev_autocommit  # type: ignore[union-attr]
