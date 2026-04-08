-- depends: 0030_add_revenue_estimate_reason

ALTER TABLE games ADD COLUMN IF NOT EXISTS publisher_slug TEXT;

-- Backfill publisher_slug for existing rows using the same normalization as
-- library_layer.utils.slugify (lowercase, collapse non-alphanumerics to a
-- single dash, trim leading/trailing dashes). One intentional divergence:
-- when the result is the empty string (publisher was blank/punctuation-only)
-- we coerce to NULL via NULLIF instead of storing '' — a NULL slug is more
-- useful for filtering than an empty-string sentinel. Leaves rows with NULL
-- publisher untouched.
UPDATE games
SET publisher_slug = NULLIF(
    trim(BOTH '-' FROM regexp_replace(lower(publisher), '[^a-z0-9]+', '-', 'g')),
    ''
)
WHERE publisher_slug IS NULL AND publisher IS NOT NULL;
