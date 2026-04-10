-- depends: 0035_chunk_summaries

-- Phase 2 artifact storage for the three-phase LLM analysis pipeline.
-- Each row holds the MergedSummary output from consolidating chunk summaries.
-- `source_chunk_ids` always contains leaf chunk_summaries.id values —
-- threaded transitively at every merge level for stable cache-keying.
-- find_latest_by_source_ids() uses this to reuse a stored merge artifact
-- when the exact same set of primary chunks is re-merged.

CREATE TABLE IF NOT EXISTS merged_summaries (
    id               BIGSERIAL PRIMARY KEY,
    appid            INTEGER NOT NULL REFERENCES games(appid),
    merge_level      SMALLINT NOT NULL DEFAULT 1,
    summary_json     JSONB NOT NULL,
    source_chunk_ids BIGINT[] NOT NULL,
    chunks_merged    INTEGER NOT NULL,
    model_id         TEXT NOT NULL,
    prompt_version   TEXT NOT NULL,
    input_tokens     INTEGER,
    output_tokens    INTEGER,
    latency_ms       INTEGER,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_merged_summaries_appid ON merged_summaries(appid);

ALTER TABLE reports ADD COLUMN IF NOT EXISTS pipeline_version TEXT;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS chunk_count INTEGER;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS merged_summary_id BIGINT;
