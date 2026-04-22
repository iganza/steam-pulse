-- depends: 0053_batch_executions_slug

-- Extend matview_refresh_log to track per-cycle status and per-view results.
-- The previous schema recorded a single `views_refreshed TEXT[]` row per full
-- success and nothing on partial progress. With the Step Functions + Map
-- fan-out, each cycle inserts a `running` row keyed by the SFN execution
-- name (cycle_id) and updates it to `complete` / `partial_failure` / `failed`
-- at Finalize with the per-view result breakdown.
--
-- Backfill-safe: existing rows have cycle_id=NULL, status=NULL and are
-- treated as "legacy, ignore" by the new debounce read.

ALTER TABLE matview_refresh_log
    ADD COLUMN IF NOT EXISTS cycle_id TEXT,
    ADD COLUMN IF NOT EXISTS status TEXT
        CHECK (status IN ('running', 'complete', 'partial_failure', 'failed')),
    ADD COLUMN IF NOT EXISTS per_view_results JSONB,
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS idx_matview_refresh_log_cycle_id
    ON matview_refresh_log(cycle_id) WHERE cycle_id IS NOT NULL;
