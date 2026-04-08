-- depends: 0029_add_revenue_quartiles_to_price_positioning

-- Persist the estimator's machine-readable reason code for rows where no
-- numeric estimate could be produced (free_to_play, excluded_type,
-- insufficient_reviews, missing_price). Populated independently of the
-- owners/revenue/method columns; NULL when a numeric estimate succeeded.
ALTER TABLE games ADD COLUMN IF NOT EXISTS revenue_estimate_reason TEXT;
