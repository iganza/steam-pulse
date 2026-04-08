-- depends: 0031_add_publisher_slug
-- transactional: false

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_games_publisher_slug ON games(publisher_slug) WHERE publisher_slug IS NOT NULL;
