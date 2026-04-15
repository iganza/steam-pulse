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
        publisher_slug   TEXT,                        -- slugified publisher for URL routing
        developers       JSONB,                       -- full array from Steam API
        publishers       JSONB,                       -- full array from Steam API
        website          TEXT,
        -- dates / status
        release_date     DATE,
        release_date_raw TEXT,                       -- raw string from Steam ("Q3 2025", "Coming Soon", etc.)
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
        -- content / input
        content_descriptor_ids  JSONB,               -- content warning IDs from Steam
        content_descriptor_notes TEXT,                -- content warning notes
        controller_support TEXT,                      -- "full" | "partial" | NULL
        -- DLC / franchise
        dlc_appids       JSONB,                       -- array of DLC appids
        parent_appid     INTEGER,                     -- parent game if this is DLC/demo
        -- media
        capsule_image    TEXT,                         -- high-res 467x181 capsule art URL
        -- engagement
        recommendations_total INTEGER,                -- curator recommendation count
        -- support
        support_url      TEXT,
        support_email    TEXT,
        legal_notice     TEXT,
        -- system requirements (HTML)
        requirements_windows TEXT,
        requirements_mac TEXT,
        requirements_linux TEXT,
        -- meta
        crawled_at       TIMESTAMPTZ,
        data_source      TEXT DEFAULT 'steam_direct',
        -- temporal velocity cache (0009)
        review_velocity_lifetime NUMERIC(10,2),
        last_velocity_computed_at TIMESTAMPTZ,
        -- revenue estimates (0026) — Boxleiter ratio; gross, pre-Steam-cut, ±50%
        estimated_owners BIGINT,
        estimated_revenue_usd NUMERIC(14,2),
        revenue_estimate_method TEXT,
        revenue_estimate_computed_at TIMESTAMPTZ,
        -- (0030) reason code when no numeric estimate is available
        -- (e.g. free_to_play, insufficient_reviews, excluded_type, missing_price)
        revenue_estimate_reason TEXT
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
        created_at TIMESTAMPTZ DEFAULT NOW(),
        -- three-phase pipeline (0036_merged_summaries)
        pipeline_version TEXT NOT NULL,
        chunk_count INTEGER,
        merged_summary_id BIGINT
    )
    """,
    # Three-phase LLM analysis pipeline artifacts (0035, 0036)
    """
    CREATE TABLE IF NOT EXISTS chunk_summaries (
        id              BIGSERIAL PRIMARY KEY,
        appid           INTEGER NOT NULL REFERENCES games(appid),
        chunk_index     SMALLINT NOT NULL,
        chunk_hash      TEXT NOT NULL,
        review_count    SMALLINT NOT NULL,
        summary_json    JSONB NOT NULL,
        model_id        TEXT NOT NULL,
        prompt_version  TEXT NOT NULL,
        input_tokens    INTEGER,
        output_tokens   INTEGER,
        latency_ms      INTEGER,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (appid, chunk_hash, prompt_version)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chunk_summaries_appid ON chunk_summaries(appid)",
    """
    CREATE TABLE IF NOT EXISTS merged_summaries (
        id               BIGSERIAL PRIMARY KEY,
        appid            INTEGER NOT NULL REFERENCES games(appid),
        merge_level      SMALLINT NOT NULL DEFAULT 1,
        summary_json     JSONB NOT NULL,
        source_chunk_ids BIGINT[] NOT NULL,
        chunks_merged    INTEGER NOT NULL,
        model_id         TEXT NOT NULL,
        prompt_version   TEXT NOT NULL,
        input_tokens     INTEGER,
        output_tokens    INTEGER,
        latency_ms       INTEGER,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_merged_summaries_appid ON merged_summaries(appid)",
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
        discovered_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        -- GetAppList metadata (0041)
        steam_last_modified TIMESTAMPTZ,             -- last_modified from IStoreService/GetAppList
        price_change_number INTEGER                  -- price version counter from GetAppList
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
    # 0038_analysis_requests — user-submitted requests for game analysis
    """
    CREATE TABLE IF NOT EXISTS analysis_requests (
        id         BIGSERIAL PRIMARY KEY,
        appid      INTEGER NOT NULL,
        email      TEXT NOT NULL,
        user_id    TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (appid, email)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_analysis_requests_appid ON analysis_requests(appid)",
    # 0043_batch_executions — operational tracking for batch LLM API calls
    """
    CREATE TABLE IF NOT EXISTS batch_executions (
        id                  BIGSERIAL PRIMARY KEY,
        execution_id        TEXT NOT NULL,
        appid               INTEGER NOT NULL REFERENCES games(appid),
        phase               TEXT NOT NULL,
        backend             TEXT NOT NULL,
        batch_id            TEXT NOT NULL UNIQUE,
        model_id            TEXT NOT NULL,
        status              TEXT NOT NULL DEFAULT 'submitted',
        submitted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at        TIMESTAMPTZ,
        duration_ms         BIGINT,
        request_count       INTEGER NOT NULL,
        succeeded_count     INTEGER,
        failed_count        INTEGER,
        input_tokens        INTEGER,
        output_tokens       INTEGER,
        cache_read_tokens   INTEGER,
        cache_write_tokens  INTEGER,
        estimated_cost_usd  NUMERIC(8, 4),
        failure_reason      TEXT,
        failed_record_ids   TEXT[],
        pipeline_version    TEXT,
        prompt_version      TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_batch_exec_execution_id ON batch_executions(execution_id)",
    "CREATE INDEX IF NOT EXISTS idx_batch_exec_appid ON batch_executions(appid)",
    "CREATE INDEX IF NOT EXISTS idx_batch_exec_status ON batch_executions(status)",
    "CREATE INDEX IF NOT EXISTS idx_batch_exec_submitted ON batch_executions(submitted_at DESC)",
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
    "ALTER TABLE app_catalog ADD COLUMN IF NOT EXISTS review_crawled_at TIMESTAMPTZ",
    "ALTER TABLE app_catalog ADD COLUMN IF NOT EXISTS tags_crawled_at TIMESTAMPTZ",
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
    # NOTE: sentiment_score was dropped in 0021_drop_sentiment_score — Steam's
    # positive_pct is now the only sentiment number. Do not re-add it.
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS hidden_gem_score REAL",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS last_analyzed TIMESTAMPTZ",
    # 0026_add_revenue_estimates — Boxleiter v1 per-game revenue columns.
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS estimated_owners BIGINT",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS estimated_revenue_usd NUMERIC(14,2)",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS revenue_estimate_method TEXT",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS revenue_estimate_computed_at TIMESTAMPTZ",
    # 0030_add_revenue_estimate_reason
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS revenue_estimate_reason TEXT",
    # 0031_add_publisher_slug
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS publisher_slug TEXT",
    # 0036_merged_summaries — three-phase pipeline bookkeeping on reports.
    "ALTER TABLE reports ADD COLUMN IF NOT EXISTS pipeline_version TEXT",
    "ALTER TABLE reports ADD COLUMN IF NOT EXISTS chunk_count INTEGER",
    "ALTER TABLE reports ADD COLUMN IF NOT EXISTS merged_summary_id BIGINT",
    # 0041_capture_steam_fields — GetAppList metadata + appdetails fields.
    "ALTER TABLE app_catalog ADD COLUMN IF NOT EXISTS steam_last_modified TIMESTAMPTZ",
    "ALTER TABLE app_catalog ADD COLUMN IF NOT EXISTS price_change_number INTEGER",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS release_date_raw TEXT",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS content_descriptor_ids JSONB",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS content_descriptor_notes TEXT",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS controller_support TEXT",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS dlc_appids JSONB",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS parent_appid INTEGER",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS capsule_image TEXT",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS recommendations_total INTEGER",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS support_url TEXT",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS support_email TEXT",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS legal_notice TEXT",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS requirements_windows TEXT",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS requirements_mac TEXT",
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS requirements_linux TEXT",
)

# Indexes — kept for test suite use only.
# Production indexes are managed by yoyo migrations (0006, 0013, 0014, 0015,
# 0018, 0032) which use CREATE INDEX CONCURRENTLY to avoid write-blocking locks.
INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_reviews_author_appid ON reviews(appid, author_steamid) WHERE author_steamid IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_reviews_appid_playtime ON reviews(appid, playtime_hours, voted_up)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_appid_ea ON reviews(appid, written_during_early_access, voted_up)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_appid_helpful ON reviews(appid, votes_helpful DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_appid_funny ON reviews(appid, votes_funny DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_appid_posted ON reviews(appid, posted_at)",
    "CREATE INDEX IF NOT EXISTS idx_games_developer_slug ON games(developer_slug) WHERE developer_slug IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_games_publisher_slug ON games(publisher_slug) WHERE publisher_slug IS NOT NULL",
    # 0015_catalog_query_indexes
    "CREATE INDEX IF NOT EXISTS idx_game_genres_genre_appid ON game_genres(genre_id, appid)",
    "CREATE INDEX IF NOT EXISTS idx_game_tags_tag_appid ON game_tags(tag_id, appid)",
    "CREATE INDEX IF NOT EXISTS idx_genres_slug ON genres(slug)",
    "CREATE INDEX IF NOT EXISTS idx_tags_slug ON tags(slug)",
    "CREATE INDEX IF NOT EXISTS idx_games_review_count ON games(review_count DESC NULLS LAST)",
    # 0018_score_indexes
    "CREATE INDEX IF NOT EXISTS idx_games_hidden_gem_score ON games(hidden_gem_score DESC NULLS LAST)",
    "CREATE INDEX IF NOT EXISTS idx_games_last_analyzed ON games(last_analyzed DESC NULLS LAST)",
    # 0027_add_revenue_estimate_index
    "CREATE INDEX IF NOT EXISTS idx_games_estimated_revenue ON games(estimated_revenue_usd DESC NULLS LAST)",
    # 0033_add_stale_meta_index
    "CREATE INDEX IF NOT EXISTS idx_catalog_stale_meta ON app_catalog(meta_crawled_at) WHERE meta_status = 'done'",
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
        ROUND(AVG(g.positive_pct), 1) AS avg_steam_pct,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY COALESCE(g.price_usd, 0))::numeric, 2)
            AS median_price,
        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY g.estimated_revenue_usd)
            FILTER (WHERE g.estimated_revenue_usd IS NOT NULL) AS revenue_q1,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY g.estimated_revenue_usd)
            FILTER (WHERE g.estimated_revenue_usd IS NOT NULL) AS revenue_median,
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY g.estimated_revenue_usd)
            FILTER (WHERE g.estimated_revenue_usd IS NOT NULL) AS revenue_q3,
        COUNT(g.estimated_revenue_usd) AS revenue_sample_size
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
        ROUND(AVG(g.positive_pct), 1) AS avg_steam_pct,
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
        ROUND(AVG(g.positive_pct) FILTER (WHERE (g.platforms->>'windows')::boolean), 1) AS windows_avg_steam_pct,
        ROUND(AVG(g.positive_pct) FILTER (WHERE (g.platforms->>'mac')::boolean), 1) AS mac_avg_steam_pct,
        ROUND(AVG(g.positive_pct) FILTER (WHERE (g.platforms->>'linux')::boolean), 1) AS linux_avg_steam_pct
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
        ROUND(AVG(g.positive_pct), 1) AS avg_steam_pct
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
        g.review_count, g.review_count_english, g.positive_pct, g.review_score_desc,
        g.price_usd, g.is_free,
        g.release_date, g.deck_compatibility,
        g.hidden_gem_score, g.last_analyzed,
        g.estimated_owners, g.estimated_revenue_usd, g.revenue_estimate_method,
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
        g.review_count, g.review_count_english, g.positive_pct, g.review_score_desc,
        g.price_usd, g.is_free,
        g.release_date, g.deck_compatibility,
        g.hidden_gem_score, g.last_analyzed,
        g.estimated_owners, g.estimated_revenue_usd, g.revenue_estimate_method,
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
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_review_counts AS
    SELECT appid, COUNT(*) AS stored_count FROM reviews GROUP BY appid""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_review_counts_appid ON mv_review_counts(appid)",
    # 0024: trend matviews powering the Builder lens / /api/analytics/trend-query.
    # Test schema mirrors migration 0024; columns must stay in sync with the
    # AnalyticsRepository.query_metrics + METRIC_REGISTRY column list.
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_trend_catalog AS
    WITH base AS (
        SELECT g.appid, g.type AS src_type, g.release_date, g.is_free, g.price_usd, g.positive_pct,
               g.metacritic_score, g.review_count, COALESCE(g.review_velocity_lifetime, g.review_count::numeric / GREATEST(CURRENT_DATE - g.release_date, 1)) AS velocity, g.platforms,
               g.deck_compatibility,
               EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS has_ea
        FROM games g
        WHERE g.release_date IS NOT NULL AND g.coming_soon = FALSE
          AND g.type IN ('game', 'dlc') AND g.review_count >= 10
    ),
    grains AS (
        SELECT 'week'::text AS granularity UNION ALL SELECT 'month'
        UNION ALL SELECT 'quarter' UNION ALL SELECT 'year'
    ),
    game_types AS (
        SELECT 'game'::text AS game_type UNION ALL SELECT 'dlc' UNION ALL SELECT 'all'
    )
    SELECT
        gt.game_type,
        gr.granularity,
        DATE_TRUNC(gr.granularity, b.release_date) AS period,
        COUNT(*) AS releases,
        COUNT(*) FILTER (WHERE b.is_free) AS free_count,
        ROUND(AVG(b.review_count)::numeric, 0) AS avg_reviews,
        ROUND(AVG(CASE WHEN b.is_free THEN 0 ELSE b.price_usd END)::numeric, 2) AS avg_price_incl_free,
        COUNT(*) FILTER (WHERE b.positive_pct >= 70) AS positive_count,
        COUNT(*) FILTER (WHERE b.positive_pct >= 40 AND b.positive_pct < 70) AS mixed_count,
        COUNT(*) FILTER (WHERE b.positive_pct < 40) AS negative_count,
        ROUND(AVG(b.positive_pct)::numeric, 1) AS avg_steam_pct,
        ROUND(AVG(b.metacritic_score) FILTER (WHERE b.metacritic_score IS NOT NULL)::numeric, 1) AS avg_metacritic,
        ROUND(AVG(b.price_usd) FILTER (WHERE NOT b.is_free)::numeric, 2) AS avg_paid_price,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.price_usd) FILTER (WHERE NOT b.is_free)::numeric, 2) AS median_price,
        ROUND(COUNT(*) FILTER (WHERE b.is_free)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS free_pct,
        COUNT(*) FILTER (WHERE b.velocity < 1) AS velocity_under_1,
        COUNT(*) FILTER (WHERE b.velocity >= 1 AND b.velocity < 10) AS velocity_1_10,
        COUNT(*) FILTER (WHERE b.velocity >= 10 AND b.velocity < 50) AS velocity_10_50,
        COUNT(*) FILTER (WHERE b.velocity >= 50) AS velocity_50_plus,
        ROUND(COUNT(*) FILTER (WHERE (b.platforms->>'mac')::boolean)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS mac_pct,
        ROUND(COUNT(*) FILTER (WHERE (b.platforms->>'linux')::boolean)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS linux_pct,
        ROUND(COUNT(*) FILTER (WHERE b.deck_compatibility = 3)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS deck_verified_pct,
        ROUND(COUNT(*) FILTER (WHERE b.deck_compatibility = 2)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS deck_playable_pct,
        ROUND(COUNT(*) FILTER (WHERE b.deck_compatibility = 1)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS deck_unsupported_pct,
        COUNT(*) FILTER (WHERE b.has_ea) AS ea_count,
        ROUND(COUNT(*) FILTER (WHERE b.has_ea)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS ea_pct,
        ROUND(AVG(b.positive_pct) FILTER (WHERE b.has_ea)::numeric, 1) AS ea_avg_steam_pct,
        ROUND(AVG(b.positive_pct) FILTER (WHERE NOT b.has_ea)::numeric, 1) AS non_ea_avg_steam_pct
    FROM base b CROSS JOIN grains gr CROSS JOIN game_types gt
    WHERE gt.game_type = 'all' OR b.src_type = gt.game_type
    GROUP BY 1, 2, 3""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_trend_catalog_pk ON mv_trend_catalog(game_type, granularity, period)",
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_trend_by_genre AS
    WITH base AS (
        SELECT g.appid, g.type AS src_type, g.release_date, g.is_free, g.price_usd, g.positive_pct,
               g.metacritic_score, g.review_count, COALESCE(g.review_velocity_lifetime, g.review_count::numeric / GREATEST(CURRENT_DATE - g.release_date, 1)) AS velocity, g.platforms,
               g.deck_compatibility, gn.slug AS genre_slug,
               EXISTS (SELECT 1 FROM game_genres gg2 WHERE gg2.appid = g.appid AND gg2.genre_id = 70) AS has_ea
        FROM games g
        JOIN game_genres gg ON gg.appid = g.appid
        JOIN genres gn ON gg.genre_id = gn.id
        WHERE g.release_date IS NOT NULL AND g.coming_soon = FALSE
          AND g.type IN ('game', 'dlc') AND g.review_count >= 10
    ),
    grains AS (
        SELECT 'week'::text AS granularity UNION ALL SELECT 'month'
        UNION ALL SELECT 'quarter' UNION ALL SELECT 'year'
    ),
    game_types AS (
        SELECT 'game'::text AS game_type UNION ALL SELECT 'dlc' UNION ALL SELECT 'all'
    )
    SELECT
        gt.game_type,
        gr.granularity,
        DATE_TRUNC(gr.granularity, b.release_date) AS period,
        b.genre_slug,
        COUNT(*) AS releases,
        COUNT(*) FILTER (WHERE b.is_free) AS free_count,
        ROUND(AVG(b.review_count)::numeric, 0) AS avg_reviews,
        ROUND(AVG(CASE WHEN b.is_free THEN 0 ELSE b.price_usd END)::numeric, 2) AS avg_price_incl_free,
        COUNT(*) FILTER (WHERE b.positive_pct >= 70) AS positive_count,
        COUNT(*) FILTER (WHERE b.positive_pct >= 40 AND b.positive_pct < 70) AS mixed_count,
        COUNT(*) FILTER (WHERE b.positive_pct < 40) AS negative_count,
        ROUND(AVG(b.positive_pct)::numeric, 1) AS avg_steam_pct,
        ROUND(AVG(b.metacritic_score) FILTER (WHERE b.metacritic_score IS NOT NULL)::numeric, 1) AS avg_metacritic,
        ROUND(AVG(b.price_usd) FILTER (WHERE NOT b.is_free)::numeric, 2) AS avg_paid_price,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.price_usd) FILTER (WHERE NOT b.is_free)::numeric, 2) AS median_price,
        ROUND(COUNT(*) FILTER (WHERE b.is_free)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS free_pct,
        COUNT(*) FILTER (WHERE b.velocity < 1) AS velocity_under_1,
        COUNT(*) FILTER (WHERE b.velocity >= 1 AND b.velocity < 10) AS velocity_1_10,
        COUNT(*) FILTER (WHERE b.velocity >= 10 AND b.velocity < 50) AS velocity_10_50,
        COUNT(*) FILTER (WHERE b.velocity >= 50) AS velocity_50_plus,
        ROUND(COUNT(*) FILTER (WHERE (b.platforms->>'mac')::boolean)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS mac_pct,
        ROUND(COUNT(*) FILTER (WHERE (b.platforms->>'linux')::boolean)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS linux_pct,
        ROUND(COUNT(*) FILTER (WHERE b.deck_compatibility = 3)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS deck_verified_pct,
        ROUND(COUNT(*) FILTER (WHERE b.deck_compatibility = 2)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS deck_playable_pct,
        ROUND(COUNT(*) FILTER (WHERE b.deck_compatibility = 1)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS deck_unsupported_pct,
        COUNT(*) FILTER (WHERE b.has_ea) AS ea_count,
        ROUND(COUNT(*) FILTER (WHERE b.has_ea)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS ea_pct,
        ROUND(AVG(b.positive_pct) FILTER (WHERE b.has_ea)::numeric, 1) AS ea_avg_steam_pct,
        ROUND(AVG(b.positive_pct) FILTER (WHERE NOT b.has_ea)::numeric, 1) AS non_ea_avg_steam_pct
    FROM base b CROSS JOIN grains gr CROSS JOIN game_types gt
    WHERE gt.game_type = 'all' OR b.src_type = gt.game_type
    GROUP BY 1, 2, 3, 4""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_trend_by_genre_pk ON mv_trend_by_genre(game_type, granularity, genre_slug, period)",
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_trend_by_tag AS
    WITH base AS (
        SELECT g.appid, g.type AS src_type, g.release_date, g.is_free, g.price_usd, g.positive_pct,
               g.metacritic_score, g.review_count, COALESCE(g.review_velocity_lifetime, g.review_count::numeric / GREATEST(CURRENT_DATE - g.release_date, 1)) AS velocity, g.platforms,
               g.deck_compatibility, t.slug AS tag_slug,
               EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS has_ea
        FROM games g
        JOIN game_tags gt ON gt.appid = g.appid
        JOIN tags t ON gt.tag_id = t.id
        WHERE g.release_date IS NOT NULL AND g.coming_soon = FALSE
          AND g.type IN ('game', 'dlc') AND g.review_count >= 10
    ),
    grains AS (
        SELECT 'week'::text AS granularity UNION ALL SELECT 'month'
        UNION ALL SELECT 'quarter' UNION ALL SELECT 'year'
    ),
    game_types AS (
        SELECT 'game'::text AS game_type UNION ALL SELECT 'dlc' UNION ALL SELECT 'all'
    )
    SELECT
        gt.game_type,
        gr.granularity,
        DATE_TRUNC(gr.granularity, b.release_date) AS period,
        b.tag_slug,
        COUNT(*) AS releases,
        COUNT(*) FILTER (WHERE b.is_free) AS free_count,
        ROUND(AVG(b.review_count)::numeric, 0) AS avg_reviews,
        ROUND(AVG(CASE WHEN b.is_free THEN 0 ELSE b.price_usd END)::numeric, 2) AS avg_price_incl_free,
        COUNT(*) FILTER (WHERE b.positive_pct >= 70) AS positive_count,
        COUNT(*) FILTER (WHERE b.positive_pct >= 40 AND b.positive_pct < 70) AS mixed_count,
        COUNT(*) FILTER (WHERE b.positive_pct < 40) AS negative_count,
        ROUND(AVG(b.positive_pct)::numeric, 1) AS avg_steam_pct,
        ROUND(AVG(b.metacritic_score) FILTER (WHERE b.metacritic_score IS NOT NULL)::numeric, 1) AS avg_metacritic,
        ROUND(AVG(b.price_usd) FILTER (WHERE NOT b.is_free)::numeric, 2) AS avg_paid_price,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.price_usd) FILTER (WHERE NOT b.is_free)::numeric, 2) AS median_price,
        ROUND(COUNT(*) FILTER (WHERE b.is_free)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS free_pct,
        COUNT(*) FILTER (WHERE b.velocity < 1) AS velocity_under_1,
        COUNT(*) FILTER (WHERE b.velocity >= 1 AND b.velocity < 10) AS velocity_1_10,
        COUNT(*) FILTER (WHERE b.velocity >= 10 AND b.velocity < 50) AS velocity_10_50,
        COUNT(*) FILTER (WHERE b.velocity >= 50) AS velocity_50_plus,
        ROUND(COUNT(*) FILTER (WHERE (b.platforms->>'mac')::boolean)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS mac_pct,
        ROUND(COUNT(*) FILTER (WHERE (b.platforms->>'linux')::boolean)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS linux_pct,
        ROUND(COUNT(*) FILTER (WHERE b.deck_compatibility = 3)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS deck_verified_pct,
        ROUND(COUNT(*) FILTER (WHERE b.deck_compatibility = 2)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS deck_playable_pct,
        ROUND(COUNT(*) FILTER (WHERE b.deck_compatibility = 1)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS deck_unsupported_pct,
        COUNT(*) FILTER (WHERE b.has_ea) AS ea_count,
        ROUND(COUNT(*) FILTER (WHERE b.has_ea)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS ea_pct,
        ROUND(AVG(b.positive_pct) FILTER (WHERE b.has_ea)::numeric, 1) AS ea_avg_steam_pct,
        ROUND(AVG(b.positive_pct) FILTER (WHERE NOT b.has_ea)::numeric, 1) AS non_ea_avg_steam_pct
    FROM base b CROSS JOIN grains gr CROSS JOIN game_types gt
    WHERE gt.game_type = 'all' OR b.src_type = gt.game_type
    GROUP BY 1, 2, 3, 4""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_trend_by_tag_pk ON mv_trend_by_tag(game_type, granularity, tag_slug, period)",
    # 0042_mv_new_releases_v2 — three-lens feed for /new-releases
    # Just Added lens uses steam_last_modified + coming_soon=TRUE (not discovered_at)
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_new_releases AS
    SELECT
        ac.appid,
        COALESCE(g.name, ac.name)            AS name,
        g.slug,
        g.type,
        g.developer,
        g.developer_slug,
        g.publisher,
        g.publisher_slug,
        g.header_image,
        g.release_date,
        g.release_date_raw,
        COALESCE(g.coming_soon, FALSE)       AS coming_soon,
        g.price_usd,
        COALESCE(g.is_free, FALSE)           AS is_free,
        g.review_count,
        g.review_count_english,
        g.positive_pct,
        g.review_score_desc,
        ac.discovered_at,
        ac.steam_last_modified,
        g.crawled_at                         AS meta_crawled_at,
        (g.appid IS NULL)                    AS metadata_pending,
        CASE
            WHEN g.release_date IS NOT NULL AND COALESCE(g.coming_soon, FALSE) = FALSE
            THEN (CURRENT_DATE - g.release_date)
        END                                   AS days_since_release,
        EXISTS (SELECT 1 FROM reports r WHERE r.appid = ac.appid) AS has_analysis,
        COALESCE((SELECT array_agg(tag_name ORDER BY votes DESC) FROM (
            SELECT t.name AS tag_name, gt.votes
            FROM game_tags gt JOIN tags t ON t.id = gt.tag_id
            WHERE gt.appid = ac.appid ORDER BY gt.votes DESC LIMIT 3
        ) tt), ARRAY[]::text[]) AS top_tags,
        COALESCE((SELECT array_agg(t.slug)
            FROM game_tags gt JOIN tags t ON t.id = gt.tag_id
            WHERE gt.appid = ac.appid), ARRAY[]::text[]) AS top_tag_slugs,
        COALESCE((SELECT array_agg(gn.name)
            FROM game_genres gg JOIN genres gn ON gn.id = gg.genre_id
            WHERE gg.appid = ac.appid), ARRAY[]::text[]) AS genres,
        COALESCE((SELECT array_agg(gn.slug)
            FROM game_genres gg JOIN genres gn ON gn.id = gg.genre_id
            WHERE gg.appid = ac.appid), ARRAY[]::text[]) AS genre_slugs
    FROM app_catalog ac
    LEFT JOIN games g ON g.appid = ac.appid
    WHERE (g.type IS NULL OR g.type = 'game')
      AND (
        (g.release_date IS NOT NULL AND COALESCE(g.coming_soon, FALSE) = FALSE
            AND g.release_date >= CURRENT_DATE - INTERVAL '365 days')
        OR (COALESCE(g.coming_soon, FALSE) = TRUE)
      )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS mv_new_releases_appid_idx ON mv_new_releases(appid)",
    "CREATE INDEX IF NOT EXISTS mv_new_releases_released_idx ON mv_new_releases(release_date DESC) WHERE coming_soon = FALSE AND release_date IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS mv_new_releases_upcoming_idx ON mv_new_releases(release_date ASC NULLS LAST) WHERE coming_soon = TRUE",
    "CREATE INDEX IF NOT EXISTS mv_new_releases_added_idx ON mv_new_releases(steam_last_modified DESC) WHERE coming_soon = TRUE",
    "CREATE INDEX IF NOT EXISTS mv_new_releases_genre_slugs_gin ON mv_new_releases USING GIN(genre_slugs)",
    "CREATE INDEX IF NOT EXISTS mv_new_releases_top_tag_slugs_gin ON mv_new_releases USING GIN(top_tag_slugs)",
    # 0037_analysis_candidates (extended in 0040 with request_count)
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_analysis_candidates AS
    SELECT
        g.appid,
        g.name AS game_name,
        g.slug,
        g.developer,
        g.header_image,
        g.review_count,
        g.positive_pct,
        g.review_score_desc,
        g.release_date,
        g.estimated_revenue_usd,
        COALESCE(ar.request_count, 0) AS request_count
    FROM games g
    LEFT JOIN reports r ON r.appid = g.appid
    LEFT JOIN (
        SELECT appid, COUNT(*) AS request_count
        FROM analysis_requests
        GROUP BY appid
    ) ar ON ar.appid = g.appid
    WHERE g.type = 'game'
      AND g.coming_soon = FALSE
      AND g.review_count >= 200
      AND r.appid IS NULL""",
    "CREATE UNIQUE INDEX IF NOT EXISTS mv_analysis_candidates_pk ON mv_analysis_candidates(appid)",
    "CREATE INDEX IF NOT EXISTS mv_analysis_candidates_review_count_idx ON mv_analysis_candidates(review_count DESC)",
    "CREATE INDEX IF NOT EXISTS mv_analysis_candidates_request_count_idx ON mv_analysis_candidates(request_count DESC)",
    # 0039_catalog_reports_matview — games with completed analysis reports
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_catalog_reports AS
    SELECT
        g.appid, g.name, g.slug, g.developer, g.developer_slug,
        g.header_image, g.release_date, g.price_usd,
        COALESCE(g.is_free, FALSE) AS is_free,
        g.review_count, g.positive_pct, g.review_score_desc,
        g.hidden_gem_score, g.estimated_revenue_usd,
        r.last_analyzed, r.reviews_analyzed,
        COALESCE((
            SELECT array_agg(tag_name ORDER BY votes DESC)
            FROM (
                SELECT t.name AS tag_name, gt.votes
                FROM game_tags gt JOIN tags t ON t.id = gt.tag_id
                WHERE gt.appid = g.appid
                ORDER BY gt.votes DESC LIMIT 3
            ) tt
        ), ARRAY[]::text[]) AS top_tags,
        COALESCE((
            SELECT array_agg(t.slug)
            FROM game_tags gt JOIN tags t ON t.id = gt.tag_id
            WHERE gt.appid = g.appid
        ), ARRAY[]::text[]) AS tag_slugs,
        COALESCE((
            SELECT array_agg(gn.name)
            FROM game_genres gg JOIN genres gn ON gn.id = gg.genre_id
            WHERE gg.appid = g.appid
        ), ARRAY[]::text[]) AS genres,
        COALESCE((
            SELECT array_agg(gn.slug)
            FROM game_genres gg JOIN genres gn ON gn.id = gg.genre_id
            WHERE gg.appid = g.appid
        ), ARRAY[]::text[]) AS genre_slugs
    FROM games g
    JOIN reports r ON r.appid = g.appid
    WHERE g.type = 'game'
      AND r.is_public = TRUE""",
    "CREATE UNIQUE INDEX IF NOT EXISTS mv_catalog_reports_pk ON mv_catalog_reports(appid)",
    "CREATE INDEX IF NOT EXISTS mv_catalog_reports_last_analyzed_idx ON mv_catalog_reports(last_analyzed DESC)",
    "CREATE INDEX IF NOT EXISTS mv_catalog_reports_review_count_idx ON mv_catalog_reports(review_count DESC)",
    "CREATE INDEX IF NOT EXISTS mv_catalog_reports_hidden_gem_idx ON mv_catalog_reports(hidden_gem_score DESC NULLS LAST)",
    "CREATE INDEX IF NOT EXISTS mv_catalog_reports_positive_pct_idx ON mv_catalog_reports(positive_pct DESC NULLS LAST)",
    "CREATE INDEX IF NOT EXISTS mv_catalog_reports_genre_slugs_gin ON mv_catalog_reports USING GIN(genre_slugs)",
    "CREATE INDEX IF NOT EXISTS mv_catalog_reports_tag_slugs_gin ON mv_catalog_reports USING GIN(tag_slugs)",
    # 0044_audience_overlap_matview — precomputed top-50 audience overlap per game
    """CREATE MATERIALIZED VIEW IF NOT EXISTS mv_audience_overlap AS
    WITH games_with_reviews AS (
        SELECT appid
        FROM reviews
        WHERE author_steamid IS NOT NULL
        GROUP BY appid
        HAVING COUNT(DISTINCT author_steamid) >= 100
    ),
    reviewer_sample AS (
        SELECT appid, author_steamid, voted_up
        FROM (
            SELECT r.appid, r.author_steamid, r.voted_up,
                   ROW_NUMBER() OVER (PARTITION BY r.appid ORDER BY r.author_steamid) AS rn
            FROM reviews r
            JOIN games_with_reviews g ON r.appid = g.appid
            WHERE r.author_steamid IS NOT NULL
        ) ranked
        WHERE rn <= 10000
    ),
    reviewer_counts AS (
        SELECT appid, COUNT(*) AS total_reviewers
        FROM reviewer_sample
        GROUP BY appid
    ),
    overlap_raw AS (
        SELECT a.appid,
               b.appid AS overlap_appid,
               COUNT(*) AS overlap_count,
               ROUND(COUNT(*) FILTER (WHERE b.voted_up)::numeric
                     / NULLIF(COUNT(*), 0) * 100, 1) AS shared_sentiment_pct
        FROM reviewer_sample a
        JOIN reviewer_sample b ON a.author_steamid = b.author_steamid AND a.appid != b.appid
        GROUP BY a.appid, b.appid
    ),
    ranked AS (
        SELECT o.appid, o.overlap_appid, o.overlap_count, o.shared_sentiment_pct,
               rc.total_reviewers,
               ROUND(o.overlap_count::numeric / NULLIF(rc.total_reviewers, 0) * 100, 1) AS overlap_pct,
               ROW_NUMBER() OVER (PARTITION BY o.appid ORDER BY o.overlap_count DESC) AS rank
        FROM overlap_raw o
        JOIN reviewer_counts rc ON o.appid = rc.appid
    )
    SELECT appid, overlap_appid, overlap_count, total_reviewers, overlap_pct, shared_sentiment_pct
    FROM ranked
    WHERE rank <= 50""",
    "CREATE UNIQUE INDEX IF NOT EXISTS mv_audience_overlap_pk ON mv_audience_overlap(appid, overlap_appid)",
    "CREATE INDEX IF NOT EXISTS mv_audience_overlap_appid_rank ON mv_audience_overlap(appid, overlap_count DESC)",
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
    # NOTE: dropping the legacy `games.sentiment_score` column happens in
    # create_matviews(), AFTER the dependent matviews are dropped — Postgres
    # would otherwise refuse the ALTER. Don't move it back here.


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
        # Drop matviews whose column shape changed (data-source-clarity refactor:
        # avg_sentiment → avg_steam_pct, removal of g.sentiment_score). IF NOT EXISTS
        # below would otherwise leave the stale definition on persistent test DBs.
        for view in (
            "mv_genre_games",
            "mv_tag_games",
            "mv_price_positioning",
            "mv_release_timing",
            "mv_platform_distribution",
            "mv_tag_trend",
            # Dropped so a persistent test DB picks up schema changes to
            # mv_new_releases (added genre_slugs / top_tag_slugs arrays).
            "mv_new_releases",
            "mv_analysis_candidates",
            "mv_catalog_reports",
            "mv_audience_overlap",
            # Dropped so persistent test DBs pick up trend matview schema changes:
            # added avg_reviews + avg_price_incl_free columns, plus the new
            # game_type dimension and updated unique-index/key shape.
            "mv_trend_catalog",
            "mv_trend_by_genre",
            "mv_trend_by_tag",
        ):
            cur.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view}")
        # Now that all dependent matviews are gone, drop the legacy
        # games.sentiment_score column on persistent test DBs (mirrors
        # migration 0021_drop_sentiment_score). Must run BEFORE we recreate
        # the matviews below — they reference g.positive_pct, not sentiment_score.
        cur.execute("DROP INDEX IF EXISTS idx_games_sentiment_score")
        cur.execute("ALTER TABLE games DROP COLUMN IF EXISTS sentiment_score")
        for ddl in MATERIALIZED_VIEWS:
            cur.execute(ddl)
    conn.commit()  # type: ignore[union-attr]
