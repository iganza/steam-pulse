-- depends: 0027_add_revenue_estimate_index

-- Recreate mv_genre_games and mv_tag_games to include Boxleiter revenue
-- estimate columns. The /api/games list path reads from these matviews
-- for simple genre/tag browsing and needs to surface estimated_owners /
-- estimated_revenue_usd / revenue_estimate_method per row.

DROP MATERIALIZED VIEW IF EXISTS mv_genre_games;
DROP MATERIALIZED VIEW IF EXISTS mv_tag_games;

CREATE MATERIALIZED VIEW mv_genre_games AS
SELECT
    gn.slug AS genre_slug,
    g.appid, g.name, g.slug, g.developer, g.header_image,
    g.review_count, g.review_count_english, g.positive_pct, g.review_score_desc,
    g.price_usd, g.is_free,
    g.release_date, g.deck_compatibility,
    g.hidden_gem_score, g.last_analyzed,
    g.estimated_owners, g.estimated_revenue_usd, g.revenue_estimate_method,
    EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS is_early_access
FROM games g
JOIN game_genres gg2 ON gg2.appid = g.appid
JOIN genres gn ON gg2.genre_id = gn.id;

CREATE UNIQUE INDEX idx_mv_genre_games_pk ON mv_genre_games(genre_slug, appid);
CREATE INDEX idx_mv_genre_games_review ON mv_genre_games(genre_slug, review_count DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_positive_pct ON mv_genre_games(genre_slug, positive_pct DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_hidden_gem ON mv_genre_games(genre_slug, hidden_gem_score DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_last_analyzed ON mv_genre_games(genre_slug, last_analyzed DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_revenue ON mv_genre_games(genre_slug, estimated_revenue_usd DESC NULLS LAST);

CREATE MATERIALIZED VIEW mv_tag_games AS
SELECT
    t.slug AS tag_slug,
    g.appid, g.name, g.slug, g.developer, g.header_image,
    g.review_count, g.review_count_english, g.positive_pct, g.review_score_desc,
    g.price_usd, g.is_free,
    g.release_date, g.deck_compatibility,
    g.hidden_gem_score, g.last_analyzed,
    g.estimated_owners, g.estimated_revenue_usd, g.revenue_estimate_method,
    EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS is_early_access
FROM games g
JOIN game_tags gt ON gt.appid = g.appid
JOIN tags t ON gt.tag_id = t.id;

CREATE UNIQUE INDEX idx_mv_tag_games_pk ON mv_tag_games(tag_slug, appid);
CREATE INDEX idx_mv_tag_games_review ON mv_tag_games(tag_slug, review_count DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_positive_pct ON mv_tag_games(tag_slug, positive_pct DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_hidden_gem ON mv_tag_games(tag_slug, hidden_gem_score DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_last_analyzed ON mv_tag_games(tag_slug, last_analyzed DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_revenue ON mv_tag_games(tag_slug, estimated_revenue_usd DESC NULLS LAST);
