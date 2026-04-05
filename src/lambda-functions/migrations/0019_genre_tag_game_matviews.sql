-- depends: 0018_score_indexes

-- Pre-joined genre+games and tag+games materialized views for fast catalog browsing.
-- Eliminates nested-loop joins on cold cache by pre-materializing the genre/tag filter.

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_genre_games AS
SELECT
    gn.slug AS genre_slug,
    g.appid, g.name, g.slug, g.developer, g.header_image,
    g.review_count, g.review_count_english, g.positive_pct, g.price_usd, g.is_free,
    g.release_date, g.deck_compatibility,
    g.hidden_gem_score, g.sentiment_score, g.last_analyzed,
    EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS is_early_access
FROM games g
JOIN game_genres gg ON gg.appid = g.appid
JOIN genres gn ON gg.genre_id = gn.id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_genre_games_pk
    ON mv_genre_games(genre_slug, appid);
CREATE INDEX IF NOT EXISTS idx_mv_genre_games_review
    ON mv_genre_games(genre_slug, review_count DESC NULLS LAST);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_tag_games AS
SELECT
    t.slug AS tag_slug,
    g.appid, g.name, g.slug, g.developer, g.header_image,
    g.review_count, g.review_count_english, g.positive_pct, g.price_usd, g.is_free,
    g.release_date, g.deck_compatibility,
    g.hidden_gem_score, g.sentiment_score, g.last_analyzed,
    EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS is_early_access
FROM games g
JOIN game_tags gt ON gt.appid = g.appid
JOIN tags t ON gt.tag_id = t.id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_tag_games_pk
    ON mv_tag_games(tag_slug, appid);
CREATE INDEX IF NOT EXISTS idx_mv_tag_games_review
    ON mv_tag_games(tag_slug, review_count DESC NULLS LAST);
