-- depends: 0046_denormalize_has_ea_reviews

-- Pre-computed top-N per feed kind for the homepage discovery rows.
-- Five feeds × 24 rows = ~120 rows total; refresh is effectively free.
--
-- This replaces five unfiltered `SELECT ... FROM games ORDER BY <col> LIMIT 8`
-- calls per homepage render, which were the slow path in GameRepository.list_games()
-- (no genre/tag filter → no matview fast path).
--
-- Registered in MATVIEW_NAMES (matview_repo.py); refresh Lambda picks it up
-- via the existing 6h EventBridge + SQS-triggered cadence.

DROP MATERIALIZED VIEW IF EXISTS mv_discovery_feeds;

CREATE MATERIALIZED VIEW mv_discovery_feeds AS
-- NOT MATERIALIZED so Postgres inlines `base` into each per-feed CTE. The
-- `popular`, `hidden_gem`, and `just_analyzed` feeds can then use the existing
-- idx_games_review_count / idx_games_hidden_gem_score / idx_games_last_analyzed
-- btree indexes to short-circuit the ORDER BY ... LIMIT 24 pick. The `top_rated`
-- and `new_release` feeds have no matching index on games(positive_pct) or
-- games(release_date), so they fall back to a seq-scan + top-N heap sort at
-- refresh time — acceptable because refresh runs at most every 5min debounce +
-- 6h EventBridge cadence, not per request.
WITH base AS NOT MATERIALIZED (
    SELECT
        g.appid,
        g.name,
        g.slug,
        g.developer,
        g.header_image,
        g.review_count,
        g.review_count_english,
        g.positive_pct,
        g.review_score_desc,
        g.price_usd,
        g.is_free,
        g.release_date,
        g.deck_compatibility,
        g.hidden_gem_score,
        g.last_analyzed,
        g.estimated_owners,
        g.estimated_revenue_usd,
        g.revenue_estimate_method,
        g.coming_soon,
        EXISTS (
            SELECT 1 FROM game_genres gg
            WHERE gg.appid = g.appid AND gg.genre_id = 70
        ) AS is_early_access
    FROM games g
    WHERE g.type IS NULL OR g.type = 'game'
),
popular AS (
    SELECT 'popular'::text AS feed_kind,
           ROW_NUMBER() OVER (ORDER BY review_count DESC NULLS LAST, appid) AS rank,
           base.*
    FROM base
    WHERE review_count IS NOT NULL
    ORDER BY review_count DESC NULLS LAST, appid
    LIMIT 24
),
top_rated AS (
    SELECT 'top_rated'::text AS feed_kind,
           ROW_NUMBER() OVER (ORDER BY positive_pct DESC NULLS LAST, review_count DESC NULLS LAST, appid) AS rank,
           base.*
    FROM base
    WHERE review_count >= 200 AND positive_pct IS NOT NULL
    ORDER BY positive_pct DESC NULLS LAST, review_count DESC NULLS LAST, appid
    LIMIT 24
),
hidden_gem AS (
    SELECT 'hidden_gem'::text AS feed_kind,
           ROW_NUMBER() OVER (ORDER BY hidden_gem_score DESC NULLS LAST, appid) AS rank,
           base.*
    FROM base
    WHERE hidden_gem_score IS NOT NULL
    ORDER BY hidden_gem_score DESC NULLS LAST, appid
    LIMIT 24
),
new_release AS (
    SELECT 'new_release'::text AS feed_kind,
           ROW_NUMBER() OVER (ORDER BY release_date DESC NULLS LAST, appid) AS rank,
           base.*
    FROM base
    WHERE release_date IS NOT NULL
      AND COALESCE(coming_soon, FALSE) = FALSE
    ORDER BY release_date DESC NULLS LAST, appid
    LIMIT 24
),
just_analyzed AS (
    SELECT 'just_analyzed'::text AS feed_kind,
           ROW_NUMBER() OVER (ORDER BY last_analyzed DESC NULLS LAST, appid) AS rank,
           base.*
    FROM base
    WHERE last_analyzed IS NOT NULL
    ORDER BY last_analyzed DESC NULLS LAST, appid
    LIMIT 24
)
SELECT feed_kind, rank,
       appid, name, slug, developer, header_image,
       review_count, review_count_english, positive_pct, review_score_desc,
       price_usd, is_free,
       release_date, deck_compatibility,
       hidden_gem_score, last_analyzed,
       estimated_owners, estimated_revenue_usd, revenue_estimate_method,
       is_early_access
FROM popular
UNION ALL
SELECT feed_kind, rank,
       appid, name, slug, developer, header_image,
       review_count, review_count_english, positive_pct, review_score_desc,
       price_usd, is_free,
       release_date, deck_compatibility,
       hidden_gem_score, last_analyzed,
       estimated_owners, estimated_revenue_usd, revenue_estimate_method,
       is_early_access
FROM top_rated
UNION ALL
SELECT feed_kind, rank,
       appid, name, slug, developer, header_image,
       review_count, review_count_english, positive_pct, review_score_desc,
       price_usd, is_free,
       release_date, deck_compatibility,
       hidden_gem_score, last_analyzed,
       estimated_owners, estimated_revenue_usd, revenue_estimate_method,
       is_early_access
FROM hidden_gem
UNION ALL
SELECT feed_kind, rank,
       appid, name, slug, developer, header_image,
       review_count, review_count_english, positive_pct, review_score_desc,
       price_usd, is_free,
       release_date, deck_compatibility,
       hidden_gem_score, last_analyzed,
       estimated_owners, estimated_revenue_usd, revenue_estimate_method,
       is_early_access
FROM new_release
UNION ALL
SELECT feed_kind, rank,
       appid, name, slug, developer, header_image,
       review_count, review_count_english, positive_pct, review_score_desc,
       price_usd, is_free,
       release_date, deck_compatibility,
       hidden_gem_score, last_analyzed,
       estimated_owners, estimated_revenue_usd, revenue_estimate_method,
       is_early_access
FROM just_analyzed;

-- Unique index required for REFRESH MATERIALIZED VIEW CONCURRENTLY.
-- Also satisfies the canonical read path: WHERE feed_kind = %s ORDER BY rank LIMIT N.
CREATE UNIQUE INDEX mv_discovery_feeds_pk_idx
    ON mv_discovery_feeds (feed_kind, rank);
