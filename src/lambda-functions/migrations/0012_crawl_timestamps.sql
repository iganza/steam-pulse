-- depends: 0011_steamspy_data

ALTER TABLE app_catalog ADD COLUMN IF NOT EXISTS tags_crawled_at   TIMESTAMPTZ;
ALTER TABLE app_catalog ADD COLUMN IF NOT EXISTS review_crawled_at TIMESTAMPTZ;
