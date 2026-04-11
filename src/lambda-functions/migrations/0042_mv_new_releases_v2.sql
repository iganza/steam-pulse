-- depends: 0041_capture_steam_fields
--
-- Recreate mv_new_releases to:
-- 1. Use steam_last_modified (from GetAppList) instead of discovered_at for the
--    "Just Added" lens — fixes the bulk-seed bug where all 159k games got
--    discovered_at = NOW() simultaneously.
-- 2. Restrict the "Just Added" bound to coming_soon games only.
-- 3. Add steam_last_modified and release_date_raw as columns.

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
    g.release_date_raw,
    COALESCE(g.coming_soon, FALSE)       AS coming_soon,
    g.price_usd,
    COALESCE(g.is_free, FALSE)           AS is_free,
    g.review_count,
    g.review_count_english,
    g.positive_pct,
    g.review_score_desc,
    ac.discovered_at,
    ac.steam_last_modified,
    g.crawled_at                         AS meta_crawled_at,
    (g.appid IS NULL)                    AS metadata_pending,
    CASE
        WHEN g.release_date IS NOT NULL AND COALESCE(g.coming_soon, FALSE) = FALSE
        THEN (CURRENT_DATE - g.release_date)
    END                                   AS days_since_release,
    EXISTS (SELECT 1 FROM reports r WHERE r.appid = ac.appid) AS has_analysis,
    COALESCE((SELECT array_agg(tag_name ORDER BY votes DESC) FROM (
        SELECT t.name AS tag_name, gt.votes
        FROM game_tags gt JOIN tags t ON t.id = gt.tag_id
        WHERE gt.appid = ac.appid ORDER BY gt.votes DESC LIMIT 3
    ) tt), ARRAY[]::text[]) AS top_tags,
    COALESCE((SELECT array_agg(t.slug)
        FROM game_tags gt JOIN tags t ON t.id = gt.tag_id
        WHERE gt.appid = ac.appid), ARRAY[]::text[]) AS top_tag_slugs,
    COALESCE((SELECT array_agg(gn.name)
        FROM game_genres gg JOIN genres gn ON gn.id = gg.genre_id
        WHERE gg.appid = ac.appid), ARRAY[]::text[]) AS genres,
    COALESCE((SELECT array_agg(gn.slug)
        FROM game_genres gg JOIN genres gn ON gn.id = gg.genre_id
        WHERE gg.appid = ac.appid), ARRAY[]::text[]) AS genre_slugs
FROM app_catalog ac
LEFT JOIN games g ON g.appid = ac.appid
WHERE (g.type IS NULL OR g.type = 'game')
  AND (
    (g.release_date IS NOT NULL AND COALESCE(g.coming_soon, FALSE) = FALSE
        AND g.release_date >= CURRENT_DATE - INTERVAL '365 days')
    OR (COALESCE(g.coming_soon, FALSE) = TRUE)
    OR (ac.steam_last_modified >= NOW() - INTERVAL '90 days'
        AND COALESCE(g.coming_soon, FALSE) = TRUE)
  );

-- Required for REFRESH MATERIALIZED VIEW CONCURRENTLY
CREATE UNIQUE INDEX mv_new_releases_appid_idx
    ON mv_new_releases(appid);

-- Released lens
CREATE INDEX mv_new_releases_released_idx
    ON mv_new_releases(release_date DESC)
    WHERE coming_soon = FALSE AND release_date IS NOT NULL;

-- Coming Soon lens
CREATE INDEX mv_new_releases_upcoming_idx
    ON mv_new_releases(release_date ASC NULLS LAST)
    WHERE coming_soon = TRUE;

-- Just Added lens — steam_last_modified for coming_soon games only
CREATE INDEX mv_new_releases_added_idx
    ON mv_new_releases(steam_last_modified DESC)
    WHERE coming_soon = TRUE;

-- GIN indexes for genre/tag slug filtering (array operators use @>)
CREATE INDEX mv_new_releases_genre_slugs_gin
    ON mv_new_releases USING GIN(genre_slugs);

CREATE INDEX mv_new_releases_top_tag_slugs_gin
    ON mv_new_releases USING GIN(top_tag_slugs);
