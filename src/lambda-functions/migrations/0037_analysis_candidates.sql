-- depends: 0036_merged_summaries

DROP MATERIALIZED VIEW IF EXISTS mv_analysis_candidates;

CREATE MATERIALIZED VIEW mv_analysis_candidates AS
SELECT
    g.appid,
    g.name AS game_name,
    g.header_image,
    g.review_count,
    g.positive_pct,
    g.review_score_desc,
    g.release_date,
    g.estimated_revenue_usd
FROM games g
LEFT JOIN reports r ON r.appid = g.appid
WHERE g.type = 'game'
  AND g.coming_soon = FALSE
  AND g.review_count >= 200
  AND r.appid IS NULL
ORDER BY g.review_count DESC;

CREATE UNIQUE INDEX mv_analysis_candidates_pk ON mv_analysis_candidates(appid);
