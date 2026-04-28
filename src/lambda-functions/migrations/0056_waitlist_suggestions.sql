-- depends: 0055_review_count_at_last_fetch

CREATE TABLE IF NOT EXISTS waitlist_suggestions (
    id          SERIAL PRIMARY KEY,
    email       TEXT NOT NULL,
    suggestion  TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
