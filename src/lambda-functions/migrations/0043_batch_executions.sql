-- depends: 0042_mv_new_releases_v2

-- Operational tracking table for batch LLM API calls. One row per
-- Anthropic/Bedrock batch submission (per game, per phase). Provides
-- structured visibility into what's running, what completed, how long
-- it took, and what it cost — without digging through Step Functions
-- console or CloudWatch logs.

CREATE TABLE IF NOT EXISTS batch_executions (
    id                  BIGSERIAL PRIMARY KEY,
    execution_id        TEXT NOT NULL,
    appid               INTEGER NOT NULL REFERENCES games(appid),
    phase               TEXT NOT NULL,
    backend             TEXT NOT NULL,

    batch_id            TEXT NOT NULL UNIQUE,
    model_id            TEXT NOT NULL,

    status              TEXT NOT NULL DEFAULT 'submitted',
    submitted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    duration_ms         INTEGER,

    request_count       INTEGER NOT NULL,
    succeeded_count     INTEGER,
    failed_count        INTEGER,

    input_tokens        INTEGER,
    output_tokens       INTEGER,
    cache_read_tokens   INTEGER,
    cache_write_tokens  INTEGER,

    estimated_cost_usd  NUMERIC(8, 4),

    failure_reason      TEXT,
    failed_record_ids   TEXT[],

    pipeline_version    TEXT,
    prompt_version      TEXT
);

CREATE INDEX IF NOT EXISTS idx_batch_exec_execution_id ON batch_executions(execution_id);
CREATE INDEX IF NOT EXISTS idx_batch_exec_appid ON batch_executions(appid);
CREATE INDEX IF NOT EXISTS idx_batch_exec_status ON batch_executions(status);
CREATE INDEX IF NOT EXISTS idx_batch_exec_submitted ON batch_executions(submitted_at DESC);
