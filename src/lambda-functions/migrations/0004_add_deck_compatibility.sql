-- depends: 0003_add_review_language_and_votes

ALTER TABLE games ADD COLUMN IF NOT EXISTS deck_compatibility INTEGER;
ALTER TABLE games ADD COLUMN IF NOT EXISTS deck_test_results JSONB;
