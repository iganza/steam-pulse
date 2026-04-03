-- depends: 0012_crawl_timestamps

ALTER TABLE tags ADD COLUMN IF NOT EXISTS steam_tag_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_tags_steam_tag_id ON tags(steam_tag_id);
