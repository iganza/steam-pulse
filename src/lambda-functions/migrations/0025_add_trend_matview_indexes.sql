-- depends: 0024_add_trend_matviews
-- transactional: false

-- Unique indexes on the trend matviews so REFRESH MATERIALIZED VIEW CONCURRENTLY
-- can be used. CONCURRENTLY requires running outside a transaction, hence
-- `-- transactional: false`.

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_mv_trend_catalog_pk
    ON mv_trend_catalog (granularity, period);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_mv_trend_by_genre_pk
    ON mv_trend_by_genre (granularity, genre_slug, period);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_mv_trend_by_tag_pk
    ON mv_trend_by_tag (granularity, tag_slug, period);
