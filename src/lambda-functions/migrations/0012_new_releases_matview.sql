-- depends: 0011_steamspy_data

-- Materialized view backing the /new-releases feed (Released, Coming Soon, Just Added).
-- Bounded to a 90-day window so it stays small and refreshes fast. Anything outside
-- that window is not surfaced on the feed pages anyway.
--
-- Refreshed at the end of CatalogService.refresh() (hourly EventBridge trigger). The
-- unique index on appid makes REFRESH MATERIALIZED VIEW CONCURRENTLY possible.
--
-- LEFT JOIN games on purpose: a freshly discovered appid in app_catalog may not yet
-- have a matching games row (metadata crawl pending). The "Just Added" lens needs to
-- show those rows with a "metadata pending" badge instead of hiding them.

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_new_releases AS
SELECT
    ac.appid,
    COALESCE(g.name, ac.name)            AS name,
    g.slug,
    g.type,
    g.developer,
    g.developer_slug,
    g.publisher,
    g.header_image,
    g.release_date,
    COALESCE(g.coming_soon, FALSE)       AS coming_soon,
    g.price_usd,
    COALESCE(g.is_free, FALSE)           AS is_free,
    g.review_count,
    g.review_count_english,
    g.positive_pct,
    g.review_score_desc,
    ac.discovered_at,
    g.crawled_at                         AS meta_crawled_at,
    (g.appid IS NULL)                    AS metadata_pending,
    CASE
        WHEN g.release_date IS NOT NULL AND COALESCE(g.coming_soon, FALSE) = FALSE
        THEN (CURRENT_DATE - g.release_date)
    END                                   AS days_since_release,
    EXISTS (SELECT 1 FROM reports r WHERE r.appid = ac.appid) AS has_analysis,
    -- Top 3 player tags by vote count, as a Postgres array.
    COALESCE(
        (
            SELECT array_agg(tag_name ORDER BY votes DESC)
            FROM (
                SELECT t.name AS tag_name, gt.votes
                FROM game_tags gt
                JOIN tags t ON t.id = gt.tag_id
                WHERE gt.appid = ac.appid
                ORDER BY gt.votes DESC
                LIMIT 3
            ) tt
        ),
        ARRAY[]::text[]
    ) AS top_tags
FROM app_catalog ac
LEFT JOIN games g ON g.appid = ac.appid
WHERE
    -- Skip non-game types from the feed (DLC, demos, music, tools).
    (g.type IS NULL OR g.type = 'game')
    AND (
        -- Released within the last 90 days
        (g.release_date IS NOT NULL
            AND COALESCE(g.coming_soon, FALSE) = FALSE
            AND g.release_date >= CURRENT_DATE - INTERVAL '90 days')
        -- Or coming soon
        OR (COALESCE(g.coming_soon, FALSE) = TRUE)
        -- Or first added to our catalog within the last 30 days (Just Added lens)
        OR (ac.discovered_at >= NOW() - INTERVAL '30 days')
    );

CREATE UNIQUE INDEX IF NOT EXISTS mv_new_releases_appid_idx
    ON mv_new_releases (appid);

CREATE INDEX IF NOT EXISTS mv_new_releases_released_idx
    ON mv_new_releases (release_date DESC)
    WHERE coming_soon = FALSE AND release_date IS NOT NULL;

CREATE INDEX IF NOT EXISTS mv_new_releases_upcoming_idx
    ON mv_new_releases (release_date ASC NULLS LAST)
    WHERE coming_soon = TRUE;

CREATE INDEX IF NOT EXISTS mv_new_releases_added_idx
    ON mv_new_releases (discovered_at DESC);
