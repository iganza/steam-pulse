-- depends: 0025_add_trend_matview_indexes

-- Boxleiter v1 revenue estimates denormalized on games so we can sort/filter
-- by estimated revenue in /api/games, price positioning, and the Compare lens
-- without expensive JSON lookups. The method is versioned via
-- `revenue_estimate_method` so v2 rolls out as a pure backfill — no schema
-- churn needed when the algorithm changes.

ALTER TABLE games ADD COLUMN IF NOT EXISTS estimated_owners BIGINT;
ALTER TABLE games ADD COLUMN IF NOT EXISTS estimated_revenue_usd NUMERIC(14,2);
ALTER TABLE games ADD COLUMN IF NOT EXISTS revenue_estimate_method TEXT;
ALTER TABLE games ADD COLUMN IF NOT EXISTS revenue_estimate_computed_at TIMESTAMPTZ;
