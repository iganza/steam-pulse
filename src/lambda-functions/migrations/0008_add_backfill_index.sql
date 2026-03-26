-- depends: 0007_review_catalog_refactor
-- transactional: false

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_app_catalog_backfill
    ON app_catalog (appid)
    WHERE meta_status = 'done'
      AND review_cursor IS NULL
      AND reviews_completed_at IS NULL;
