-- depends: 0021_drop_sentiment_score

-- Rename matview `avg_sentiment` columns to `avg_steam_pct`. The values were
-- always Steam's positive_pct — the old name implied an AI-derived score, which
-- it never was. See scripts/prompts/data-source-clarity.md.
--
-- Each affected matview is dropped and recreated. Indexes are recreated too;
-- the UNIQUE indexes are required so future REFRESH MATERIALIZED VIEW CONCURRENTLY
-- calls succeed.

DROP MATERIALIZED VIEW IF EXISTS mv_price_positioning;
CREATE MATERIALIZED VIEW mv_price_positioning AS
SELECT
    gn.slug AS genre_slug,
    gn.name AS genre_name,
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
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY COALESCE(g.price_usd, 0))::numeric,
        2
    ) AS median_price
FROM games g
JOIN game_genres gg ON gg.appid = g.appid
JOIN genres gn ON gg.genre_id = gn.id
WHERE g.review_count >= 10
  AND (g.price_usd IS NOT NULL OR g.is_free)
GROUP BY gn.slug, gn.name, 3;

CREATE UNIQUE INDEX idx_mv_price_positioning_pk
    ON mv_price_positioning(genre_slug, price_range);

DROP MATERIALIZED VIEW IF EXISTS mv_release_timing;
CREATE MATERIALIZED VIEW mv_release_timing AS
SELECT
    gn.slug AS genre_slug,
    gn.name AS genre_name,
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
GROUP BY gn.slug, gn.name, 3;

CREATE UNIQUE INDEX idx_mv_release_timing_pk
    ON mv_release_timing(genre_slug, month);

DROP MATERIALIZED VIEW IF EXISTS mv_platform_distribution;
CREATE MATERIALIZED VIEW mv_platform_distribution AS
SELECT
    gn.slug AS genre_slug,
    gn.name AS genre_name,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE (g.platforms->>'windows')::boolean) AS windows,
    COUNT(*) FILTER (WHERE (g.platforms->>'mac')::boolean) AS mac,
    COUNT(*) FILTER (WHERE (g.platforms->>'linux')::boolean) AS linux,
    ROUND(AVG(g.positive_pct) FILTER (WHERE (g.platforms->>'windows')::boolean), 1)
        AS windows_avg_steam_pct,
    ROUND(AVG(g.positive_pct) FILTER (WHERE (g.platforms->>'mac')::boolean), 1)
        AS mac_avg_steam_pct,
    ROUND(AVG(g.positive_pct) FILTER (WHERE (g.platforms->>'linux')::boolean), 1)
        AS linux_avg_steam_pct
FROM games g
JOIN game_genres gg ON gg.appid = g.appid
JOIN genres gn ON gg.genre_id = gn.id
WHERE g.platforms IS NOT NULL
  AND g.review_count >= 10
GROUP BY gn.slug, gn.name;

CREATE UNIQUE INDEX idx_mv_platform_distribution_pk
    ON mv_platform_distribution(genre_slug);

DROP MATERIALIZED VIEW IF EXISTS mv_tag_trend;
CREATE MATERIALIZED VIEW mv_tag_trend AS
SELECT
    t.slug AS tag_slug,
    t.name AS tag_name,
    EXTRACT(YEAR FROM g.release_date)::int AS year,
    COUNT(*) AS game_count,
    ROUND(AVG(g.positive_pct), 1) AS avg_steam_pct
FROM games g
JOIN game_tags gt ON gt.appid = g.appid
JOIN tags t ON gt.tag_id = t.id
WHERE g.release_date IS NOT NULL
  AND EXTRACT(YEAR FROM g.release_date) >= 2015
GROUP BY t.slug, t.name, 3;

CREATE UNIQUE INDEX idx_mv_tag_trend_pk
    ON mv_tag_trend(tag_slug, year);
