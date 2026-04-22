-- depends: 0053_batch_executions_slug

-- Per-cycle status + per-view results for the SFN-driven matview refresh.
-- Legacy rows (cycle_id IS NULL) are ignored by the new debounce read.

ALTER TABLE matview_refresh_log
    ADD COLUMN IF NOT EXISTS cycle_id TEXT,
    ADD COLUMN IF NOT EXISTS status TEXT
        CHECK (status IN ('running', 'complete', 'partial_failure', 'failed')),
    ADD COLUMN IF NOT EXISTS per_view_results JSONB,
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS idx_matview_refresh_log_cycle_id
    ON matview_refresh_log(cycle_id) WHERE cycle_id IS NOT NULL;
