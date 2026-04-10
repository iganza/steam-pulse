-- depends: 0037_analysis_candidates

CREATE TABLE IF NOT EXISTS analysis_requests (
    id         BIGSERIAL PRIMARY KEY,
    appid      INTEGER NOT NULL,
    email      TEXT NOT NULL,
    user_id    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (appid, email)
);

CREATE INDEX IF NOT EXISTS idx_analysis_requests_appid
    ON analysis_requests (appid);
