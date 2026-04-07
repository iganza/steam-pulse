-- depends: 0020_price_summary_matview

-- Drop the denormalized AI-computed sentiment_score from games. Steam's
-- positive_pct is now the only sentiment number — see scripts/prompts/data-source-clarity.md.
--
-- mv_genre_games and mv_tag_games (created in 0020) reference g.sentiment_score
-- directly, so they must be dropped first, then recreated against positive_pct.

DROP MATERIALIZED VIEW IF EXISTS mv_genre_games;
DROP MATERIALIZED VIEW IF EXISTS mv_tag_games;

DROP INDEX IF EXISTS idx_games_sentiment_score;
ALTER TABLE games DROP COLUMN IF EXISTS sentiment_score;

-- Recreate mv_genre_games / mv_tag_games using positive_pct.
-- Also exposes review_score_desc so callers can render Steam's sentiment label
-- without joining back to games.
CREATE MATERIALIZED VIEW mv_genre_games AS
SELECT
    gn.slug AS genre_slug,
    g.appid, g.name, g.slug, g.developer, g.header_image,
    g.review_count, g.review_count_english, g.positive_pct, g.review_score_desc,
    g.price_usd, g.is_free,
    g.release_date, g.deck_compatibility,
    g.hidden_gem_score, g.last_analyzed,
    EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS is_early_access
FROM games g
JOIN game_genres gg2 ON gg2.appid = g.appid
JOIN genres gn ON gg2.genre_id = gn.id;

CREATE UNIQUE INDEX idx_mv_genre_games_pk ON mv_genre_games(genre_slug, appid);
CREATE INDEX idx_mv_genre_games_review ON mv_genre_games(genre_slug, review_count DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_positive_pct ON mv_genre_games(genre_slug, positive_pct DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_hidden_gem ON mv_genre_games(genre_slug, hidden_gem_score DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_last_analyzed ON mv_genre_games(genre_slug, last_analyzed DESC NULLS LAST);

CREATE MATERIALIZED VIEW mv_tag_games AS
SELECT
    t.slug AS tag_slug,
    g.appid, g.name, g.slug, g.developer, g.header_image,
    g.review_count, g.review_count_english, g.positive_pct, g.review_score_desc,
    g.price_usd, g.is_free,
    g.release_date, g.deck_compatibility,
    g.hidden_gem_score, g.last_analyzed,
    EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS is_early_access
FROM games g
JOIN game_tags gt ON gt.appid = g.appid
JOIN tags t ON gt.tag_id = t.id;

CREATE UNIQUE INDEX idx_mv_tag_games_pk ON mv_tag_games(tag_slug, appid);
CREATE INDEX idx_mv_tag_games_review ON mv_tag_games(tag_slug, review_count DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_positive_pct ON mv_tag_games(tag_slug, positive_pct DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_hidden_gem ON mv_tag_games(tag_slug, hidden_gem_score DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_last_analyzed ON mv_tag_games(tag_slug, last_analyzed DESC NULLS LAST);
