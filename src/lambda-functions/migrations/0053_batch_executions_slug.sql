-- depends: 0052_genre_editorial_columns

-- Allow batch_executions to track slug-keyed batches (Phase 4 genre
-- synthesis) alongside appid-keyed ones (Phase 1-3). Exactly one of
-- (appid, slug) must be set per row — enforced by a CHECK constraint.
--
-- Written idempotently so partial-apply retries and reruns succeed:
--   - ALTER COLUMN DROP NOT NULL is naturally idempotent.
--   - ADD COLUMN uses IF NOT EXISTS.
--   - The CHECK constraint is wrapped in a pg_constraint existence guard.

ALTER TABLE batch_executions
    ALTER COLUMN appid DROP NOT NULL;

ALTER TABLE batch_executions
    ADD COLUMN IF NOT EXISTS slug TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'batch_executions_subject_check'
          AND conrelid = 'batch_executions'::regclass
    ) THEN
        ALTER TABLE batch_executions
            ADD CONSTRAINT batch_executions_subject_check
            CHECK ((appid IS NOT NULL) <> (slug IS NOT NULL));
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_batch_exec_slug ON batch_executions(slug);
