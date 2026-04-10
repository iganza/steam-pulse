"""Repository for reading materialized views and managing refresh."""

from aws_lambda_powertools import Logger
from library_layer.repositories.base import BaseRepository
from library_layer.repositories.tag_repo import TAG_CATEGORY_ORDER
from psycopg2 import sql

logger = Logger()

MATVIEW_NAMES: tuple[str, ...] = (
    "mv_genre_counts",
    "mv_tag_counts",
    "mv_price_positioning",
    "mv_release_timing",
    "mv_platform_distribution",
    "mv_tag_trend",
    "mv_genre_games",
    "mv_tag_games",
    "mv_price_summary",
    "mv_review_counts",
    "mv_trend_catalog",
    "mv_trend_by_genre",
    "mv_trend_by_tag",
    "mv_new_releases",
    "mv_analysis_candidates",
)


class MatviewRepository(BaseRepository):
    """Read from materialized views and manage refresh cycles."""

    # ------------------------------------------------------------------
    # Read methods — simple SELECTs against pre-computed matviews
    # ------------------------------------------------------------------

    def get_total_games_count(self) -> int:
        """Return estimated total games count for public.games (instant, no scan)."""
        row = self._fetchone(
            """
            SELECT COALESCE(
                       CASE
                           WHEN c.reltuples >= 0 THEN c.reltuples::bigint
                           ELSE NULL
                       END,
                       s.n_live_tup::bigint,
                       0
                   ) AS estimate
            FROM pg_class AS c
            LEFT JOIN pg_stat_user_tables AS s
              ON s.relid = c.oid
            WHERE c.oid = 'public.games'::regclass
            """
        )
        return int(row["estimate"]) if row else 0

    def get_genre_count(self, genre_slug: str) -> int | None:
        """Return pre-computed game count for a single genre, or None."""
        row = self._fetchone(
            "SELECT game_count FROM mv_genre_counts WHERE slug = %s",
            (genre_slug,),
        )
        return int(row["game_count"]) if row else None

    def get_tag_count(self, tag_slug: str) -> int | None:
        """Return pre-computed game count for a single tag, or None."""
        row = self._fetchone(
            "SELECT game_count FROM mv_tag_counts WHERE slug = %s",
            (tag_slug,),
        )
        return int(row["game_count"]) if row else None

    def list_genre_counts(self) -> list[dict]:
        rows = self._fetchall("""
            SELECT id, name, slug, game_count
            FROM mv_genre_counts
            ORDER BY game_count DESC, name
        """)
        return [dict(r) for r in rows]

    def list_tag_counts(self, limit: int = 100) -> list[dict]:
        rows = self._fetchall(
            """
            SELECT id, name, slug, category, game_count
            FROM mv_tag_counts
            ORDER BY game_count DESC, name
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(r) for r in rows]

    def list_tags_grouped(self, limit_per_category: int = 20) -> list[dict]:
        """Tags grouped by category from mv_tag_counts — mirrors GameRepository.list_tags_grouped()."""
        rows = self._fetchall(
            """
            SELECT ranked.category, ranked.id, ranked.name, ranked.slug,
                   ranked.game_count, ranked.total_count
            FROM (
                SELECT
                    category, id, name, slug, game_count,
                    COUNT(*) OVER (PARTITION BY category) AS total_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY category
                        ORDER BY game_count DESC, name
                    ) AS rn
                FROM mv_tag_counts
                WHERE game_count > 0
            ) AS ranked
            WHERE ranked.rn <= %s
            ORDER BY ranked.category, ranked.game_count DESC, ranked.name
            """,
            (limit_per_category,),
        )
        grouped_by_category: dict[str, dict] = {}
        for row in rows:
            category = row["category"]
            if category not in grouped_by_category:
                grouped_by_category[category] = {
                    "category": category,
                    "tags": [],
                    "total_count": row["total_count"],
                }
            grouped_by_category[category]["tags"].append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "slug": row["slug"],
                    "category": row["category"],
                    "game_count": row["game_count"],
                }
            )
        grouped = list(grouped_by_category.values())
        grouped.sort(
            key=lambda g: (
                TAG_CATEGORY_ORDER.index(g["category"])
                if g["category"] in TAG_CATEGORY_ORDER
                else 99
            ),
        )
        return grouped

    def find_price_positioning(self, genre_slug: str) -> list[dict]:
        rows = self._fetchall(
            """
            SELECT genre_name, price_range, game_count, avg_steam_pct, median_price
            FROM mv_price_positioning
            WHERE genre_slug = %s
            ORDER BY median_price
            """,
            (genre_slug,),
        )
        return [dict(r) for r in rows]

    def find_release_timing(self, genre_slug: str) -> list[dict]:
        rows = self._fetchall(
            """
            SELECT genre_name, month, releases, avg_steam_pct, avg_reviews
            FROM mv_release_timing
            WHERE genre_slug = %s
            ORDER BY month
            """,
            (genre_slug,),
        )
        return [dict(r) for r in rows]

    def find_platform_distribution(self, genre_slug: str) -> dict | None:
        row = self._fetchone(
            """
            SELECT genre_name, total, windows, mac, linux,
                   windows_avg_steam_pct, mac_avg_steam_pct, linux_avg_steam_pct
            FROM mv_platform_distribution
            WHERE genre_slug = %s
            """,
            (genre_slug,),
        )
        return dict(row) if row else None

    def find_tag_trend(self, tag_slug: str) -> list[dict]:
        rows = self._fetchall(
            """
            SELECT tag_name, year, game_count, avg_steam_pct
            FROM mv_tag_trend
            WHERE tag_slug = %s
            ORDER BY year
            """,
            (tag_slug,),
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Refresh management
    # ------------------------------------------------------------------

    def get_last_refresh_time(self) -> float | None:
        """Return epoch seconds of the most recent *full* successful refresh, or None."""
        row = self._fetchone(
            """
            SELECT EXTRACT(EPOCH FROM refreshed_at) AS ts
            FROM matview_refresh_log
            WHERE views_refreshed @> %s AND views_refreshed <@ %s
            ORDER BY refreshed_at DESC
            LIMIT 1
            """,
            (list(MATVIEW_NAMES), list(MATVIEW_NAMES)),
        )
        return float(row["ts"]) if row else None

    def refresh_all(self) -> dict[str, bool]:
        """Refresh all materialized views CONCURRENTLY. Returns name → success."""
        results: dict[str, bool] = {}
        prev_autocommit = self.conn.autocommit
        self.conn.autocommit = True
        try:
            for name in MATVIEW_NAMES:
                try:
                    with self.conn.cursor() as cur:
                        cur.execute(
                            sql.SQL("REFRESH MATERIALIZED VIEW CONCURRENTLY {}").format(
                                sql.Identifier(name)
                            )
                        )
                    results[name] = True
                except Exception:
                    logger.exception(
                        "Failed to refresh matview",
                        extra={"matview": name},
                    )
                    results[name] = False
        finally:
            self.conn.autocommit = prev_autocommit
        return results

    def log_refresh(self, duration_ms: int, views: list[str]) -> None:
        """Record a refresh event for debounce tracking."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO matview_refresh_log (duration_ms, views_refreshed)
                VALUES (%s, %s)
                """,
                (duration_ms, views),
            )
        self.conn.commit()
