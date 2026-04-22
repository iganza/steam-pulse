-- depends: 0051_games_name_trgm_index

-- Editorial columns layered on top of the Phase-4 synthesizer output.
-- Operator-populated at curation time via scripts/ops/update_editorial.py;
-- the weekly synthesizer refresh does NOT touch these columns. Empty
-- string = "not yet curated"; the /genre/[slug]/ page falls back to
-- narrative_summary for the intro and hides the churn interpretation
-- line when blank.
ALTER TABLE mv_genre_synthesis
    ADD COLUMN IF NOT EXISTS editorial_intro TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS churn_interpretation TEXT NOT NULL DEFAULT '';
