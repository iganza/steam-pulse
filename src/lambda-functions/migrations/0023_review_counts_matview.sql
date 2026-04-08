-- 0023: materialized view for per-game stored review counts
-- Avoids full-table COUNT(*) aggregation on the 20M-row reviews table.
-- Refresh after bulk ingestion or on the same schedule as other matviews.

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_review_counts AS
SELECT
    appid,
    COUNT(*) AS stored_count
FROM reviews
GROUP BY appid;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_review_counts_appid
    ON mv_review_counts (appid);
