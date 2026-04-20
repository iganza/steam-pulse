-- depends: 0050_create_mv_genre_synthesis
-- transactional: false

-- Accelerate catalog search (/api/games?q=…). Current query does
-- g.name ILIKE '%term%' on an unindexed column, forcing a seq scan
-- over ~100k rows on every search. Trigram GIN converts that to an
-- index scan and also speeds the ILIKE 'term%' prefix boost used
-- in ORDER BY.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_games_name_trgm
    ON games USING GIN (name gin_trgm_ops);
