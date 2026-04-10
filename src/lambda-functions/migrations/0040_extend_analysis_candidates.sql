-- depends: 0039_catalog_reports_matview
--
-- Extend mv_analysis_candidates with request_count from analysis_requests.
-- Drop + recreate to add the new column.

DROP MATERIALIZED VIEW IF EXISTS mv_analysis_candidates;

CREATE MATERIALIZED VIEW mv_analysis_candidates AS
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
  AND r.appid IS NULL;

CREATE UNIQUE INDEX mv_analysis_candidates_pk ON mv_analysis_candidates(appid);
CREATE INDEX mv_analysis_candidates_review_count_idx ON mv_analysis_candidates(review_count DESC);
CREATE INDEX mv_analysis_candidates_request_count_idx ON mv_analysis_candidates(request_count DESC);
