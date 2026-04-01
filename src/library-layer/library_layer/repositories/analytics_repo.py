"""AnalyticsRepository — cross-cutting analytics queries spanning multiple tables."""

import json

from library_layer.repositories.base import BaseRepository

_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


class AnalyticsRepository(BaseRepository):
    """Cross-cutting analytics queries spanning games, reviews, genres, and tags."""

    def find_audience_overlap(self, appid: int, limit: int = 20) -> dict:
        """Find games with the most shared reviewers via author_steamid.

        Caps the reviewer pool at 10,000 to keep the self-join fast for large
        games (TF2, CS2, etc.) — sufficient for meaningful overlap detection.
        """
        # Count using the same 10k cap so total_reviewers is consistent with overlap_pct.
        total_row = self._fetchone(
            """
            SELECT COUNT(*) AS cnt FROM (
                SELECT DISTINCT author_steamid
                FROM reviews
                WHERE appid = %s AND author_steamid IS NOT NULL
                LIMIT 10000
            ) capped
            """,
            (appid,),
        )
        total = int(total_row["cnt"]) if total_row else 0
        if total == 0:
            return {"total_reviewers": 0, "overlaps": []}

        rows = self._fetchall(
            """
            WITH game_reviewers AS (
                SELECT DISTINCT author_steamid
                FROM reviews
                WHERE appid = %s AND author_steamid IS NOT NULL
                ORDER BY author_steamid
                LIMIT 10000
            ),
            total AS (
                SELECT COUNT(*) AS cnt FROM game_reviewers
            ),
            shared_games AS (
                SELECT r.appid,
                       COUNT(DISTINCT r.author_steamid) AS overlap_count,
                       ROUND(COUNT(CASE WHEN r.voted_up THEN 1 END)::numeric
                             / NULLIF(COUNT(*), 0) * 100, 1) AS shared_sentiment_pct
                FROM reviews r
                JOIN game_reviewers gr ON r.author_steamid = gr.author_steamid
                WHERE r.appid != %s
                GROUP BY r.appid
                ORDER BY overlap_count DESC
                LIMIT %s
            )
            SELECT o.appid, g.name, g.slug, g.header_image,
                   g.positive_pct, g.review_count,
                   o.overlap_count,
                   ROUND(o.overlap_count::numeric / NULLIF(t.cnt, 0) * 100, 1) AS overlap_pct,
                   o.shared_sentiment_pct
            FROM shared_games o
            JOIN games g ON o.appid = g.appid
            CROSS JOIN total t
            ORDER BY o.overlap_count DESC
            """,
            (appid, appid, limit),
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

    def find_price_positioning(self, genre_slug: str) -> dict:
        """Price distribution + sentiment correlation within a genre."""
        genre_row = self._fetchone(
            "SELECT name FROM genres WHERE slug = %s", (genre_slug,)
        )
        genre_name = genre_row["name"] if genre_row else genre_slug

        dist_rows = self._fetchall(
            """
            SELECT
                CASE
                    WHEN g.is_free THEN 'Free'
                    WHEN g.price_usd < 5 THEN 'Under $5'
                    WHEN g.price_usd < 10 THEN '$5-10'
                    WHEN g.price_usd < 15 THEN '$10-15'
                    WHEN g.price_usd < 20 THEN '$15-20'
                    WHEN g.price_usd < 30 THEN '$20-30'
                    WHEN g.price_usd < 50 THEN '$30-50'
                    ELSE '$50+'
                END AS price_range,
                COUNT(*) AS game_count,
                ROUND(AVG(g.positive_pct), 1) AS avg_sentiment,
                ROUND(
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY COALESCE(g.price_usd, 0))::numeric,
                    2
                ) AS median_price
            FROM games g
            JOIN game_genres gg ON gg.appid = g.appid
            JOIN genres gn ON gg.genre_id = gn.id
            WHERE gn.slug = %s
              AND g.review_count >= 10
              AND (g.price_usd IS NOT NULL OR g.is_free)
            GROUP BY 1
            ORDER BY MIN(COALESCE(g.price_usd, 0))
            """,
            (genre_slug,),
        )

        summary_row = self._fetchone(
            """
            SELECT
                ROUND(AVG(g.price_usd) FILTER (WHERE NOT g.is_free), 2) AS avg_price,
                ROUND(
                    (PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY g.price_usd)
                     FILTER (WHERE NOT g.is_free))::numeric,
                    2
                ) AS median_price,
                COUNT(*) FILTER (WHERE g.is_free) AS free_count,
                COUNT(*) FILTER (WHERE NOT g.is_free) AS paid_count
            FROM games g
            JOIN game_genres gg ON gg.appid = g.appid
            JOIN genres gn ON gg.genre_id = gn.id
            WHERE gn.slug = %s AND g.review_count >= 10
            """,
            (genre_slug,),
        )

        distribution = [
            {
                "price_range": r["price_range"],
                "game_count": int(r["game_count"]),
                "avg_sentiment": float(r["avg_sentiment"]) if r["avg_sentiment"] is not None else None,
                "median_price": float(r["median_price"]) if r["median_price"] is not None else 0.0,
            }
            for r in dist_rows
        ]

        eligible = [d for d in distribution if d["game_count"] >= 10 and d["avg_sentiment"] is not None]
        sweet_spot = max(eligible, key=lambda x: x["avg_sentiment"])["price_range"] if eligible else None

        return {
            "genre": genre_name,
            "genre_slug": genre_slug,
            "distribution": distribution,
            "summary": {
                "avg_price": float(summary_row["avg_price"]) if summary_row and summary_row["avg_price"] else None,
                "median_price": float(summary_row["median_price"]) if summary_row and summary_row["median_price"] else None,
                "free_count": int(summary_row["free_count"]) if summary_row else 0,
                "paid_count": int(summary_row["paid_count"]) if summary_row else 0,
                "sweet_spot": sweet_spot,
            },
        }

    def find_release_timing(self, genre_slug: str) -> dict:
        """Monthly release density and avg sentiment by month, last 5 years."""
        genre_row = self._fetchone(
            "SELECT name FROM genres WHERE slug = %s", (genre_slug,)
        )
        genre_name = genre_row["name"] if genre_row else genre_slug

        rows = self._fetchall(
            """
            SELECT
                EXTRACT(MONTH FROM g.release_date)::int AS month,
                COUNT(*) AS releases,
                ROUND(AVG(g.positive_pct), 1) AS avg_sentiment,
                ROUND(AVG(g.review_count), 0) AS avg_reviews
            FROM games g
            JOIN game_genres gg ON gg.appid = g.appid
            JOIN genres gn ON gg.genre_id = gn.id
            WHERE gn.slug = %s
              AND g.release_date IS NOT NULL
              AND g.release_date >= NOW() - INTERVAL '5 years'
              AND g.review_count >= 10
            GROUP BY 1
            ORDER BY 1
            """,
            (genre_slug,),
        )

        monthly = [
            {
                "month": r["month"],
                "month_name": _MONTH_NAMES[r["month"]],
                "releases": int(r["releases"]),
                "avg_sentiment": float(r["avg_sentiment"]) if r["avg_sentiment"] is not None else None,
                "avg_reviews": int(r["avg_reviews"]) if r["avg_reviews"] is not None else 0,
            }
            for r in rows
        ]

        if not monthly:
            return {
                "genre": genre_name,
                "monthly": [],
                "best_month": None,
                "worst_month": None,
                "quietest_month": None,
                "busiest_month": None,
            }

        has_sentiment = [m for m in monthly if m["avg_sentiment"] is not None]
        best_month = max(has_sentiment, key=lambda x: x["avg_sentiment"]) if has_sentiment else None
        worst_month = min(has_sentiment, key=lambda x: x["avg_sentiment"]) if has_sentiment else None
        quietest_month = min(monthly, key=lambda x: x["releases"])
        busiest_month = max(monthly, key=lambda x: x["releases"])

        def _summary(m: dict | None) -> dict | None:
            if m is None:
                return None
            return {
                "month": m["month"],
                "month_name": m["month_name"],
                "avg_sentiment": m.get("avg_sentiment"),
                "releases": m["releases"],
            }

        return {
            "genre": genre_name,
            "monthly": monthly,
            "best_month": _summary(best_month),
            "worst_month": _summary(worst_month),
            "quietest_month": _summary(quietest_month),
            "busiest_month": _summary(busiest_month),
        }

    def find_platform_distribution(self, genre_slug: str) -> dict:
        """Platform support breakdown and sentiment by platform within a genre."""
        genre_row = self._fetchone(
            "SELECT name FROM genres WHERE slug = %s", (genre_slug,)
        )
        genre_name = genre_row["name"] if genre_row else genre_slug

        row = self._fetchone(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE (g.platforms->>'windows')::boolean) AS windows,
                COUNT(*) FILTER (WHERE (g.platforms->>'mac')::boolean) AS mac,
                COUNT(*) FILTER (WHERE (g.platforms->>'linux')::boolean) AS linux,
                ROUND(AVG(g.positive_pct) FILTER (WHERE (g.platforms->>'windows')::boolean), 1)
                    AS windows_avg_sentiment,
                ROUND(AVG(g.positive_pct) FILTER (WHERE (g.platforms->>'mac')::boolean), 1)
                    AS mac_avg_sentiment,
                ROUND(AVG(g.positive_pct) FILTER (WHERE (g.platforms->>'linux')::boolean), 1)
                    AS linux_avg_sentiment
            FROM games g
            JOIN game_genres gg ON gg.appid = g.appid
            JOIN genres gn ON gg.genre_id = gn.id
            WHERE gn.slug = %s
              AND g.platforms IS NOT NULL
              AND g.review_count >= 10
            """,
            (genre_slug,),
        )

        if not row or not row["total"]:
            return {"genre": genre_name, "total_games": 0, "platforms": {}, "underserved": None}

        total = int(row["total"])

        def _pct(count: int) -> float:
            return round(count / total * 100, 1) if total else 0.0

        platforms = {
            "windows": {
                "count": int(row["windows"] or 0),
                "pct": _pct(int(row["windows"] or 0)),
                "avg_sentiment": float(row["windows_avg_sentiment"]) if row["windows_avg_sentiment"] is not None else None,
            },
            "mac": {
                "count": int(row["mac"] or 0),
                "pct": _pct(int(row["mac"] or 0)),
                "avg_sentiment": float(row["mac_avg_sentiment"]) if row["mac_avg_sentiment"] is not None else None,
            },
            "linux": {
                "count": int(row["linux"] or 0),
                "pct": _pct(int(row["linux"] or 0)),
                "avg_sentiment": float(row["linux_avg_sentiment"]) if row["linux_avg_sentiment"] is not None else None,
            },
        }

        supported = {name: data for name, data in platforms.items() if data["pct"] > 0}
        underserved = min(supported, key=lambda k: supported[k]["pct"]) if supported else None

        return {
            "genre": genre_name,
            "total_games": total,
            "platforms": platforms,
            "underserved": underserved,
        }

    def find_tag_trend(self, tag_slug: str) -> dict:
        """Game count per year for a specific tag, showing growth over time."""
        tag_row = self._fetchone("SELECT name FROM tags WHERE slug = %s", (tag_slug,))
        tag_name = tag_row["name"] if tag_row else tag_slug

        rows = self._fetchall(
            """
            SELECT
                EXTRACT(YEAR FROM g.release_date)::int AS year,
                COUNT(*) AS game_count,
                ROUND(AVG(g.positive_pct), 1) AS avg_sentiment
            FROM games g
            JOIN game_tags gt ON gt.appid = g.appid
            JOIN tags t ON gt.tag_id = t.id
            WHERE t.slug = %s
              AND g.release_date IS NOT NULL
              AND EXTRACT(YEAR FROM g.release_date) >= 2015
            GROUP BY 1
            ORDER BY 1
            """,
            (tag_slug,),
        )

        yearly = [
            {
                "year": r["year"],
                "game_count": int(r["game_count"]),
                "avg_sentiment": float(r["avg_sentiment"]) if r["avg_sentiment"] is not None else None,
            }
            for r in rows
        ]

        total_games = sum(y["game_count"] for y in yearly)
        peak_year = max(yearly, key=lambda x: x["game_count"])["year"] if yearly else None

        first_count = yearly[0]["game_count"] if yearly else 0
        last_count = yearly[-1]["game_count"] if yearly else 0
        if first_count > 0:
            growth_rate: float | None = round((last_count - first_count) / first_count, 4)
        else:
            growth_rate = None

        return {
            "tag": tag_name,
            "tag_slug": tag_slug,
            "yearly": yearly,
            "growth_rate": growth_rate,
            "peak_year": peak_year,
            "total_games": total_games,
        }

    def find_developer_portfolio(self, developer_slug: str) -> dict:
        """All games by a developer with aggregate stats and sentiment trajectory."""
        games_rows = self._fetchall(
            """
            SELECT
                g.appid, g.name, g.slug, g.header_image,
                g.release_date, g.price_usd, g.is_free,
                g.review_count, g.positive_pct, g.review_score_desc,
                g.metacritic_score, g.achievements_total, g.developer
            FROM games g
            WHERE g.developer_slug = %s
            ORDER BY g.release_date DESC NULLS LAST
            """,
            (developer_slug,),
        )

        summary_row = self._fetchone(
            """
            SELECT
                COUNT(*) AS total_games,
                SUM(g.review_count) AS total_reviews,
                ROUND(AVG(g.positive_pct), 1) AS avg_sentiment,
                MIN(g.release_date) AS first_release,
                MAX(g.release_date) AS latest_release,
                ROUND(AVG(g.price_usd) FILTER (WHERE NOT g.is_free), 2) AS avg_price,
                COUNT(*) FILTER (WHERE g.is_free) AS free_games,
                COUNT(*) FILTER (WHERE g.positive_pct >= 70) AS well_received,
                COUNT(*) FILTER (WHERE g.positive_pct < 50) AS poorly_received
            FROM games g
            WHERE g.developer_slug = %s
            """,
            (developer_slug,),
        )

        developer_name = games_rows[0]["developer"] if games_rows else developer_slug
        total_games = int(summary_row["total_games"]) if summary_row else 0
        overall_avg = float(summary_row["avg_sentiment"]) if summary_row and summary_row["avg_sentiment"] is not None else 0.0

        # Sentiment trajectory: compare last-3 games avg vs overall avg
        ordered = sorted(
            [g for g in games_rows if g["release_date"] is not None and g["positive_pct"] is not None],
            key=lambda g: g["release_date"],
        )
        if total_games == 0:
            trajectory = "no_games"
        elif total_games == 1:
            trajectory = "single_title"
        elif len(ordered) >= 3:
            last_3_avg = sum(float(g["positive_pct"]) for g in ordered[-3:]) / 3
            if last_3_avg >= overall_avg + 5:
                trajectory = "improving"
            elif last_3_avg <= overall_avg - 5:
                trajectory = "declining"
            else:
                trajectory = "stable"
        else:
            trajectory = "stable"

        games = [
            {
                "appid": int(r["appid"]),
                "name": r["name"],
                "slug": r["slug"],
                "header_image": r["header_image"],
                "release_date": str(r["release_date"]) if r["release_date"] else None,
                "price_usd": float(r["price_usd"]) if r["price_usd"] is not None else None,
                "is_free": r["is_free"],
                "review_count": r["review_count"],
                "positive_pct": r["positive_pct"],
                "review_score_desc": r["review_score_desc"],
                "metacritic_score": r["metacritic_score"],
                "achievements_total": r["achievements_total"],
            }
            for r in games_rows
        ]

        return {
            "developer": developer_name,
            "developer_slug": developer_slug,
            "summary": {
                "total_games": total_games,
                "total_reviews": int(summary_row["total_reviews"]) if summary_row and summary_row["total_reviews"] else 0,
                "avg_sentiment": overall_avg,
                "first_release": str(summary_row["first_release"]) if summary_row and summary_row["first_release"] else None,
                "latest_release": str(summary_row["latest_release"]) if summary_row and summary_row["latest_release"] else None,
                "avg_price": float(summary_row["avg_price"]) if summary_row and summary_row["avg_price"] else None,
                "free_games": int(summary_row["free_games"]) if summary_row else 0,
                "well_received": int(summary_row["well_received"]) if summary_row else 0,
                "poorly_received": int(summary_row["poorly_received"]) if summary_row else 0,
                "sentiment_trajectory": trajectory,
            },
            "games": games,
        }

    # -----------------------------------------------------------------------
    # Catalog-wide trend methods (analytics dashboard)
    # -----------------------------------------------------------------------

    def _type_clause(self, game_type: str) -> str:
        """Return SQL fragment for game type filtering."""
        if game_type == "dlc":
            return "AND g.type = 'dlc'"
        if game_type == "all":
            return ""
        return "AND g.type = 'game'"

    def _genre_join_and_filter(
        self, genre_slug: str | None, params: list,
    ) -> tuple[str, str]:
        """Return (JOIN clause, WHERE clause) for optional genre filter."""
        if genre_slug is None:
            return "", ""
        params.append(genre_slug)
        return (
            "JOIN game_genres gg ON gg.appid = g.appid JOIN genres gn ON gg.genre_id = gn.id",
            "AND gn.slug = %s",
        )

    def _tag_join_and_filter(
        self, tag_slug: str | None, params: list,
    ) -> tuple[str, str]:
        """Return (JOIN clause, WHERE clause) for optional tag filter."""
        if tag_slug is None:
            return "", ""
        params.append(tag_slug)
        return (
            "JOIN game_tags gt2 ON gt2.appid = g.appid JOIN tags t2 ON gt2.tag_id = t2.id",
            "AND t2.slug = %s",
        )

    def find_release_volume_rows(
        self,
        granularity: str,
        genre_slug: str | None = None,
        tag_slug: str | None = None,
        game_type: str = "game",
        limit: int = 100,
    ) -> list[dict]:
        params: list = [granularity]
        genre_join, genre_where = self._genre_join_and_filter(genre_slug, params)
        tag_join, tag_where = self._tag_join_and_filter(tag_slug, params)
        type_clause = self._type_clause(game_type)
        params.append(limit)

        rows = self._fetchall(
            f"""
            SELECT * FROM (
                SELECT
                    DATE_TRUNC(%s, g.release_date) AS period,
                    COUNT(*) AS releases,
                    ROUND(AVG(g.positive_pct), 1) AS avg_sentiment,
                    ROUND(AVG(g.review_count), 0) AS avg_reviews,
                    COUNT(*) FILTER (WHERE g.is_free) AS free_count
                FROM games g
                {genre_join}
                {tag_join}
                WHERE g.release_date IS NOT NULL
                  AND g.coming_soon = FALSE
                  {type_clause}
                  AND g.review_count >= 10
                  {genre_where}
                  {tag_where}
                GROUP BY 1
                ORDER BY 1 DESC
                LIMIT %s
            ) sub ORDER BY period
            """,
            tuple(params),
        )
        return [dict(r) for r in rows]

    def find_sentiment_distribution_rows(
        self,
        granularity: str,
        genre_slug: str | None = None,
        game_type: str = "game",
        limit: int = 100,
    ) -> list[dict]:
        params: list = [granularity]
        genre_join, genre_where = self._genre_join_and_filter(genre_slug, params)
        type_clause = self._type_clause(game_type)
        params.append(limit)

        rows = self._fetchall(
            f"""
            SELECT * FROM (
                SELECT
                    DATE_TRUNC(%s, g.release_date) AS period,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE g.positive_pct >= 70) AS positive_count,
                    COUNT(*) FILTER (WHERE g.positive_pct >= 40 AND g.positive_pct < 70) AS mixed_count,
                    COUNT(*) FILTER (WHERE g.positive_pct < 40) AS negative_count,
                    ROUND(AVG(g.positive_pct), 1) AS avg_sentiment,
                    ROUND(AVG(g.metacritic_score) FILTER (WHERE g.metacritic_score IS NOT NULL), 1) AS avg_metacritic
                FROM games g
                {genre_join}
                WHERE g.release_date IS NOT NULL
                  AND g.coming_soon = FALSE
                  {type_clause}
                  AND g.review_count >= 10
                  {genre_where}
                GROUP BY 1
                ORDER BY 1 DESC
                LIMIT %s
            ) sub ORDER BY period
            """,
            tuple(params),
        )
        return [dict(r) for r in rows]

    def find_genre_share_rows(
        self,
        granularity: str,
        game_type: str = "game",
        limit: int = 100,
    ) -> list[dict]:
        # limit controls the number of *periods* returned, not rows. Because there
        # are multiple (period, genre) rows per period, we first collect the N most
        # recent periods and then return all genre rows within them.
        type_clause = self._type_clause(game_type)
        rows = self._fetchall(
            f"""
            WITH periods AS (
                SELECT DISTINCT DATE_TRUNC(%s, g.release_date) AS period
                FROM games g
                WHERE g.release_date IS NOT NULL
                  AND g.coming_soon = FALSE
                  {type_clause}
                  AND g.review_count >= 10
                ORDER BY 1 DESC
                LIMIT %s
            )
            SELECT
                p.period,
                gn.name AS genre,
                gn.slug AS genre_slug,
                COUNT(*) AS releases
            FROM games g
            JOIN game_genres gg ON gg.appid = g.appid
            JOIN genres gn ON gg.genre_id = gn.id
            JOIN periods p ON p.period = DATE_TRUNC(%s, g.release_date)
            WHERE g.release_date IS NOT NULL
              AND g.coming_soon = FALSE
              {type_clause}
              AND g.review_count >= 10
            GROUP BY 1, 2, 3
            ORDER BY 1, 4 DESC
            """,
            (granularity, limit, granularity),
        )
        return [dict(r) for r in rows]

    def find_velocity_distribution_rows(
        self,
        granularity: str,
        genre_slug: str | None = None,
        game_type: str = "game",
        limit: int = 100,
    ) -> list[dict]:
        params: list = [granularity]
        genre_join, genre_where = self._genre_join_and_filter(genre_slug, params)
        type_clause = self._type_clause(game_type)
        params.append(limit)

        rows = self._fetchall(
            f"""
            SELECT * FROM (
                SELECT
                    DATE_TRUNC(%s, g.release_date) AS period,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE COALESCE(g.review_velocity_lifetime,
                        g.review_count_english::numeric / NULLIF(CURRENT_DATE - g.release_date, 0))
                        < 1) AS velocity_under_1,
                    COUNT(*) FILTER (WHERE COALESCE(g.review_velocity_lifetime,
                        g.review_count_english::numeric / NULLIF(CURRENT_DATE - g.release_date, 0))
                        >= 1 AND COALESCE(g.review_velocity_lifetime,
                        g.review_count_english::numeric / NULLIF(CURRENT_DATE - g.release_date, 0))
                        < 10) AS velocity_1_10,
                    COUNT(*) FILTER (WHERE COALESCE(g.review_velocity_lifetime,
                        g.review_count_english::numeric / NULLIF(CURRENT_DATE - g.release_date, 0))
                        >= 10 AND COALESCE(g.review_velocity_lifetime,
                        g.review_count_english::numeric / NULLIF(CURRENT_DATE - g.release_date, 0))
                        < 50) AS velocity_10_50,
                    COUNT(*) FILTER (WHERE COALESCE(g.review_velocity_lifetime,
                        g.review_count_english::numeric / NULLIF(CURRENT_DATE - g.release_date, 0))
                        >= 50) AS velocity_50_plus
                FROM games g
                {genre_join}
                WHERE g.release_date IS NOT NULL
                  AND g.coming_soon = FALSE
                  {type_clause}
                  AND g.review_count >= 10
                  AND CURRENT_DATE - g.release_date > 0
                  {genre_where}
                GROUP BY 1
                ORDER BY 1 DESC
                LIMIT %s
            ) sub ORDER BY period
            """,
            tuple(params),
        )
        return [dict(r) for r in rows]

    def find_price_trend_rows(
        self,
        granularity: str,
        genre_slug: str | None = None,
        game_type: str = "game",
        limit: int = 100,
    ) -> list[dict]:
        params: list = [granularity]
        genre_join, genre_where = self._genre_join_and_filter(genre_slug, params)
        type_clause = self._type_clause(game_type)
        params.append(limit)

        rows = self._fetchall(
            f"""
            SELECT * FROM (
                SELECT
                    DATE_TRUNC(%s, g.release_date) AS period,
                    COUNT(*) AS total,
                    ROUND(AVG(g.price_usd) FILTER (WHERE NOT g.is_free), 2) AS avg_paid_price,
                    ROUND(AVG(g.price_usd), 2) AS avg_price_incl_free,
                    COUNT(*) FILTER (WHERE g.is_free) AS free_count
                FROM games g
                {genre_join}
                WHERE g.release_date IS NOT NULL
                  AND g.coming_soon = FALSE
                  {type_clause}
                  AND g.review_count >= 10
                  {genre_where}
                GROUP BY 1
                ORDER BY 1 DESC
                LIMIT %s
            ) sub ORDER BY period
            """,
            tuple(params),
        )
        return [dict(r) for r in rows]

    def find_ea_trend_rows(
        self,
        granularity: str,
        game_type: str = "game",
        limit: int = 100,
    ) -> list[dict]:
        type_clause = self._type_clause(game_type)
        rows = self._fetchall(
            f"""
            WITH ea_flags AS (
                SELECT appid, BOOL_OR(written_during_early_access) AS has_ea
                FROM reviews
                GROUP BY appid
            )
            SELECT * FROM (
                SELECT
                    DATE_TRUNC(%s, g.release_date) AS period,
                    COUNT(*) AS total_releases,
                    COUNT(*) FILTER (WHERE COALESCE(ef.has_ea, FALSE)) AS ea_count,
                    ROUND(
                        AVG(g.positive_pct) FILTER (WHERE COALESCE(ef.has_ea, FALSE)),
                        1
                    ) AS ea_avg_sentiment,
                    ROUND(
                        AVG(g.positive_pct) FILTER (WHERE NOT COALESCE(ef.has_ea, FALSE)),
                        1
                    ) AS non_ea_avg_sentiment
                FROM games g
                LEFT JOIN ea_flags ef ON ef.appid = g.appid
                WHERE g.release_date IS NOT NULL
                  AND g.coming_soon = FALSE
                  {type_clause}
                  AND g.review_count >= 10
                GROUP BY 1
                ORDER BY 1 DESC
                LIMIT %s
            ) sub ORDER BY period
            """,
            (granularity, limit),
        )
        return [dict(r) for r in rows]

    def find_platform_trend_rows(
        self,
        granularity: str,
        genre_slug: str | None = None,
        game_type: str = "game",
        limit: int = 100,
    ) -> list[dict]:
        params: list = [granularity]
        genre_join, genre_where = self._genre_join_and_filter(genre_slug, params)
        type_clause = self._type_clause(game_type)
        params.append(limit)

        rows = self._fetchall(
            f"""
            SELECT * FROM (
                SELECT
                    DATE_TRUNC(%s, g.release_date) AS period,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE (g.platforms->>'mac')::boolean) AS mac_count,
                    COUNT(*) FILTER (WHERE (g.platforms->>'linux')::boolean) AS linux_count,
                    COUNT(*) FILTER (WHERE g.deck_compatibility = 3) AS deck_verified,
                    COUNT(*) FILTER (WHERE g.deck_compatibility = 2) AS deck_playable,
                    COUNT(*) FILTER (WHERE g.deck_compatibility = 1) AS deck_unsupported
                FROM games g
                {genre_join}
                WHERE g.release_date IS NOT NULL
                  AND g.coming_soon = FALSE
                  {type_clause}
                  AND g.review_count >= 10
                  {genre_where}
                GROUP BY 1
                ORDER BY 1 DESC
                LIMIT %s
            ) sub ORDER BY period
            """,
            tuple(params),
        )
        return [dict(r) for r in rows]

    def find_engagement_depth_rows(
        self,
        granularity: str,
        genre_slug: str | None = None,
    ) -> list[dict]:
        slug = f"{granularity}:{genre_slug or 'all'}"
        row = self._fetchone(
            """
            SELECT insight_json
            FROM index_insights
            WHERE type = 'engagement_depth'
              AND slug = %s
            ORDER BY computed_at DESC
            LIMIT 1
            """,
            (slug,),
        )
        if row is None or row["insight_json"] is None:
            return []
        data = row["insight_json"]
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                return []
        return data if isinstance(data, list) else []

    def find_category_trend_rows(
        self,
        granularity: str,
        game_type: str = "game",
        limit: int = 100,
    ) -> list[dict]:
        # limit controls periods returned, not rows. Collect N periods first.
        type_clause = self._type_clause(game_type)
        rows = self._fetchall(
            f"""
            WITH periods AS (
                SELECT DISTINCT DATE_TRUNC(%s, g.release_date) AS period
                FROM games g
                WHERE g.release_date IS NOT NULL
                  AND g.coming_soon = FALSE
                  {type_clause}
                  AND g.review_count >= 10
                ORDER BY 1 DESC
                LIMIT %s
            )
            SELECT
                p.period,
                gc.category_name,
                COUNT(*) AS games_with_category
            FROM games g
            JOIN game_categories gc ON gc.appid = g.appid
            JOIN periods p ON p.period = DATE_TRUNC(%s, g.release_date)
            WHERE g.release_date IS NOT NULL
              AND g.coming_soon = FALSE
              {type_clause}
              AND g.review_count >= 10
              AND gc.category_name IN (
                'Single-player', 'Multi-player', 'Co-op', 'Steam Workshop',
                'VR Supported', 'Full controller support', 'Steam Cloud', 'Steam Achievements'
              )
            GROUP BY 1, 2
            ORDER BY 1, 3 DESC
            """,
            (granularity, limit, granularity),
        )
        return [dict(r) for r in rows]
