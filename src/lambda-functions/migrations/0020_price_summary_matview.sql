-- depends: 0019_genre_tag_game_matviews

-- Pre-computed price summary stats per genre — eliminates the expensive
-- AVG/MEDIAN/COUNT JOIN on games→game_genres→genres per request.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_price_summary AS
SELECT
    gn.slug AS genre_slug,
    ROUND(AVG(g.price_usd) FILTER (WHERE NOT g.is_free), 2) AS avg_price,
    ROUND(
        (PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY g.price_usd)
         FILTER (WHERE NOT g.is_free))::numeric,
        2
    ) AS median_price,
    COUNT(*) FILTER (WHERE g.is_free) AS free_count,
    COUNT(*) FILTER (WHERE NOT g.is_free) AS paid_count
FROM games g
JOIN game_genres gg ON gg.appid = g.appid
JOIN genres gn ON gg.genre_id = gn.id
WHERE g.review_count >= 10
GROUP BY gn.slug;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_price_summary_pk
    ON mv_price_summary(genre_slug);
