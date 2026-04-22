-- depends: 0052_genre_editorial_columns

-- Allow batch_executions to track slug-keyed batches (Phase 4 genre
-- synthesis) alongside appid-keyed ones (Phase 1-3). Exactly one of
-- (appid, slug) must be set per row — enforced by a CHECK constraint.

ALTER TABLE batch_executions
    ALTER COLUMN appid DROP NOT NULL,
    ADD COLUMN slug TEXT;

ALTER TABLE batch_executions
    ADD CONSTRAINT batch_executions_subject_check
    CHECK ((appid IS NOT NULL) <> (slug IS NOT NULL));

CREATE INDEX IF NOT EXISTS idx_batch_exec_slug ON batch_executions(slug);
