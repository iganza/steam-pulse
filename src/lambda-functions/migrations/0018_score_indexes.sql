-- depends: 0017_denormalize_scores
-- transactional: false

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_games_sentiment_score
    ON games(sentiment_score DESC NULLS LAST);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_games_hidden_gem_score
    ON games(hidden_gem_score DESC NULLS LAST);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_games_last_analyzed
    ON games(last_analyzed DESC NULLS LAST);
