-- depends: 0026_add_revenue_estimates
-- transactional: false

-- CONCURRENTLY requires running outside a transaction, hence
-- `-- transactional: false`.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_games_estimated_revenue
    ON games(estimated_revenue_usd DESC NULLS LAST);
