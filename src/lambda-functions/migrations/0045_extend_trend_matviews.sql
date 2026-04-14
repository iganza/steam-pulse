-- depends: 0044_audience_overlap_matview

-- Extend the three trend matviews with two new columns:
--   avg_reviews         — ROUND(AVG(review_count), 0)   (for release-volume endpoint)
--   avg_price_incl_free — ROUND(AVG(price_usd), 2)      (for pricing endpoint)
--
-- Also adds review_count to the base CTE so avg_reviews can be computed.
-- Drop + recreate is required because ALTER MATERIALIZED VIEW cannot add columns.
-- Unique indexes are recreated inline (not CONCURRENTLY — matview is freshly created).

-- ---------------------------------------------------------------------------
-- mv_trend_catalog
-- ---------------------------------------------------------------------------

DROP MATERIALIZED VIEW IF EXISTS mv_trend_catalog;

CREATE MATERIALIZED VIEW mv_trend_catalog AS
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
        g.review_count,
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
    ROUND(AVG(b.review_count)::numeric, 0) AS avg_reviews,
    ROUND(AVG(b.price_usd)::numeric, 2) AS avg_price_incl_free,
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

CREATE UNIQUE INDEX idx_mv_trend_catalog_pk ON mv_trend_catalog(granularity, period);

-- ---------------------------------------------------------------------------
-- mv_trend_by_genre
-- ---------------------------------------------------------------------------

DROP MATERIALIZED VIEW IF EXISTS mv_trend_by_genre;

CREATE MATERIALIZED VIEW mv_trend_by_genre AS
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
        g.review_count,
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
    ROUND(AVG(b.review_count)::numeric, 0) AS avg_reviews,
    ROUND(AVG(b.price_usd)::numeric, 2) AS avg_price_incl_free,
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

CREATE UNIQUE INDEX idx_mv_trend_by_genre_pk ON mv_trend_by_genre(granularity, genre_slug, period);

-- ---------------------------------------------------------------------------
-- mv_trend_by_tag
-- ---------------------------------------------------------------------------

DROP MATERIALIZED VIEW IF EXISTS mv_trend_by_tag;

CREATE MATERIALIZED VIEW mv_trend_by_tag AS
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
        g.review_count,
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
    ROUND(AVG(b.review_count)::numeric, 0) AS avg_reviews,
    ROUND(AVG(b.price_usd)::numeric, 2) AS avg_price_incl_free,
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

CREATE UNIQUE INDEX idx_mv_trend_by_tag_pk ON mv_trend_by_tag(granularity, tag_slug, period);
