-- depends: 0038_analysis_requests
--
-- Materialized view backing the /reports page "Available Reports" tab.
-- Pre-joins games with reports and denormalizes genre/tag arrays for
-- GIN-backed filtering. Follows the mv_new_releases pattern.

DROP MATERIALIZED VIEW IF EXISTS mv_catalog_reports;

CREATE MATERIALIZED VIEW mv_catalog_reports AS
SELECT
    g.appid,
    g.name,
    g.slug,
    g.developer,
    g.developer_slug,
    g.header_image,
    g.release_date,
    g.price_usd,
    COALESCE(g.is_free, FALSE) AS is_free,
    g.review_count,
    g.positive_pct,
    g.review_score_desc,
    g.hidden_gem_score,
    g.estimated_revenue_usd,
    r.last_analyzed,
    r.reviews_analyzed,
    -- Top 3 tag names (display)
    COALESCE((
        SELECT array_agg(tag_name ORDER BY votes DESC)
        FROM (
            SELECT t.name AS tag_name, gt.votes
            FROM game_tags gt JOIN tags t ON t.id = gt.tag_id
            WHERE gt.appid = g.appid
            ORDER BY gt.votes DESC LIMIT 3
        ) tt
    ), ARRAY[]::text[]) AS top_tags,
    -- Full tag slug list (filter)
    COALESCE((
        SELECT array_agg(t.slug)
        FROM game_tags gt JOIN tags t ON t.id = gt.tag_id
        WHERE gt.appid = g.appid
    ), ARRAY[]::text[]) AS tag_slugs,
    -- Genre names (display)
    COALESCE((
        SELECT array_agg(gn.name)
        FROM game_genres gg JOIN genres gn ON gn.id = gg.genre_id
        WHERE gg.appid = g.appid
    ), ARRAY[]::text[]) AS genres,
    -- Genre slugs (filter)
    COALESCE((
        SELECT array_agg(gn.slug)
        FROM game_genres gg JOIN genres gn ON gn.id = gg.genre_id
        WHERE gg.appid = g.appid
    ), ARRAY[]::text[]) AS genre_slugs
FROM games g
JOIN reports r ON r.appid = g.appid
WHERE g.type = 'game'
  AND r.is_public = TRUE;

-- Unique index required for REFRESH MATERIALIZED VIEW CONCURRENTLY.
CREATE UNIQUE INDEX mv_catalog_reports_pk ON mv_catalog_reports(appid);

CREATE INDEX mv_catalog_reports_last_analyzed_idx ON mv_catalog_reports(last_analyzed DESC);
CREATE INDEX mv_catalog_reports_review_count_idx ON mv_catalog_reports(review_count DESC);
CREATE INDEX mv_catalog_reports_hidden_gem_idx ON mv_catalog_reports(hidden_gem_score DESC NULLS LAST);
CREATE INDEX mv_catalog_reports_positive_pct_idx ON mv_catalog_reports(positive_pct DESC NULLS LAST);

-- GIN indexes so genre/tag-slug filtering is index-backed.
CREATE INDEX mv_catalog_reports_genre_slugs_gin ON mv_catalog_reports USING GIN (genre_slugs);
CREATE INDEX mv_catalog_reports_tag_slugs_gin ON mv_catalog_reports USING GIN (tag_slugs);
