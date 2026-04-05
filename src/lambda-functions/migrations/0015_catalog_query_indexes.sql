-- depends: 0014_add_tag_category
-- transactional: false

-- Covering indexes for EXISTS subqueries in list_games() genre/tag filters.
-- Composite (filter_col, join_col) enables index-only scans on the junction tables.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_game_genres_genre_appid
    ON game_genres(genre_id, appid);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_game_tags_tag_appid
    ON game_tags(tag_id, appid);

-- Slug lookups for genre/tag filter JOINs inside EXISTS.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_genres_slug
    ON genres(slug);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tags_slug
    ON tags(slug);

-- Default sort order for catalog browse (review_count DESC).
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_games_review_count
    ON games(review_count DESC NULLS LAST);
