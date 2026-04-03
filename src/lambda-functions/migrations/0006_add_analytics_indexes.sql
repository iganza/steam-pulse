-- depends: 0005_add_review_cursor
-- transactional: false

-- CONCURRENTLY avoids write-blocking locks on reviews/games during index builds.
-- Postgres requires CONCURRENTLY to run outside a transaction; the non-transactional
-- header above tells yoyo not to wrap these statements in BEGIN/COMMIT.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_reviews_author_appid ON reviews(appid, author_steamid) WHERE author_steamid IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_reviews_appid_playtime ON reviews(appid, playtime_hours, voted_up);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_reviews_appid_ea ON reviews(appid, written_during_early_access, voted_up);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_reviews_appid_helpful ON reviews(appid, votes_helpful DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_reviews_appid_funny ON reviews(appid, votes_funny DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_reviews_appid_posted ON reviews(appid, posted_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_games_developer_slug ON games(developer_slug) WHERE developer_slug IS NOT NULL;
