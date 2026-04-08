-- depends: 0023_review_counts_matview

-- Pre-computed trend matviews powering the Builder lens + /api/analytics/trend-query.
--
-- Three wide matviews, one per filter shape, each carrying every Builder metric
-- as a column so query_metrics can SELECT only the columns it needs from a
-- single relation with no joins and no live aggregation.
--
--   mv_trend_catalog   — key (granularity, period)                catalog-wide
--   mv_trend_by_genre  — key (granularity, period, genre_slug)    one row per genre per period
--   mv_trend_by_tag    — key (granularity, period, tag_slug)      one row per tag per period
--
-- Each matview is built as UNION ALL of four DATE_TRUNC aggregates (week, month,
-- quarter, year) over games filtered to review_count >= 10 and type='game'.
-- The ea_flags CTE is folded in so EA metrics sit directly in the matview.
--
-- Unique indexes on the key columns are created in 0025_add_trend_matview_indexes.sql
-- (CONCURRENTLY, outside a transaction) so future refreshes can use
-- REFRESH MATERIALIZED VIEW CONCURRENTLY.

-- ---------------------------------------------------------------------------
-- mv_trend_catalog
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_trend_catalog AS
WITH ea_flags AS (
    SELECT appid, BOOL_OR(written_during_early_access) AS has_ea
    FROM reviews
    GROUP BY appid
),
base AS (
    SELECT
        g.appid,
        g.release_date,
        g.is_free,
        g.price_usd,
        g.positive_pct,
        g.metacritic_score,
        g.review_velocity_lifetime,
        g.platforms,
        g.deck_compatibility,
        COALESCE(ef.has_ea, FALSE) AS has_ea
    FROM games g
    LEFT JOIN ea_flags ef ON ef.appid = g.appid
    WHERE g.release_date IS NOT NULL
      AND g.coming_soon = FALSE
      AND g.type = 'game'
      AND g.review_count >= 10
),
grains AS (
    SELECT 'week'::text AS granularity UNION ALL
    SELECT 'month' UNION ALL
    SELECT 'quarter' UNION ALL
    SELECT 'year'
)
SELECT
    gr.granularity,
    DATE_TRUNC(gr.granularity, b.release_date) AS period,
    COUNT(*) AS releases,
    COUNT(*) FILTER (WHERE b.is_free) AS free_count,
    COUNT(*) FILTER (WHERE b.positive_pct >= 70) AS positive_count,
    COUNT(*) FILTER (WHERE b.positive_pct >= 40 AND b.positive_pct < 70) AS mixed_count,
    COUNT(*) FILTER (WHERE b.positive_pct < 40) AS negative_count,
    ROUND(AVG(b.positive_pct)::numeric, 1) AS avg_steam_pct,
    ROUND(AVG(b.metacritic_score) FILTER (WHERE b.metacritic_score IS NOT NULL)::numeric, 1) AS avg_metacritic,
    ROUND(AVG(b.price_usd) FILTER (WHERE NOT b.is_free)::numeric, 2) AS avg_paid_price,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.price_usd)
        FILTER (WHERE NOT b.is_free)::numeric, 2
    ) AS median_price,
    ROUND(
        COUNT(*) FILTER (WHERE b.is_free)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS free_pct,
    COUNT(*) FILTER (WHERE b.review_velocity_lifetime < 1) AS velocity_under_1,
    COUNT(*) FILTER (WHERE b.review_velocity_lifetime >= 1 AND b.review_velocity_lifetime < 10) AS velocity_1_10,
    COUNT(*) FILTER (WHERE b.review_velocity_lifetime >= 10 AND b.review_velocity_lifetime < 50) AS velocity_10_50,
    COUNT(*) FILTER (WHERE b.review_velocity_lifetime >= 50) AS velocity_50_plus,
    ROUND(
        COUNT(*) FILTER (WHERE (b.platforms->>'mac')::boolean)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS mac_pct,
    ROUND(
        COUNT(*) FILTER (WHERE (b.platforms->>'linux')::boolean)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS linux_pct,
    ROUND(
        COUNT(*) FILTER (WHERE b.deck_compatibility = 3)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS deck_verified_pct,
    ROUND(
        COUNT(*) FILTER (WHERE b.deck_compatibility = 2)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS deck_playable_pct,
    ROUND(
        COUNT(*) FILTER (WHERE b.deck_compatibility = 1)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS deck_unsupported_pct,
    COUNT(*) FILTER (WHERE b.has_ea) AS ea_count,
    ROUND(
        COUNT(*) FILTER (WHERE b.has_ea)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS ea_pct,
    ROUND(AVG(b.positive_pct) FILTER (WHERE b.has_ea)::numeric, 1) AS ea_avg_steam_pct,
    ROUND(AVG(b.positive_pct) FILTER (WHERE NOT b.has_ea)::numeric, 1) AS non_ea_avg_steam_pct
FROM base b
CROSS JOIN grains gr
GROUP BY 1, 2;

-- ---------------------------------------------------------------------------
-- mv_trend_by_genre
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_trend_by_genre AS
WITH ea_flags AS (
    SELECT appid, BOOL_OR(written_during_early_access) AS has_ea
    FROM reviews
    GROUP BY appid
),
base AS (
    SELECT
        g.appid,
        g.release_date,
        g.is_free,
        g.price_usd,
        g.positive_pct,
        g.metacritic_score,
        g.review_velocity_lifetime,
        g.platforms,
        g.deck_compatibility,
        gn.slug AS genre_slug,
        COALESCE(ef.has_ea, FALSE) AS has_ea
    FROM games g
    JOIN game_genres gg ON gg.appid = g.appid
    JOIN genres gn ON gg.genre_id = gn.id
    LEFT JOIN ea_flags ef ON ef.appid = g.appid
    WHERE g.release_date IS NOT NULL
      AND g.coming_soon = FALSE
      AND g.type = 'game'
      AND g.review_count >= 10
),
grains AS (
    SELECT 'week'::text AS granularity UNION ALL
    SELECT 'month' UNION ALL
    SELECT 'quarter' UNION ALL
    SELECT 'year'
)
SELECT
    gr.granularity,
    DATE_TRUNC(gr.granularity, b.release_date) AS period,
    b.genre_slug,
    COUNT(*) AS releases,
    COUNT(*) FILTER (WHERE b.is_free) AS free_count,
    COUNT(*) FILTER (WHERE b.positive_pct >= 70) AS positive_count,
    COUNT(*) FILTER (WHERE b.positive_pct >= 40 AND b.positive_pct < 70) AS mixed_count,
    COUNT(*) FILTER (WHERE b.positive_pct < 40) AS negative_count,
    ROUND(AVG(b.positive_pct)::numeric, 1) AS avg_steam_pct,
    ROUND(AVG(b.metacritic_score) FILTER (WHERE b.metacritic_score IS NOT NULL)::numeric, 1) AS avg_metacritic,
    ROUND(AVG(b.price_usd) FILTER (WHERE NOT b.is_free)::numeric, 2) AS avg_paid_price,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.price_usd)
        FILTER (WHERE NOT b.is_free)::numeric, 2
    ) AS median_price,
    ROUND(
        COUNT(*) FILTER (WHERE b.is_free)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS free_pct,
    COUNT(*) FILTER (WHERE b.review_velocity_lifetime < 1) AS velocity_under_1,
    COUNT(*) FILTER (WHERE b.review_velocity_lifetime >= 1 AND b.review_velocity_lifetime < 10) AS velocity_1_10,
    COUNT(*) FILTER (WHERE b.review_velocity_lifetime >= 10 AND b.review_velocity_lifetime < 50) AS velocity_10_50,
    COUNT(*) FILTER (WHERE b.review_velocity_lifetime >= 50) AS velocity_50_plus,
    ROUND(
        COUNT(*) FILTER (WHERE (b.platforms->>'mac')::boolean)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS mac_pct,
    ROUND(
        COUNT(*) FILTER (WHERE (b.platforms->>'linux')::boolean)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS linux_pct,
    ROUND(
        COUNT(*) FILTER (WHERE b.deck_compatibility = 3)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS deck_verified_pct,
    ROUND(
        COUNT(*) FILTER (WHERE b.deck_compatibility = 2)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS deck_playable_pct,
    ROUND(
        COUNT(*) FILTER (WHERE b.deck_compatibility = 1)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS deck_unsupported_pct,
    COUNT(*) FILTER (WHERE b.has_ea) AS ea_count,
    ROUND(
        COUNT(*) FILTER (WHERE b.has_ea)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS ea_pct,
    ROUND(AVG(b.positive_pct) FILTER (WHERE b.has_ea)::numeric, 1) AS ea_avg_steam_pct,
    ROUND(AVG(b.positive_pct) FILTER (WHERE NOT b.has_ea)::numeric, 1) AS non_ea_avg_steam_pct
FROM base b
CROSS JOIN grains gr
GROUP BY 1, 2, 3;

-- ---------------------------------------------------------------------------
-- mv_trend_by_tag
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_trend_by_tag AS
WITH ea_flags AS (
    SELECT appid, BOOL_OR(written_during_early_access) AS has_ea
    FROM reviews
    GROUP BY appid
),
base AS (
    SELECT
        g.appid,
        g.release_date,
        g.is_free,
        g.price_usd,
        g.positive_pct,
        g.metacritic_score,
        g.review_velocity_lifetime,
        g.platforms,
        g.deck_compatibility,
        t.slug AS tag_slug,
        COALESCE(ef.has_ea, FALSE) AS has_ea
    FROM games g
    JOIN game_tags gt ON gt.appid = g.appid
    JOIN tags t ON gt.tag_id = t.id
    LEFT JOIN ea_flags ef ON ef.appid = g.appid
    WHERE g.release_date IS NOT NULL
      AND g.coming_soon = FALSE
      AND g.type = 'game'
      AND g.review_count >= 10
),
grains AS (
    SELECT 'week'::text AS granularity UNION ALL
    SELECT 'month' UNION ALL
    SELECT 'quarter' UNION ALL
    SELECT 'year'
)
SELECT
    gr.granularity,
    DATE_TRUNC(gr.granularity, b.release_date) AS period,
    b.tag_slug,
    COUNT(*) AS releases,
    COUNT(*) FILTER (WHERE b.is_free) AS free_count,
    COUNT(*) FILTER (WHERE b.positive_pct >= 70) AS positive_count,
    COUNT(*) FILTER (WHERE b.positive_pct >= 40 AND b.positive_pct < 70) AS mixed_count,
    COUNT(*) FILTER (WHERE b.positive_pct < 40) AS negative_count,
    ROUND(AVG(b.positive_pct)::numeric, 1) AS avg_steam_pct,
    ROUND(AVG(b.metacritic_score) FILTER (WHERE b.metacritic_score IS NOT NULL)::numeric, 1) AS avg_metacritic,
    ROUND(AVG(b.price_usd) FILTER (WHERE NOT b.is_free)::numeric, 2) AS avg_paid_price,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.price_usd)
        FILTER (WHERE NOT b.is_free)::numeric, 2
    ) AS median_price,
    ROUND(
        COUNT(*) FILTER (WHERE b.is_free)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS free_pct,
    COUNT(*) FILTER (WHERE b.review_velocity_lifetime < 1) AS velocity_under_1,
    COUNT(*) FILTER (WHERE b.review_velocity_lifetime >= 1 AND b.review_velocity_lifetime < 10) AS velocity_1_10,
    COUNT(*) FILTER (WHERE b.review_velocity_lifetime >= 10 AND b.review_velocity_lifetime < 50) AS velocity_10_50,
    COUNT(*) FILTER (WHERE b.review_velocity_lifetime >= 50) AS velocity_50_plus,
    ROUND(
        COUNT(*) FILTER (WHERE (b.platforms->>'mac')::boolean)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS mac_pct,
    ROUND(
        COUNT(*) FILTER (WHERE (b.platforms->>'linux')::boolean)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS linux_pct,
    ROUND(
        COUNT(*) FILTER (WHERE b.deck_compatibility = 3)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS deck_verified_pct,
    ROUND(
        COUNT(*) FILTER (WHERE b.deck_compatibility = 2)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS deck_playable_pct,
    ROUND(
        COUNT(*) FILTER (WHERE b.deck_compatibility = 1)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS deck_unsupported_pct,
    COUNT(*) FILTER (WHERE b.has_ea) AS ea_count,
    ROUND(
        COUNT(*) FILTER (WHERE b.has_ea)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS ea_pct,
    ROUND(AVG(b.positive_pct) FILTER (WHERE b.has_ea)::numeric, 1) AS ea_avg_steam_pct,
    ROUND(AVG(b.positive_pct) FILTER (WHERE NOT b.has_ea)::numeric, 1) AS non_ea_avg_steam_pct
FROM base b
CROSS JOIN grains gr
GROUP BY 1, 2, 3;
