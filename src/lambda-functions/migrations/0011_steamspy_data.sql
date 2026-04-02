-- depends: 0010_add_waitlist

-- New table for SteamSpy enrichment data.
-- One row per appid, upserted on each backfill/crawl.
CREATE TABLE IF NOT EXISTS steamspy_data (
    appid             INTEGER PRIMARY KEY REFERENCES games(appid),
    score_rank        TEXT,
    positive          INTEGER,
    negative          INTEGER,
    userscore         INTEGER,
    owners            TEXT,            -- range string: "2,000,000 .. 5,000,000"
    average_forever   INTEGER,         -- minutes
    average_2weeks    INTEGER,         -- minutes
    median_forever    INTEGER,         -- minutes
    median_2weeks     INTEGER,         -- minutes
    price             INTEGER,         -- cents (current)
    initialprice      INTEGER,         -- cents (original)
    discount          INTEGER,         -- percentage
    ccu               INTEGER,         -- peak concurrent users
    languages         TEXT,
    upserted_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Remove category-polluted data from tags table.
-- Tags will be repopulated by SteamSpy backfill.
-- game_categories table is unaffected.
TRUNCATE game_tags;
DELETE FROM tags;
