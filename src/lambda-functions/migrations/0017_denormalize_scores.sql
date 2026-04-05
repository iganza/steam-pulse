-- depends: 0016_materialized_views

-- Denormalize sentiment_score and hidden_gem_score onto games to eliminate
-- the LEFT JOIN reports (JSONB TOAST decompression) from catalog queries.
ALTER TABLE games ADD COLUMN IF NOT EXISTS sentiment_score REAL;
ALTER TABLE games ADD COLUMN IF NOT EXISTS hidden_gem_score REAL;

-- Backfill from existing reports.
UPDATE games g
SET sentiment_score = (r.report_json->>'sentiment_score')::real,
    hidden_gem_score = (r.report_json->>'hidden_gem_score')::real
FROM reports r
WHERE r.appid = g.appid
  AND g.sentiment_score IS NULL;
