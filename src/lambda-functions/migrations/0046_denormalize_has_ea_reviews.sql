-- depends: 0045_extend_trend_matviews

-- Denormalize has_early_access_reviews onto games to eliminate the ea_flags CTE
-- (full reviews table scan) from trend matview refreshes.

-- 1. Add column
ALTER TABLE games ADD COLUMN IF NOT EXISTS has_early_access_reviews BOOLEAN DEFAULT FALSE;

-- 2. Backfill from reviews (join against precomputed distinct set for efficiency)
UPDATE games g
SET has_early_access_reviews = TRUE
FROM (
    SELECT DISTINCT r.appid
    FROM reviews r
    WHERE r.written_during_early_access = TRUE
) ea_reviews
WHERE g.has_early_access_reviews = FALSE
  AND ea_reviews.appid = g.appid;

-- 3. Recreate trend matviews with ea_flags CTE removed

-- ---------------------------------------------------------------------------
-- mv_trend_catalog
-- ---------------------------------------------------------------------------

DROP MATERIALIZED VIEW IF EXISTS mv_trend_catalog;

CREATE MATERIALIZED VIEW mv_trend_catalog AS
WITH base AS (
    SELECT
        g.appid,
        g.type AS src_type,
        g.release_date,
        g.is_free,
        g.price_usd,
        g.positive_pct,
        g.metacritic_score,
        g.review_count,
        COALESCE(g.review_velocity_lifetime,
            g.review_count::numeric / GREATEST(CURRENT_DATE - g.release_date, 1)
        ) AS velocity,
        g.platforms,
        g.deck_compatibility,
        COALESCE(g.has_early_access_reviews, FALSE) AS has_ea
    FROM games g
    WHERE g.release_date IS NOT NULL
      AND g.coming_soon = FALSE
      AND g.type IN ('game', 'dlc')
      AND g.review_count >= 10
),
grains AS (
    SELECT 'week'::text AS granularity UNION ALL
    SELECT 'month' UNION ALL
    SELECT 'quarter' UNION ALL
    SELECT 'year'
),
game_types AS (
    SELECT 'game'::text AS game_type UNION ALL
    SELECT 'dlc' UNION ALL
    SELECT 'all'
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
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.price_usd)
        FILTER (WHERE NOT b.is_free)::numeric, 2
    ) AS median_price,
    ROUND(
        COUNT(*) FILTER (WHERE b.is_free)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS free_pct,
    COUNT(*) FILTER (WHERE b.velocity < 1) AS velocity_under_1,
    COUNT(*) FILTER (WHERE b.velocity >= 1 AND b.velocity < 10) AS velocity_1_10,
    COUNT(*) FILTER (WHERE b.velocity >= 10 AND b.velocity < 50) AS velocity_10_50,
    COUNT(*) FILTER (WHERE b.velocity >= 50) AS velocity_50_plus,
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
CROSS JOIN game_types gt
WHERE gt.game_type = 'all' OR b.src_type = gt.game_type
GROUP BY 1, 2, 3;

CREATE UNIQUE INDEX idx_mv_trend_catalog_pk ON mv_trend_catalog(game_type, granularity, period);

-- ---------------------------------------------------------------------------
-- mv_trend_by_genre
-- ---------------------------------------------------------------------------

DROP MATERIALIZED VIEW IF EXISTS mv_trend_by_genre;

CREATE MATERIALIZED VIEW mv_trend_by_genre AS
WITH base AS (
    SELECT
        g.appid,
        g.type AS src_type,
        g.release_date,
        g.is_free,
        g.price_usd,
        g.positive_pct,
        g.metacritic_score,
        g.review_count,
        COALESCE(g.review_velocity_lifetime,
            g.review_count::numeric / GREATEST(CURRENT_DATE - g.release_date, 1)
        ) AS velocity,
        g.platforms,
        g.deck_compatibility,
        gn.slug AS genre_slug,
        COALESCE(g.has_early_access_reviews, FALSE) AS has_ea
    FROM games g
    JOIN game_genres gg ON gg.appid = g.appid
    JOIN genres gn ON gg.genre_id = gn.id
    WHERE g.release_date IS NOT NULL
      AND g.coming_soon = FALSE
      AND g.type IN ('game', 'dlc')
      AND g.review_count >= 10
),
grains AS (
    SELECT 'week'::text AS granularity UNION ALL
    SELECT 'month' UNION ALL
    SELECT 'quarter' UNION ALL
    SELECT 'year'
),
game_types AS (
    SELECT 'game'::text AS game_type UNION ALL
    SELECT 'dlc' UNION ALL
    SELECT 'all'
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
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.price_usd)
        FILTER (WHERE NOT b.is_free)::numeric, 2
    ) AS median_price,
    ROUND(
        COUNT(*) FILTER (WHERE b.is_free)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS free_pct,
    COUNT(*) FILTER (WHERE b.velocity < 1) AS velocity_under_1,
    COUNT(*) FILTER (WHERE b.velocity >= 1 AND b.velocity < 10) AS velocity_1_10,
    COUNT(*) FILTER (WHERE b.velocity >= 10 AND b.velocity < 50) AS velocity_10_50,
    COUNT(*) FILTER (WHERE b.velocity >= 50) AS velocity_50_plus,
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
CROSS JOIN game_types gt
WHERE gt.game_type = 'all' OR b.src_type = gt.game_type
GROUP BY 1, 2, 3, 4;

CREATE UNIQUE INDEX idx_mv_trend_by_genre_pk ON mv_trend_by_genre(game_type, granularity, genre_slug, period);

-- ---------------------------------------------------------------------------
-- mv_trend_by_tag
-- ---------------------------------------------------------------------------

DROP MATERIALIZED VIEW IF EXISTS mv_trend_by_tag;

CREATE MATERIALIZED VIEW mv_trend_by_tag AS
WITH base AS (
    SELECT
        g.appid,
        g.type AS src_type,
        g.release_date,
        g.is_free,
        g.price_usd,
        g.positive_pct,
        g.metacritic_score,
        g.review_count,
        COALESCE(g.review_velocity_lifetime,
            g.review_count::numeric / GREATEST(CURRENT_DATE - g.release_date, 1)
        ) AS velocity,
        g.platforms,
        g.deck_compatibility,
        t.slug AS tag_slug,
        COALESCE(g.has_early_access_reviews, FALSE) AS has_ea
    FROM games g
    JOIN game_tags gt ON gt.appid = g.appid
    JOIN tags t ON gt.tag_id = t.id
    WHERE g.release_date IS NOT NULL
      AND g.coming_soon = FALSE
      AND g.type IN ('game', 'dlc')
      AND g.review_count >= 10
),
grains AS (
    SELECT 'week'::text AS granularity UNION ALL
    SELECT 'month' UNION ALL
    SELECT 'quarter' UNION ALL
    SELECT 'year'
),
game_types AS (
    SELECT 'game'::text AS game_type UNION ALL
    SELECT 'dlc' UNION ALL
    SELECT 'all'
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
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.price_usd)
        FILTER (WHERE NOT b.is_free)::numeric, 2
    ) AS median_price,
    ROUND(
        COUNT(*) FILTER (WHERE b.is_free)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS free_pct,
    COUNT(*) FILTER (WHERE b.velocity < 1) AS velocity_under_1,
    COUNT(*) FILTER (WHERE b.velocity >= 1 AND b.velocity < 10) AS velocity_1_10,
    COUNT(*) FILTER (WHERE b.velocity >= 10 AND b.velocity < 50) AS velocity_10_50,
    COUNT(*) FILTER (WHERE b.velocity >= 50) AS velocity_50_plus,
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
CROSS JOIN game_types gt
WHERE gt.game_type = 'all' OR b.src_type = gt.game_type
GROUP BY 1, 2, 3, 4;

CREATE UNIQUE INDEX idx_mv_trend_by_tag_pk ON mv_trend_by_tag(game_type, granularity, tag_slug, period);
