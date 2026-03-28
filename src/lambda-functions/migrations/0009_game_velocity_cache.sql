-- depends: 0008_drop_review_cursor_cols

ALTER TABLE games ADD COLUMN IF NOT EXISTS review_velocity_lifetime NUMERIC(10,2);
ALTER TABLE games ADD COLUMN IF NOT EXISTS last_velocity_computed_at TIMESTAMPTZ;
