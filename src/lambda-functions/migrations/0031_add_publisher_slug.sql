-- depends: 0030_add_revenue_estimate_reason

ALTER TABLE games ADD COLUMN IF NOT EXISTS publisher_slug TEXT;

-- Backfill publisher_slug for existing rows. Mirrors library_layer.utils.slugify:
-- lowercase, replace any run of non-alphanumeric chars with a single dash, and
-- trim leading/trailing dashes. Leaves rows with NULL publisher untouched.
UPDATE games
SET publisher_slug = NULLIF(
    trim(BOTH '-' FROM regexp_replace(lower(publisher), '[^a-z0-9]+', '-', 'g')),
    ''
)
WHERE publisher_slug IS NULL AND publisher IS NOT NULL;
