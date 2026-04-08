-- depends: 0032_index_publisher_slug
-- transactional: false

-- Partial index supporting CatalogRepository.find_stale_meta().
-- Only rows with meta_status='done' are ever considered for staleness, so a
-- partial index keeps the B-tree small and the staleness scan efficient on
-- 160k+ catalog rows. CONCURRENTLY avoids write-blocking locks — required for
-- this reason the migration is marked non-transactional.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_catalog_stale_meta
    ON app_catalog (meta_crawled_at)
    WHERE meta_status = 'done';
