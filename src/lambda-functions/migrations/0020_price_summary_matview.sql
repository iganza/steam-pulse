-- depends: 0019_genre_tag_game_matviews

-- Recreate mv_genre_games and mv_tag_games to include last_analyzed column
-- (added to games table in migration 0017 but missing from the original matview definition).
DROP MATERIALIZED VIEW IF EXISTS mv_genre_games;
DROP MATERIALIZED VIEW IF EXISTS mv_tag_games;

CREATE MATERIALIZED VIEW mv_genre_games AS
SELECT
    gn.slug AS genre_slug,
    g.appid, g.name, g.slug, g.developer, g.header_image,
    g.review_count, g.review_count_english, g.positive_pct, g.price_usd, g.is_free,
    g.release_date, g.deck_compatibility,
    g.hidden_gem_score, g.sentiment_score, g.last_analyzed,
    EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS is_early_access
FROM games g
JOIN game_genres gg2 ON gg2.appid = g.appid
JOIN genres gn ON gg2.genre_id = gn.id;

CREATE UNIQUE INDEX idx_mv_genre_games_pk ON mv_genre_games(genre_slug, appid);
CREATE INDEX idx_mv_genre_games_review ON mv_genre_games(genre_slug, review_count DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_sentiment ON mv_genre_games(genre_slug, sentiment_score DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_hidden_gem ON mv_genre_games(genre_slug, hidden_gem_score DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_last_analyzed ON mv_genre_games(genre_slug, last_analyzed DESC NULLS LAST);

CREATE MATERIALIZED VIEW mv_tag_games AS
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

CREATE UNIQUE INDEX idx_mv_tag_games_pk ON mv_tag_games(tag_slug, appid);
CREATE INDEX idx_mv_tag_games_review ON mv_tag_games(tag_slug, review_count DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_sentiment ON mv_tag_games(tag_slug, sentiment_score DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_hidden_gem ON mv_tag_games(tag_slug, hidden_gem_score DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_last_analyzed ON mv_tag_games(tag_slug, last_analyzed DESC NULLS LAST);

-- Pre-computed price summary stats per genre.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_price_summary AS
SELECT
    gn.slug AS genre_slug,
    ROUND(AVG(g.price_usd) FILTER (WHERE NOT g.is_free), 2) AS avg_price,
    ROUND(
        (PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY g.price_usd)
         FILTER (WHERE NOT g.is_free))::numeric,
        2
    ) AS median_price,
    COUNT(*) FILTER (WHERE g.is_free) AS free_count,
    COUNT(*) FILTER (WHERE NOT g.is_free) AS paid_count
FROM games g
JOIN game_genres gg ON gg.appid = g.appid
JOIN genres gn ON gg.genre_id = gn.id
WHERE g.review_count >= 10
GROUP BY gn.slug;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_price_summary_pk
    ON mv_price_summary(genre_slug);
