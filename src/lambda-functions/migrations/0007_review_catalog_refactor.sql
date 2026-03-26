-- depends: 0006_add_analytics_indexes

-- Add completion timestamp (replaces empty-string sentinel and dead review_status lifecycle)
ALTER TABLE app_catalog ADD COLUMN IF NOT EXISTS reviews_completed_at TIMESTAMPTZ;

-- Fix existing empty-string sentinel rows: treat '' as complete,
-- use review_cursor_updated_at as a proxy for when the crawl finished.
UPDATE app_catalog
SET review_cursor        = NULL,
    reviews_completed_at = COALESCE(review_cursor_updated_at, NOW())
WHERE review_cursor = '';

-- Drop dead columns (review_status lifecycle was never wired up;
-- review_crawled_at was only ever set via set_review_status which was never called).
ALTER TABLE app_catalog DROP COLUMN IF EXISTS review_status;
ALTER TABLE app_catalog DROP COLUMN IF EXISTS review_crawled_at;
