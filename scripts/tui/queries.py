"""SQL query constants for the TUI screens."""

# ── Dashboard ──────────────────────────────────────────────────────────────────

DASHBOARD_KPI = """
SELECT
  COALESCE((SELECT reltuples::bigint FROM pg_class WHERE relname = 'games'),       0) AS games,
  COALESCE((SELECT reltuples::bigint FROM pg_class WHERE relname = 'reviews'),     0) AS reviews,
  COALESCE((SELECT reltuples::bigint FROM pg_class WHERE relname = 'reports'),     0) AS reports,
  COALESCE((SELECT reltuples::bigint FROM pg_class WHERE relname = 'app_catalog'), 0) AS catalog
"""

DASHBOARD_PIPELINE = """
SELECT
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE meta_status = 'pending') AS meta_pending,
  COUNT(*) FILTER (WHERE meta_status = 'done') AS meta_done,
  COUNT(*) FILTER (WHERE meta_status = 'failed') AS meta_failed,
  COUNT(*) FILTER (WHERE meta_status = 'skipped') AS meta_skipped,
  COUNT(*) FILTER (WHERE reviews_completed_at IS NOT NULL) AS reviews_done,
  COUNT(*) FILTER (WHERE tags_crawled_at IS NOT NULL) AS tags_crawled
FROM app_catalog
"""

DASHBOARD_FRESHNESS = """
SELECT
  (SELECT MAX(meta_crawled_at) FROM app_catalog) AS last_meta_crawl,
  (SELECT MAX(review_crawled_at) FROM app_catalog) AS last_review_crawl,
  (SELECT MAX(last_analyzed) FROM reports) AS last_analysis,
  (SELECT MAX(refreshed_at) FROM matview_refresh_log) AS last_matview_refresh
"""

DASHBOARD_REPORT_COUNT = "SELECT COUNT(*) AS reports FROM reports"

DASHBOARD_MIGRATIONS = """
SELECT migration_id, applied_at_utc
FROM _yoyo_migration
WHERE migration_id ~ '^[0-9]{4}_'
ORDER BY migration_id DESC
"""

# -- Games ---------------------------------------------------------------------

GAMES_LIST = """
SELECT g.appid, g.name, g.review_count, g.positive_pct, g.sentiment_score,
       g.price_usd, g.release_date, g.crawled_at, g.last_analyzed,
       CASE WHEN r.appid IS NOT NULL THEN true ELSE false END AS has_report
FROM games g
LEFT JOIN reports r ON r.appid = g.appid
{where}
ORDER BY {sort}
LIMIT {limit} OFFSET {offset}
"""

GAMES_COUNT = """
SELECT COUNT(*) AS total
FROM games g
LEFT JOIN reports r ON r.appid = g.appid
{where}
"""

GAME_DETAIL = """
SELECT g.*, ac.meta_status, ac.meta_crawled_at, ac.reviews_completed_at,
       ac.tags_crawled_at, ac.review_crawled_at
FROM games g
LEFT JOIN app_catalog ac ON ac.appid = g.appid
WHERE g.appid = %s
"""

GAME_REPORT_SUMMARY = """
SELECT reviews_analyzed, last_analyzed,
       report_json->>'one_liner' AS one_liner,
       report_json->>'overall_sentiment' AS overall_sentiment,
       (report_json->>'sentiment_score')::float AS sentiment_score,
       jsonb_array_length(report_json->'design_strengths') AS strengths_count,
       jsonb_array_length(report_json->'gameplay_friction') AS friction_count,
       jsonb_array_length(report_json->'technical_issues') AS tech_issues_count
FROM reports WHERE appid = %s
"""

GAME_REVIEW_COUNT = "SELECT COUNT(*) AS count FROM reviews WHERE appid = %s"

# -- Reviews -------------------------------------------------------------------

REVIEW_STATS = """
SELECT
  COUNT(*) AS total,
  ROUND(100.0 * COUNT(*) FILTER (WHERE voted_up) / NULLIF(COUNT(*), 0), 1) AS positive_pct,
  ROUND(AVG(playtime_hours)::numeric, 1) AS avg_playtime,
  ROUND(100.0 * COUNT(*) FILTER (WHERE written_during_early_access)
        / NULLIF(COUNT(*), 0), 1) AS ea_pct,
  MAX(posted_at) AS last_review
FROM reviews WHERE appid = %s
"""

REVIEWS_LIST = """
SELECT steam_review_id, voted_up, playtime_hours, posted_at, language,
       votes_helpful, votes_funny, written_during_early_access,
       LEFT(body, 80) AS body_preview
FROM reviews
WHERE appid = %s
ORDER BY {sort}
LIMIT {limit} OFFSET {offset}
"""

REVIEW_FULL_BODY = "SELECT body FROM reviews WHERE id = %s"

# ── Tags & Genres ──────────────────────────────────────────────────────────────

TAGS_LIST = """
SELECT name, slug, category, game_count
FROM mv_tag_counts
ORDER BY category, game_count DESC
"""

GENRES_LIST = """
SELECT name, slug, game_count
FROM mv_genre_counts
ORDER BY game_count DESC
"""

TAG_TOP_GAMES = """
SELECT appid, name, slug, developer, review_count, positive_pct, sentiment_score
FROM mv_tag_games
WHERE tag_slug = %s
ORDER BY review_count DESC
LIMIT 20
"""

GENRE_TOP_GAMES = """
SELECT appid, name, slug, developer, review_count, positive_pct, sentiment_score
FROM mv_genre_games
WHERE genre_slug = %s
ORDER BY review_count DESC
LIMIT 20
"""

MATVIEW_LAST_REFRESH = """
SELECT MAX(refreshed_at) AS last_refresh FROM matview_refresh_log
"""

# -- Analysis ------------------------------------------------------------------

ANALYSIS_BACKLOG = """
SELECT g.appid, g.name, g.review_count,
       COALESCE(mrc.stored_count, 0) AS reviews_in_db,
       r.last_analyzed,
       CASE
         WHEN r.appid IS NULL THEN 'no report'
         WHEN r.last_analyzed < NOW() - INTERVAL '30 days' THEN 'stale'
         ELSE 'current'
       END AS status
FROM games g
LEFT JOIN reports r ON r.appid = g.appid
LEFT JOIN mv_review_counts mrc ON mrc.appid = g.appid
WHERE g.review_count >= 50
ORDER BY
  CASE WHEN r.appid IS NULL THEN 0 ELSE 1 END,
  g.review_count DESC
LIMIT 100
"""

REPORT_FULL_JSON = "SELECT report_json FROM reports WHERE appid = %s"

# ── Saved Queries (SQL Console templates) ──────────────────────────────────────

SAVED_QUERIES: dict[str, str] = {
    "Pipeline funnel": """
SELECT
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE meta_status = 'pending') AS meta_pending,
  COUNT(*) FILTER (WHERE meta_status = 'done') AS meta_done,
  COUNT(*) FILTER (WHERE meta_status = 'failed') AS meta_failed,
  COUNT(*) FILTER (WHERE meta_status = 'skipped') AS meta_skipped,
  COUNT(*) FILTER (WHERE reviews_completed_at IS NOT NULL) AS reviews_done,
  COUNT(*) FILTER (WHERE tags_crawled_at IS NOT NULL) AS tags_crawled
FROM app_catalog
    """.strip(),
    "Unanalyzed games (top 50)": """
SELECT g.appid, g.name, g.review_count,
       ac.reviews_completed_at, g.crawled_at
FROM games g
JOIN app_catalog ac ON ac.appid = g.appid
WHERE ac.reviews_completed_at IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM reports r WHERE r.appid = g.appid)
ORDER BY g.review_count DESC
LIMIT 50
    """.strip(),
    "Stale reports (>30d)": """
SELECT r.appid, g.name, r.last_analyzed, g.review_count,
       NOW() - r.last_analyzed AS age
FROM reports r
JOIN games g ON g.appid = r.appid
WHERE r.last_analyzed < NOW() - INTERVAL '30 days'
ORDER BY r.last_analyzed ASC
LIMIT 50
    """.strip(),
    "Review crawl stuck": """
SELECT ac.appid, g.name, ac.review_crawled_at, ac.reviews_completed_at,
       g.review_count
FROM app_catalog ac
JOIN games g ON g.appid = ac.appid
WHERE ac.review_crawled_at IS NOT NULL
  AND ac.reviews_completed_at IS NULL
  AND ac.review_crawled_at < NOW() - INTERVAL '6 hours'
ORDER BY ac.review_crawled_at ASC
    """.strip(),
    "Failed metadata": """
SELECT ac.appid, ac.name, ac.meta_crawled_at
FROM app_catalog ac
WHERE ac.meta_status = 'failed'
ORDER BY ac.meta_crawled_at DESC
LIMIT 50
    """.strip(),
    "Top games without tags": """
SELECT g.appid, g.name, g.review_count, ac.tags_crawled_at
FROM games g
JOIN app_catalog ac ON ac.appid = g.appid
WHERE ac.tags_crawled_at IS NULL
  AND g.review_count >= 100
ORDER BY g.review_count DESC
LIMIT 50
    """.strip(),
    "Recent analyses": """
SELECT r.appid, g.name, r.reviews_analyzed, r.last_analyzed,
       report_json->>'overall_sentiment' AS sentiment,
       (report_json->>'sentiment_score')::float AS score
FROM reports r
JOIN games g ON g.appid = r.appid
ORDER BY r.last_analyzed DESC
LIMIT 25
    """.strip(),
    "Matview refresh history": """
SELECT refreshed_at, duration_ms, views_refreshed
FROM matview_refresh_log
ORDER BY refreshed_at DESC
LIMIT 20
    """.strip(),
    "Review volume by month": """
SELECT DATE_TRUNC('month', posted_at) AS month,
       COUNT(*) AS reviews,
       ROUND(100.0 * COUNT(*) FILTER (WHERE voted_up) / COUNT(*), 1) AS positive_pct
FROM reviews
WHERE posted_at > NOW() - INTERVAL '12 months'
GROUP BY 1 ORDER BY 1 DESC
    """.strip(),
    "DLQ candidates (failed metadata)": """
SELECT ac.appid, ac.name, ac.meta_status, ac.meta_crawled_at
FROM app_catalog ac
WHERE ac.meta_status = 'failed'
ORDER BY ac.meta_crawled_at DESC NULLS LAST
LIMIT 50
    """.strip(),
}
