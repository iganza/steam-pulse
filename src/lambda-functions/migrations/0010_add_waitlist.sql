-- depends: 0009_game_velocity_cache

CREATE TABLE IF NOT EXISTS waitlist (
    id          SERIAL PRIMARY KEY,
    email       TEXT UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
