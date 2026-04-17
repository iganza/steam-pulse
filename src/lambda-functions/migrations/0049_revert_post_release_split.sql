-- depends: 0048_split_ea_post_release_counts

-- Reverts 0048. The denormalized post-release split was never consumed by any
-- read path worth keeping (see PR #96 discussion) — remove it to eliminate the
-- ongoing ingest cost, matview coupling, and SQL-vs-Python breakpoint
-- duplication. The EA history signal is still available via the existing
-- `games.has_early_access_reviews` column and the `EarlyAccessImpact` endpoint.

-- Matviews that project the 0048 columns must be rebuilt before the columns
-- are dropped (Postgres won't let you DROP a column referenced by a view).

DROP MATERIALIZED VIEW IF EXISTS mv_discovery_feeds;
DROP MATERIALIZED VIEW IF EXISTS mv_genre_games;
DROP MATERIALIZED VIEW IF EXISTS mv_tag_games;

-- ---------------------------------------------------------------------------
-- mv_genre_games — pre-0048 shape (from 0028_add_revenue_to_game_matviews.sql)
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW mv_genre_games AS
SELECT
    gn.slug AS genre_slug,
    g.appid, g.name, g.slug, g.developer, g.header_image,
    g.review_count, g.review_count_english, g.positive_pct, g.review_score_desc,
    g.price_usd, g.is_free,
    g.release_date, g.deck_compatibility,
    g.hidden_gem_score, g.last_analyzed,
    g.estimated_owners, g.estimated_revenue_usd, g.revenue_estimate_method,
    EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS is_early_access
FROM games g
JOIN game_genres gg2 ON gg2.appid = g.appid
JOIN genres gn ON gg2.genre_id = gn.id;

CREATE UNIQUE INDEX idx_mv_genre_games_pk     ON mv_genre_games(genre_slug, appid);
CREATE INDEX idx_mv_genre_games_review        ON mv_genre_games(genre_slug, review_count DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_positive_pct  ON mv_genre_games(genre_slug, positive_pct DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_hidden_gem    ON mv_genre_games(genre_slug, hidden_gem_score DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_last_analyzed ON mv_genre_games(genre_slug, last_analyzed DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_revenue       ON mv_genre_games(genre_slug, estimated_revenue_usd DESC NULLS LAST);

-- ---------------------------------------------------------------------------
-- mv_tag_games — pre-0048 shape
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW mv_tag_games AS
SELECT
    t.slug AS tag_slug,
    g.appid, g.name, g.slug, g.developer, g.header_image,
    g.review_count, g.review_count_english, g.positive_pct, g.review_score_desc,
    g.price_usd, g.is_free,
    g.release_date, g.deck_compatibility,
    g.hidden_gem_score, g.last_analyzed,
    g.estimated_owners, g.estimated_revenue_usd, g.revenue_estimate_method,
    EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS is_early_access
FROM games g
JOIN game_tags gt ON gt.appid = g.appid
JOIN tags t ON gt.tag_id = t.id;

CREATE UNIQUE INDEX idx_mv_tag_games_pk     ON mv_tag_games(tag_slug, appid);
CREATE INDEX idx_mv_tag_games_review        ON mv_tag_games(tag_slug, review_count DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_positive_pct  ON mv_tag_games(tag_slug, positive_pct DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_hidden_gem    ON mv_tag_games(tag_slug, hidden_gem_score DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_last_analyzed ON mv_tag_games(tag_slug, last_analyzed DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_revenue       ON mv_tag_games(tag_slug, estimated_revenue_usd DESC NULLS LAST);

-- ---------------------------------------------------------------------------
-- mv_discovery_feeds — pre-0048 shape (from 0047_discovery_feeds_matview.sql)
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW mv_discovery_feeds AS
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

CREATE UNIQUE INDEX mv_discovery_feeds_pk_idx
    ON mv_discovery_feeds (feed_kind, rank);

-- Now safe to drop the 0048 columns.
ALTER TABLE games DROP COLUMN IF EXISTS review_count_post_release;
ALTER TABLE games DROP COLUMN IF EXISTS positive_count_post_release;
ALTER TABLE games DROP COLUMN IF EXISTS positive_pct_post_release;
ALTER TABLE games DROP COLUMN IF EXISTS review_score_desc_post_release;
