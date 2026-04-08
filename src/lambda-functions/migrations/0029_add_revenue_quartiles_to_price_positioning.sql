-- depends: 0028_add_revenue_to_game_matviews

-- Recreate mv_price_positioning to include Boxleiter revenue quartiles per
-- price bucket. Previously `analytics_repo.find_price_positioning` computed
-- these live via PERCENTILE_CONT on every request, which is expensive for a
-- hot endpoint. Precomputing them into the matview restores predictable
-- latency and lets cdk-monitoring alarms catch drift via matview age.

DROP MATERIALIZED VIEW IF EXISTS mv_price_positioning;

CREATE MATERIALIZED VIEW mv_price_positioning AS
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
    -- Boxleiter v1 gross revenue quartiles (pre-Steam-cut, +/-50%).
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
GROUP BY gn.slug, gn.name, 3;

CREATE UNIQUE INDEX idx_mv_price_positioning_pk
    ON mv_price_positioning(genre_slug, price_range);
