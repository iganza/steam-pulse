-- depends: 0043_batch_executions

-- Precomputed audience overlap: top 50 overlapping games per appid by shared
-- reviewer count, with overlap_pct and shared_sentiment_pct.  Replaces the
-- live self-join in AnalyticsRepository.find_audience_overlap().

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_audience_overlap AS
WITH games_with_reviews AS (
    -- Only include games with >= 10 reviewers. Below that threshold
    -- overlap percentages are noisy, and excluding them dramatically
    -- shrinks the self-join (the costliest part of this matview).
    SELECT appid
    FROM reviews
    WHERE author_steamid IS NOT NULL
    GROUP BY appid
    HAVING COUNT(DISTINCT author_steamid) >= 100
),
reviewer_sample AS (
    -- Cap at 10k reviewers per game. Carries voted_up so overlap_raw
    -- computes shared_sentiment_pct without re-joining raw reviews.
    -- steam_review_id is UNIQUE so (appid, author_steamid) is 1:1.
    SELECT appid, author_steamid, voted_up
    FROM (
        SELECT r.appid, r.author_steamid, r.voted_up,
               ROW_NUMBER() OVER (PARTITION BY r.appid ORDER BY r.author_steamid) AS rn
        FROM reviews r
        JOIN games_with_reviews g ON r.appid = g.appid
        WHERE r.author_steamid IS NOT NULL
    ) ranked
    WHERE rn <= 10000
),
reviewer_counts AS (
    SELECT appid, COUNT(*) AS total_reviewers
    FROM reviewer_sample
    GROUP BY appid
),
overlap_raw AS (
    SELECT a.appid,
           b.appid AS overlap_appid,
           COUNT(*) AS overlap_count,
           ROUND(COUNT(*) FILTER (WHERE b.voted_up)::numeric
                 / NULLIF(COUNT(*), 0) * 100, 1) AS shared_sentiment_pct
    FROM reviewer_sample a
    JOIN reviewer_sample b ON a.author_steamid = b.author_steamid AND a.appid != b.appid
    GROUP BY a.appid, b.appid
),
ranked AS (
    SELECT o.appid, o.overlap_appid, o.overlap_count, o.shared_sentiment_pct,
           rc.total_reviewers,
           ROUND(o.overlap_count::numeric / NULLIF(rc.total_reviewers, 0) * 100, 1) AS overlap_pct,
           ROW_NUMBER() OVER (PARTITION BY o.appid ORDER BY o.overlap_count DESC) AS rank
    FROM overlap_raw o
    JOIN reviewer_counts rc ON o.appid = rc.appid
)
SELECT appid, overlap_appid, overlap_count, total_reviewers, overlap_pct, shared_sentiment_pct
FROM ranked
WHERE rank <= 50;

-- Required for REFRESH MATERIALIZED VIEW CONCURRENTLY
CREATE UNIQUE INDEX IF NOT EXISTS mv_audience_overlap_pk
    ON mv_audience_overlap(appid, overlap_appid);

CREATE INDEX IF NOT EXISTS mv_audience_overlap_appid_rank
    ON mv_audience_overlap(appid, overlap_count DESC);
