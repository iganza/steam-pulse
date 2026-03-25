-- depends: 0004_add_deck_compatibility

ALTER TABLE app_catalog ADD COLUMN IF NOT EXISTS review_cursor TEXT;
ALTER TABLE app_catalog ADD COLUMN IF NOT EXISTS review_cursor_updated_at TIMESTAMPTZ;
ALTER TABLE app_catalog ADD COLUMN IF NOT EXISTS reviews_target INT;
