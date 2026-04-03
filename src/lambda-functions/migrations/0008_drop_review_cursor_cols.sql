-- depends: 0007_review_catalog_refactor

-- Cursor and target now travel in SQS message bodies — no longer stored in DB.
-- reviews_completed_at is kept (business fact: when reviews were last fully fetched).
ALTER TABLE app_catalog DROP COLUMN IF EXISTS review_cursor;
ALTER TABLE app_catalog DROP COLUMN IF EXISTS review_cursor_updated_at;
ALTER TABLE app_catalog DROP COLUMN IF EXISTS reviews_target;
