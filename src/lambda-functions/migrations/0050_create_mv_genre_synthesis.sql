-- depends: 0049_revert_post_release_split

-- Phase-4 cross-genre synthesis artifact. Populated by the genre_synthesis
-- Lambda (one LLM pass per genre, weekly). Named `mv_*` to align with the
-- matview vocabulary in ARCHITECTURE.org, but implemented as a regular
-- table because Postgres MATERIALIZED VIEW cannot invoke an LLM.
--
-- The API reads one row: SELECT * FROM mv_genre_synthesis WHERE slug = $1.
-- `input_hash = sha256(prompt_version || sorted_appids)` is the cache key:
-- re-running with the same inputs is a no-op short-circuit in the service.

CREATE TABLE IF NOT EXISTS mv_genre_synthesis (
    slug                TEXT PRIMARY KEY,
    display_name        TEXT NOT NULL,
    input_appids        INTEGER[] NOT NULL,
    input_count         INTEGER NOT NULL,
    prompt_version      TEXT NOT NULL,
    input_hash          TEXT NOT NULL,
    synthesis           JSONB NOT NULL,
    narrative_summary   TEXT NOT NULL,
    avg_positive_pct    NUMERIC NOT NULL,
    median_review_count INTEGER NOT NULL,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS mv_genre_synthesis_input_hash_idx
    ON mv_genre_synthesis(input_hash);

CREATE INDEX IF NOT EXISTS mv_genre_synthesis_computed_at_idx
    ON mv_genre_synthesis(computed_at);
