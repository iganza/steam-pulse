"""Repository for reading materialized views and managing refresh."""

import json
import time

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
    "mv_catalog_reports",
    "mv_audience_overlap",
    "mv_discovery_feeds",
)

# Views invalidated by a new report landing — used by the `report-ready` trigger path.
# Order mirrors MATVIEW_NAMES so the Map (max_concurrency=1) refreshes in the same sequence.
REPORT_DEPENDENT_VIEWS: tuple[str, ...] = (
    "mv_new_releases",
    "mv_analysis_candidates",
    "mv_catalog_reports",
    "mv_discovery_feeds",
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

    def list_discovery_feed(self, kind: str, limit: int) -> list[dict]:
        """Top-N games for a homepage discovery feed (pre-computed in mv_discovery_feeds).

        kind: one of 'popular' | 'top_rated' | 'hidden_gem' | 'new_release' | 'just_analyzed'.
        The caller is responsible for validating `kind`; an unknown value returns [].

        Rows match the shape returned by GameRepository._list_from_matview() so the
        same frontend Game type consumes them.
        """
        rows = self._fetchall(
            """
            SELECT appid, name, slug, developer, header_image,
                   review_count, review_count_english, positive_pct, review_score_desc,
                   price_usd, is_free,
                   release_date, deck_compatibility,
                   hidden_gem_score, last_analyzed, is_early_access,
                   estimated_owners, estimated_revenue_usd, revenue_estimate_method
            FROM mv_discovery_feeds
            WHERE feed_kind = %s
            ORDER BY rank
            LIMIT %s
            """,
            (kind, limit),
        )
        # Convert psycopg2 types that stdlib json.dumps (used by JSONResponse in
        # the /api/discovery/{kind} handler) can't serialize:
        #   - date        → str (YYYY-MM-DD)
        #   - datetime    → ISO-8601 str
        #   - Decimal     → float
        result = []
        for row in rows:
            d = dict(row)
            if d.get("release_date"):
                d["release_date"] = str(d["release_date"])
            if d.get("last_analyzed") is not None:
                d["last_analyzed"] = d["last_analyzed"].isoformat()
            if d.get("price_usd") is not None:
                d["price_usd"] = float(d["price_usd"])
            if d.get("estimated_revenue_usd") is not None:
                d["estimated_revenue_usd"] = float(d["estimated_revenue_usd"])
            result.append(d)
        return result

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

    def get_audience_overlap(self, appid: int, *, limit: int) -> dict:
        """Serve precomputed audience overlap from mv_audience_overlap.

        total_reviewers is derived from reviews directly (with 10k cap) rather
        than from the matview, so games with reviewers but no overlaps still
        report the correct count.
        """
        total_row = self._fetchone(
            """
            SELECT COUNT(*) AS total_reviewers
            FROM (
                SELECT 1
                FROM (
                    SELECT DISTINCT author_steamid
                    FROM reviews
                    WHERE appid = %s AND author_steamid IS NOT NULL
                ) deduped
                LIMIT 10000
            ) capped
            """,
            (appid,),
        )
        total = int(total_row["total_reviewers"]) if total_row else 0
        if total == 0:
            return {"total_reviewers": 0, "overlaps": []}

        rows = self._fetchall(
            """
            SELECT o.overlap_appid AS appid, g.name, g.slug, g.header_image,
                   g.positive_pct, g.review_count,
                   o.overlap_count, o.overlap_pct, o.shared_sentiment_pct
            FROM mv_audience_overlap o
            JOIN games g ON o.overlap_appid = g.appid
            WHERE o.appid = %s
            ORDER BY o.overlap_count DESC
            LIMIT %s
            """,
            (appid, limit),
        )
        return {
            "total_reviewers": total,
            "overlaps": [
                {
                    "appid": int(r["appid"]),
                    "name": r["name"],
                    "slug": r["slug"],
                    "header_image": r["header_image"],
                    "positive_pct": r["positive_pct"],
                    "review_count": r["review_count"],
                    "overlap_count": int(r["overlap_count"]),
                    "overlap_pct": float(r["overlap_pct"]),
                    "shared_sentiment_pct": float(r["shared_sentiment_pct"]),
                }
                for r in rows
            ],
        }

    # ------------------------------------------------------------------
    # Refresh management
    # ------------------------------------------------------------------

    def get_last_refresh_time(self) -> float | None:
        """Epoch seconds of the newest status='complete' cycle, or None."""
        row = self._fetchone(
            """
            SELECT EXTRACT(EPOCH FROM refreshed_at) AS ts
            FROM matview_refresh_log
            WHERE status = 'complete'
            ORDER BY refreshed_at DESC
            LIMIT 1
            """,
        )
        return float(row["ts"]) if row else None

    def get_running_cycle_id(self, stale_after_seconds: int) -> str | None:
        """cycle_id of the newest 'running' row inside the stale window, or None."""
        row = self._fetchone(
            """
            SELECT cycle_id
            FROM matview_refresh_log
            WHERE status = 'running'
              AND started_at > NOW() - (%s || ' seconds')::interval
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (str(stale_after_seconds),),
        )
        return row["cycle_id"] if row else None

    def refresh_one(self, name: str) -> int:
        """REFRESH MATERIALIZED VIEW CONCURRENTLY <name>. Returns duration_ms."""
        if name not in MATVIEW_NAMES:
            raise ValueError(f"Unknown matview name: {name!r}")
        # Snapshot conn — BaseRepository.conn re-invokes the factory per access.
        conn = self.conn
        prev_autocommit = conn.autocommit
        if not prev_autocommit:
            conn.rollback()
        conn.autocommit = True
        try:
            start = time.monotonic()
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("REFRESH MATERIALIZED VIEW CONCURRENTLY {}").format(
                        sql.Identifier(name)
                    )
                )
            return int((time.monotonic() - start) * 1000)
        finally:
            conn.autocommit = prev_autocommit

    def start_cycle(self, cycle_id: str) -> None:
        """Idempotent insert of a 'running' row keyed by SFN execution name."""
        conn = self.conn
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO matview_refresh_log (cycle_id, status, started_at)
                VALUES (%s, 'running', NOW())
                ON CONFLICT (cycle_id) WHERE cycle_id IS NOT NULL DO NOTHING
                """,
                (cycle_id,),
            )
        conn.commit()

    def complete_cycle(
        self,
        cycle_id: str,
        duration_ms: int,
        per_view_results: dict[str, dict],
    ) -> None:
        """Finalize the cycle row: derive status, stamp refreshed_at, raise if no match."""
        success_names = [n for n, r in per_view_results.items() if r.get("success")]
        if len(success_names) == len(per_view_results):
            status = "complete"
        elif not success_names:
            status = "failed"
        else:
            status = "partial_failure"
        conn = self.conn
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE matview_refresh_log
                SET status = %s,
                    duration_ms = %s,
                    per_view_results = %s::jsonb,
                    views_refreshed = %s,
                    refreshed_at = NOW()
                WHERE cycle_id = %s
                """,
                (
                    status,
                    duration_ms,
                    json.dumps(per_view_results),
                    success_names,
                    cycle_id,
                ),
            )
            rowcount = cur.rowcount
        conn.commit()
        if rowcount == 0:
            raise RuntimeError(
                f"complete_cycle matched no row for cycle_id={cycle_id!r}"
            )
