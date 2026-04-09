-- depends: 0034_new_releases_matview

-- Phase 1 artifact storage for the three-phase LLM analysis pipeline
-- (chunk → merge → synthesize). Each row holds the structured TopicSignal
-- output for a single 50-review chunk, keyed by a deterministic
-- `chunk_hash` so Phase 1 is idempotent: re-running the analyzer with the
-- same reviews and same prompt version reuses cached rows instead of
-- re-tokenising. Bumping CHUNK_PROMPT_VERSION in analyzer.py invalidates
-- the cache naturally because `prompt_version` is part of the unique key.

CREATE TABLE IF NOT EXISTS chunk_summaries (
    id              BIGSERIAL PRIMARY KEY,
    appid           INTEGER NOT NULL REFERENCES games(appid),
    chunk_index     SMALLINT NOT NULL,
    chunk_hash      TEXT NOT NULL,
    review_count    SMALLINT NOT NULL,
    summary_json    JSONB NOT NULL,
    model_id        TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (appid, chunk_hash, prompt_version)
);

CREATE INDEX IF NOT EXISTS idx_chunk_summaries_appid ON chunk_summaries(appid);
