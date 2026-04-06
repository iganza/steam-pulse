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
    # 0016_materialized_views — refresh log table
    """CREATE TABLE IF NOT EXISTS matview_refresh_log (
        id SERIAL PRIMARY KEY,
        refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        duration_ms INTEGER,
        views_refreshed TEXT[]
    )""",
    # 0017_denormalize_scores
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS sentiment_score REAL",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS hidden_gem_score REAL",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS last_analyzed TIMESTAMPTZ",
)

# Indexes — kept for test suite use only.
# Production indexes are managed by yoyo migrations (0006, 0013, 0014, 0015, 0018)
# which use CREATE INDEX CONCURRENTLY to avoid write-blocking locks.
INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_reviews_author_appid ON reviews(appid, author_steamid) WHERE author_steamid IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_reviews_appid_playtime ON reviews(appid, playtime_hours, voted_up)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_appid_ea ON reviews(appid, written_during_early_access, voted_up)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_appid_helpful ON reviews(appid, votes_helpful DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_appid_funny ON reviews(appid, votes_funny DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_appid_posted ON reviews(appid, posted_at)",
    "CREATE INDEX IF NOT EXISTS idx_games_developer_slug ON games(developer_slug) WHERE developer_slug IS NOT NULL",
    # 0015_catalog_query_indexes
    "CREATE INDEX IF NOT EXISTS idx_game_genres_genre_appid ON game_genres(genre_id, appid)",
    "CREATE INDEX IF NOT EXISTS idx_game_tags_tag_appid ON game_tags(tag_id, appid)",
    "CREATE INDEX IF NOT EXISTS idx_genres_slug ON genres(slug)",
    "CREATE INDEX IF NOT EXISTS idx_tags_slug ON tags(slug)",
    "CREATE INDEX IF NOT EXISTS idx_games_review_count ON games(review_count DESC NULLS LAST)",
    # 0018_score_indexes
    "CREATE INDEX IF NOT EXISTS idx_games_sentiment_score ON games(sentiment_score DESC NULLS LAST)",
    "CREATE INDEX IF NOT EXISTS idx_games_hidden_gem_score ON games(hidden_gem_score DESC NULLS LAST)",
    "CREATE INDEX IF NOT EXISTS idx_games_last_analyzed ON games(last_analyzed DESC NULLS LAST)",
)


MATERIALIZED_VIEWS: tuple[str, ...] = (
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_genre_counts AS
    SELECT gn.id, gn.name, gn.slug, COUNT(gg.appid) AS game_count
    FROM genres gn
    LEFT JOIN game_genres gg ON gg.genre_id = gn.id
    GROUP BY gn.id, gn.name, gn.slug""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_genre_counts_id ON mv_genre_counts(id)",
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_tag_counts AS
    SELECT t.id, t.name, t.slug, t.category, COUNT(gt.appid) AS game_count
    FROM tags t
    LEFT JOIN game_tags gt ON gt.tag_id = t.id
    GROUP BY t.id, t.name, t.slug, t.category""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_tag_counts_id ON mv_tag_counts(id)",
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_price_positioning AS
    SELECT
        gn.slug AS genre_slug, gn.name AS genre_name,
        CASE
            WHEN g.is_free THEN 'Free'
            WHEN g.price_usd < 5 THEN 'Under $5'
            WHEN g.price_usd < 10 THEN '$5-10'
            WHEN g.price_usd < 15 THEN '$10-15'
            WHEN g.price_usd < 20 THEN '$15-20'
            WHEN g.price_usd < 30 THEN '$20-30'
            WHEN g.price_usd < 50 THEN '$30-50'
            ELSE '$50+'
        END AS price_range,
        COUNT(*) AS game_count,
        ROUND(AVG(g.positive_pct), 1) AS avg_sentiment,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY COALESCE(g.price_usd, 0))::numeric, 2)
            AS median_price
    FROM games g
    JOIN game_genres gg ON gg.appid = g.appid
    JOIN genres gn ON gg.genre_id = gn.id
    WHERE g.review_count >= 10 AND (g.price_usd IS NOT NULL OR g.is_free)
    GROUP BY gn.slug, gn.name, 3""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_price_positioning_pk ON mv_price_positioning(genre_slug, price_range)",
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_release_timing AS
    SELECT
        gn.slug AS genre_slug, gn.name AS genre_name,
        EXTRACT(MONTH FROM g.release_date)::int AS month,
        COUNT(*) AS releases,
        ROUND(AVG(g.positive_pct), 1) AS avg_sentiment,
        ROUND(AVG(g.review_count), 0) AS avg_reviews
    FROM games g
    JOIN game_genres gg ON gg.appid = g.appid
    JOIN genres gn ON gg.genre_id = gn.id
    WHERE g.release_date IS NOT NULL
      AND g.release_date >= NOW() - INTERVAL '5 years'
      AND g.review_count >= 10
    GROUP BY gn.slug, gn.name, 3""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_release_timing_pk ON mv_release_timing(genre_slug, month)",
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_platform_distribution AS
    SELECT
        gn.slug AS genre_slug, gn.name AS genre_name,
        COUNT(*) AS total,
        COUNT(*) FILTER (WHERE (g.platforms->>'windows')::boolean) AS windows,
        COUNT(*) FILTER (WHERE (g.platforms->>'mac')::boolean) AS mac,
        COUNT(*) FILTER (WHERE (g.platforms->>'linux')::boolean) AS linux,
        ROUND(AVG(g.positive_pct) FILTER (WHERE (g.platforms->>'windows')::boolean), 1) AS windows_avg_sentiment,
        ROUND(AVG(g.positive_pct) FILTER (WHERE (g.platforms->>'mac')::boolean), 1) AS mac_avg_sentiment,
        ROUND(AVG(g.positive_pct) FILTER (WHERE (g.platforms->>'linux')::boolean), 1) AS linux_avg_sentiment
    FROM games g
    JOIN game_genres gg ON gg.appid = g.appid
    JOIN genres gn ON gg.genre_id = gn.id
    WHERE g.platforms IS NOT NULL AND g.review_count >= 10
    GROUP BY gn.slug, gn.name""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_platform_distribution_pk ON mv_platform_distribution(genre_slug)",
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_tag_trend AS
    SELECT
        t.slug AS tag_slug, t.name AS tag_name,
        EXTRACT(YEAR FROM g.release_date)::int AS year,
        COUNT(*) AS game_count,
        ROUND(AVG(g.positive_pct), 1) AS avg_sentiment
    FROM games g
    JOIN game_tags gt ON gt.appid = g.appid
    JOIN tags t ON gt.tag_id = t.id
    WHERE g.release_date IS NOT NULL AND EXTRACT(YEAR FROM g.release_date) >= 2015
    GROUP BY t.slug, t.name, 3""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_tag_trend_pk ON mv_tag_trend(tag_slug, year)",
    # 0019/0020: pre-joined genre/tag game matviews (with last_analyzed)
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_genre_games AS
    SELECT
        gn.slug AS genre_slug,
        g.appid, g.name, g.slug, g.developer, g.header_image,
        g.review_count, g.review_count_english, g.positive_pct, g.price_usd, g.is_free,
        g.release_date, g.deck_compatibility,
        g.hidden_gem_score, g.sentiment_score, g.last_analyzed,
        EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS is_early_access
    FROM games g
    JOIN game_genres gg2 ON gg2.appid = g.appid
    JOIN genres gn ON gg2.genre_id = gn.id""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_genre_games_pk ON mv_genre_games(genre_slug, appid)",
    "CREATE INDEX IF NOT EXISTS idx_mv_genre_games_review ON mv_genre_games(genre_slug, review_count DESC NULLS LAST)",
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_tag_games AS
    SELECT
        t.slug AS tag_slug,
        g.appid, g.name, g.slug, g.developer, g.header_image,
        g.review_count, g.review_count_english, g.positive_pct, g.price_usd, g.is_free,
        g.release_date, g.deck_compatibility,
        g.hidden_gem_score, g.sentiment_score, g.last_analyzed,
        EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS is_early_access
    FROM games g
    JOIN game_tags gt ON gt.appid = g.appid
    JOIN tags t ON gt.tag_id = t.id""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_tag_games_pk ON mv_tag_games(tag_slug, appid)",
    "CREATE INDEX IF NOT EXISTS idx_mv_tag_games_review ON mv_tag_games(tag_slug, review_count DESC NULLS LAST)",
    # 0020: price summary
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_price_summary AS
    SELECT
        gn.slug AS genre_slug,
        ROUND(AVG(g.price_usd) FILTER (WHERE NOT g.is_free), 2) AS avg_price,
        ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY g.price_usd)
               FILTER (WHERE NOT g.is_free))::numeric, 2) AS median_price,
        COUNT(*) FILTER (WHERE g.is_free) AS free_count,
        COUNT(*) FILTER (WHERE NOT g.is_free) AS paid_count
    FROM games g
    JOIN game_genres gg ON gg.appid = g.appid
    JOIN genres gn ON gg.genre_id = gn.id
    WHERE g.review_count >= 10
    GROUP BY gn.slug""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_price_summary_pk ON mv_price_summary(genre_slug)",
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


def create_matviews(conn: object) -> None:
    """Create materialized views and their unique indexes. For the test suite only.

    Production matviews are managed by yoyo migrations (0016, 0019, 0020).
    Drop mv_genre_games/mv_tag_games first so IF NOT EXISTS picks up the
    current definition (with last_analyzed) on persistent test databases.
    """
    with conn.cursor() as cur:  # type: ignore[union-attr]
        cur.execute("DROP MATERIALIZED VIEW IF EXISTS mv_genre_games")
        cur.execute("DROP MATERIALIZED VIEW IF EXISTS mv_tag_games")
        for ddl in MATERIALIZED_VIEWS:
            cur.execute(ddl)
    conn.commit()  # type: ignore[union-attr]
