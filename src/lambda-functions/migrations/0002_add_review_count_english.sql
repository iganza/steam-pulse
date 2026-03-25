-- depends: 0001_initial_schema

ALTER TABLE games ADD COLUMN IF NOT EXISTS review_count_english INTEGER;
