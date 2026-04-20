-- depends: 0032_index_publisher_slug
-- transactional: false

-- Partial index supporting CatalogRepository.find_due_meta() (originally
-- created for the superseded find_stale_meta — same scan shape).
-- Only rows with meta_status='done' are ever considered for refresh, so a
-- partial index keeps the B-tree small and the tier-refresh scan efficient on
-- 160k+ catalog rows. CONCURRENTLY avoids write-blocking locks — required for
-- this reason the migration is marked non-transactional.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_catalog_stale_meta
    ON app_catalog (meta_crawled_at)
    WHERE meta_status = 'done';
