-- depends: 0047_discovery_feeds_matview

-- Denormalize post-release review counts + sentiment onto games so the read path
-- can surface Steam-store-consistent numbers for ex-EA games without scanning
-- reviews at query time.
--
-- English-only, mirroring the existing implicit-English convention on
-- positive_pct / review_score_desc / total_positive / total_negative. Rows in
-- `reviews` are English-only by construction (steam_source.get_reviews passes
-- language="english").
--
-- NOT NULL DEFAULT 0 / '' — "no post-release reviews yet" and "genuinely 0" are
-- observationally identical and the display helper gates on count > 0 anyway.

ALTER TABLE games ADD COLUMN IF NOT EXISTS review_count_post_release     INTEGER NOT NULL DEFAULT 0;
ALTER TABLE games ADD COLUMN IF NOT EXISTS positive_count_post_release   INTEGER NOT NULL DEFAULT 0;
ALTER TABLE games ADD COLUMN IF NOT EXISTS positive_pct_post_release     INTEGER NOT NULL DEFAULT 0;
ALTER TABLE games ADD COLUMN IF NOT EXISTS review_score_desc_post_release TEXT    NOT NULL DEFAULT '';

-- Bulk backfill of counts + pct + label directly from the reviews table.
-- Label encodes Steam's published breakpoints as a SQL CASE so every game gets
-- a meaningful value immediately — there's no "wait for recrawl" window where
-- post-release labels are empty. The Python steam_review_label() helper in
-- crawl_service keeps the two paths in sync for subsequent ingests (both
-- paths must agree on the 0048 breakpoints).
WITH agg AS (
    SELECT
        appid,
        COUNT(*) FILTER (WHERE written_during_early_access = FALSE) AS post_count,
        COUNT(*) FILTER (WHERE written_during_early_access = FALSE AND voted_up = TRUE) AS post_positive,
        CASE
            WHEN COUNT(*) FILTER (WHERE written_during_early_access = FALSE) > 0
            THEN ROUND(
                100.0 * COUNT(*) FILTER (WHERE written_during_early_access = FALSE AND voted_up = TRUE)
                / COUNT(*) FILTER (WHERE written_during_early_access = FALSE)
            )::INTEGER
            ELSE 0
        END AS post_pct
    FROM reviews
    GROUP BY appid
)
UPDATE games g
SET review_count_post_release   = agg.post_count,
    positive_count_post_release = agg.post_positive,
    positive_pct_post_release   = agg.post_pct,
    review_score_desc_post_release = CASE
        WHEN agg.post_count <= 0 THEN ''
        WHEN agg.post_pct >= 95 AND agg.post_count >= 500 THEN 'Overwhelmingly Positive'
        WHEN agg.post_pct >= 80 AND agg.post_count >= 50  THEN 'Very Positive'
        WHEN agg.post_pct >= 80                           THEN 'Positive'
        WHEN agg.post_pct >= 70                           THEN 'Mostly Positive'
        WHEN agg.post_pct >= 40                           THEN 'Mixed'
        WHEN agg.post_pct < 20  AND agg.post_count >= 500 THEN 'Overwhelmingly Negative'
        WHEN agg.post_pct < 20  AND agg.post_count >= 50  THEN 'Very Negative'
        WHEN agg.post_pct < 20                            THEN 'Negative'
        ELSE 'Mostly Negative'
    END
FROM agg
WHERE g.appid = agg.appid;

-- ---------------------------------------------------------------------------
-- Rebuild per-game matviews to project the new columns.
-- Trend matviews (mv_trend_catalog/by_genre/by_tag) are analytics aggregates and
-- do not expose per-game columns — they're untouched here.
-- ---------------------------------------------------------------------------

DROP MATERIALIZED VIEW IF EXISTS mv_genre_games;
DROP MATERIALIZED VIEW IF EXISTS mv_tag_games;

CREATE MATERIALIZED VIEW mv_genre_games AS
SELECT
    gn.slug AS genre_slug,
    g.appid, g.name, g.slug, g.developer, g.header_image,
    g.review_count, g.review_count_english, g.positive_pct, g.review_score_desc,
    g.review_count_post_release, g.positive_pct_post_release, g.review_score_desc_post_release,
    g.has_early_access_reviews, g.coming_soon,
    g.price_usd, g.is_free,
    g.release_date, g.deck_compatibility,
    g.hidden_gem_score, g.last_analyzed,
    g.estimated_owners, g.estimated_revenue_usd, g.revenue_estimate_method,
    EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS is_early_access
FROM games g
JOIN game_genres gg2 ON gg2.appid = g.appid
JOIN genres gn ON gg2.genre_id = gn.id;

CREATE UNIQUE INDEX idx_mv_genre_games_pk ON mv_genre_games(genre_slug, appid);
CREATE INDEX idx_mv_genre_games_review ON mv_genre_games(genre_slug, review_count DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_positive_pct ON mv_genre_games(genre_slug, positive_pct DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_hidden_gem ON mv_genre_games(genre_slug, hidden_gem_score DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_last_analyzed ON mv_genre_games(genre_slug, last_analyzed DESC NULLS LAST);
CREATE INDEX idx_mv_genre_games_revenue ON mv_genre_games(genre_slug, estimated_revenue_usd DESC NULLS LAST);

CREATE MATERIALIZED VIEW mv_tag_games AS
SELECT
    t.slug AS tag_slug,
    g.appid, g.name, g.slug, g.developer, g.header_image,
    g.review_count, g.review_count_english, g.positive_pct, g.review_score_desc,
    g.review_count_post_release, g.positive_pct_post_release, g.review_score_desc_post_release,
    g.has_early_access_reviews, g.coming_soon,
    g.price_usd, g.is_free,
    g.release_date, g.deck_compatibility,
    g.hidden_gem_score, g.last_analyzed,
    g.estimated_owners, g.estimated_revenue_usd, g.revenue_estimate_method,
    EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS is_early_access
FROM games g
JOIN game_tags gt ON gt.appid = g.appid
JOIN tags t ON gt.tag_id = t.id;

CREATE UNIQUE INDEX idx_mv_tag_games_pk ON mv_tag_games(tag_slug, appid);
CREATE INDEX idx_mv_tag_games_review ON mv_tag_games(tag_slug, review_count DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_positive_pct ON mv_tag_games(tag_slug, positive_pct DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_hidden_gem ON mv_tag_games(tag_slug, hidden_gem_score DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_last_analyzed ON mv_tag_games(tag_slug, last_analyzed DESC NULLS LAST);
CREATE INDEX idx_mv_tag_games_revenue ON mv_tag_games(tag_slug, estimated_revenue_usd DESC NULLS LAST);

-- ---------------------------------------------------------------------------
-- mv_discovery_feeds — add post-release projections alongside existing columns
-- ---------------------------------------------------------------------------

DROP MATERIALIZED VIEW IF EXISTS mv_discovery_feeds;

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
        g.review_count_post_release,
        g.positive_pct_post_release,
        g.review_score_desc_post_release,
        g.has_early_access_reviews,
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
       review_count_post_release, positive_pct_post_release, review_score_desc_post_release,
       has_early_access_reviews, coming_soon,
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
       review_count_post_release, positive_pct_post_release, review_score_desc_post_release,
       has_early_access_reviews, coming_soon,
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
       review_count_post_release, positive_pct_post_release, review_score_desc_post_release,
       has_early_access_reviews, coming_soon,
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
       review_count_post_release, positive_pct_post_release, review_score_desc_post_release,
       has_early_access_reviews, coming_soon,
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
       review_count_post_release, positive_pct_post_release, review_score_desc_post_release,
       has_early_access_reviews, coming_soon,
       price_usd, is_free,
       release_date, deck_compatibility,
       hidden_gem_score, last_analyzed,
       estimated_owners, estimated_revenue_usd, revenue_estimate_method,
       is_early_access
FROM just_analyzed;

CREATE UNIQUE INDEX mv_discovery_feeds_pk_idx
    ON mv_discovery_feeds (feed_kind, rank);
