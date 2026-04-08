-- depends: 0012_new_releases_matview

-- mv_new_releases v2: adds genre + tag slug arrays for filtering, widens the
-- bounded windows so the "All time" UI option has meaningful coverage.
--
-- Window changes:
--   Released: 90d → 365d  (so "All releases this year" works)
--   Just Added: 30d → 90d (still bounded, but a quarter of activity)
--
-- Schema additions:
--   genres        text[]  — display names
--   genre_slugs   text[]  — for WHERE filter
--   top_tag_slugs text[]  — for WHERE filter (top_tags already has names)

DROP MATERIALIZED VIEW IF EXISTS mv_new_releases;

CREATE MATERIALIZED VIEW mv_new_releases AS
SELECT
    ac.appid,
    COALESCE(g.name, ac.name)            AS name,
    g.slug,
    g.type,
    g.developer,
    g.developer_slug,
    g.publisher,
    g.publisher_slug,
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
    -- Top 3 tag names (display) and full tag-slug list (filter)
    COALESCE((
        SELECT array_agg(tag_name ORDER BY votes DESC)
        FROM (
            SELECT t.name AS tag_name, gt.votes
            FROM game_tags gt JOIN tags t ON t.id = gt.tag_id
            WHERE gt.appid = ac.appid
            ORDER BY gt.votes DESC LIMIT 3
        ) tt
    ), ARRAY[]::text[]) AS top_tags,
    COALESCE((
        SELECT array_agg(t.slug)
        FROM game_tags gt JOIN tags t ON t.id = gt.tag_id
        WHERE gt.appid = ac.appid
    ), ARRAY[]::text[]) AS top_tag_slugs,
    COALESCE((
        SELECT array_agg(gn.name)
        FROM game_genres gg JOIN genres gn ON gn.id = gg.genre_id
        WHERE gg.appid = ac.appid
    ), ARRAY[]::text[]) AS genres,
    COALESCE((
        SELECT array_agg(gn.slug)
        FROM game_genres gg JOIN genres gn ON gn.id = gg.genre_id
        WHERE gg.appid = ac.appid
    ), ARRAY[]::text[]) AS genre_slugs
FROM app_catalog ac
LEFT JOIN games g ON g.appid = ac.appid
WHERE
    (g.type IS NULL OR g.type = 'game')
    AND (
        -- Released within the last 365 days (covers the "All" pill nicely)
        (g.release_date IS NOT NULL
            AND COALESCE(g.coming_soon, FALSE) = FALSE
            AND g.release_date >= CURRENT_DATE - INTERVAL '365 days')
        -- Or coming soon
        OR (COALESCE(g.coming_soon, FALSE) = TRUE)
        -- Or first added to our catalog within the last 90 days
        OR (ac.discovered_at >= NOW() - INTERVAL '90 days')
    );

CREATE UNIQUE INDEX mv_new_releases_appid_idx
    ON mv_new_releases (appid);

CREATE INDEX mv_new_releases_released_idx
    ON mv_new_releases (release_date DESC)
    WHERE coming_soon = FALSE AND release_date IS NOT NULL;

CREATE INDEX mv_new_releases_upcoming_idx
    ON mv_new_releases (release_date ASC NULLS LAST)
    WHERE coming_soon = TRUE;

CREATE INDEX mv_new_releases_added_idx
    ON mv_new_releases (discovered_at DESC);

-- GIN indexes so genre/tag-slug filtering is index-backed.
CREATE INDEX mv_new_releases_genre_slugs_gin
    ON mv_new_releases USING GIN (genre_slugs);

CREATE INDEX mv_new_releases_top_tag_slugs_gin
    ON mv_new_releases USING GIN (top_tag_slugs);
