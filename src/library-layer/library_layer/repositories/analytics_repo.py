"""AnalyticsRepository — cross-cutting analytics queries spanning multiple tables."""

import json

from library_layer.analytics.metrics import get_metric
from library_layer.repositories.base import BaseRepository
from psycopg2 import sql

_MONTH_NAMES = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


class AnalyticsRepository(BaseRepository):
    """Cross-cutting analytics queries spanning games, reviews, genres, and tags."""

    def _resolve_genre_name(self, genre_slug: str) -> str:
        """Look up the display name for a genre slug from the base table."""
        row = self._fetchone("SELECT name FROM genres WHERE slug = %s", (genre_slug,))
        return row["name"] if row else genre_slug

    def _resolve_tag_name(self, tag_slug: str) -> str:
        """Look up the display name for a tag slug from the base table."""
        row = self._fetchone("SELECT name FROM tags WHERE slug = %s", (tag_slug,))
        return row["name"] if row else tag_slug

    def find_price_positioning(self, genre_slug: str) -> dict:
        """Price distribution + sentiment correlation within a genre (from matview)."""
        dist_rows = self._fetchall(
            """
            SELECT genre_name, price_range, game_count, avg_steam_pct, median_price,
                   revenue_q1, revenue_median, revenue_q3, revenue_sample_size
            FROM mv_price_positioning
            WHERE genre_slug = %s
            ORDER BY median_price
            """,
            (genre_slug,),
        )

        genre_name = (
            dist_rows[0]["genre_name"] if dist_rows else self._resolve_genre_name(genre_slug)
        )

        distribution = [
            {
                "price_range": r["price_range"],
                "game_count": int(r["game_count"]),
                "avg_steam_pct": float(r["avg_steam_pct"])
                if r["avg_steam_pct"] is not None
                else None,
                "median_price": float(r["median_price"]) if r["median_price"] is not None else 0.0,
                # Boxleiter v1 gross revenue quartiles (pre-Steam-cut, +/-50%).
                # Precomputed in mv_price_positioning (see migration 0029).
                "revenue_quartiles": {
                    "q1": float(r["revenue_q1"]) if r["revenue_q1"] is not None else None,
                    "median": float(r["revenue_median"])
                    if r["revenue_median"] is not None
                    else None,
                    "q3": float(r["revenue_q3"]) if r["revenue_q3"] is not None else None,
                    "sample_size": int(r["revenue_sample_size"] or 0),
                },
            }
            for r in dist_rows
        ]

        eligible = [
            d for d in distribution if d["game_count"] >= 10 and d["avg_steam_pct"] is not None
        ]
        sweet_spot = (
            max(eligible, key=lambda x: x["avg_steam_pct"])["price_range"] if eligible else None
        )

        # Summary stats from pre-computed matview (one row per genre).
        summary_row = self._fetchone(
            """
            SELECT avg_price, median_price, free_count, paid_count
            FROM mv_price_summary
            WHERE genre_slug = %s
            """,
            (genre_slug,),
        )

        return {
            "genre": genre_name,
            "genre_slug": genre_slug,
            "distribution": distribution,
            "summary": {
                "avg_price": float(summary_row["avg_price"])
                if summary_row and summary_row["avg_price"]
                else None,
                "median_price": float(summary_row["median_price"])
                if summary_row and summary_row["median_price"]
                else None,
                "free_count": int(summary_row["free_count"]) if summary_row else 0,
                "paid_count": int(summary_row["paid_count"]) if summary_row else 0,
                "sweet_spot": sweet_spot,
            },
        }

    def find_release_timing(self, genre_slug: str) -> dict:
        """Monthly release density and avg sentiment by month (from matview)."""
        rows = self._fetchall(
            """
            SELECT genre_name, month, releases, avg_steam_pct, avg_reviews
            FROM mv_release_timing
            WHERE genre_slug = %s
            ORDER BY month
            """,
            (genre_slug,),
        )
        genre_name = rows[0]["genre_name"] if rows else self._resolve_genre_name(genre_slug)

        monthly = [
            {
                "month": r["month"],
                "month_name": _MONTH_NAMES[r["month"]],
                "releases": int(r["releases"]),
                "avg_steam_pct": float(r["avg_steam_pct"])
                if r["avg_steam_pct"] is not None
                else None,
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

        has_steam_pct = [m for m in monthly if m["avg_steam_pct"] is not None]
        best_month = max(has_steam_pct, key=lambda x: x["avg_steam_pct"]) if has_steam_pct else None
        worst_month = (
            min(has_steam_pct, key=lambda x: x["avg_steam_pct"]) if has_steam_pct else None
        )
        quietest_month = min(monthly, key=lambda x: x["releases"])
        busiest_month = max(monthly, key=lambda x: x["releases"])

        def _summary(m: dict | None) -> dict | None:
            if m is None:
                return None
            return {
                "month": m["month"],
                "month_name": m["month_name"],
                "avg_steam_pct": m.get("avg_steam_pct"),
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
        """Platform support breakdown and sentiment by platform (from matview)."""
        row = self._fetchone(
            """
            SELECT genre_name, total, windows, mac, linux,
                   windows_avg_steam_pct, mac_avg_steam_pct, linux_avg_steam_pct
            FROM mv_platform_distribution
            WHERE genre_slug = %s
            """,
            (genre_slug,),
        )
        genre_name = row["genre_name"] if row else self._resolve_genre_name(genre_slug)

        if not row or not row["total"]:
            return {"genre": genre_name, "total_games": 0, "platforms": {}, "underserved": None}

        total = int(row["total"])

        def _pct(count: int) -> float:
            return round(count / total * 100, 1) if total else 0.0

        platforms = {
            "windows": {
                "count": int(row["windows"] or 0),
                "pct": _pct(int(row["windows"] or 0)),
                "avg_steam_pct": float(row["windows_avg_steam_pct"])
                if row["windows_avg_steam_pct"] is not None
                else None,
            },
            "mac": {
                "count": int(row["mac"] or 0),
                "pct": _pct(int(row["mac"] or 0)),
                "avg_steam_pct": float(row["mac_avg_steam_pct"])
                if row["mac_avg_steam_pct"] is not None
                else None,
            },
            "linux": {
                "count": int(row["linux"] or 0),
                "pct": _pct(int(row["linux"] or 0)),
                "avg_steam_pct": float(row["linux_avg_steam_pct"])
                if row["linux_avg_steam_pct"] is not None
                else None,
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
        """Game count per year for a specific tag (from matview)."""
        rows = self._fetchall(
            """
            SELECT tag_name, year, game_count, avg_steam_pct
            FROM mv_tag_trend
            WHERE tag_slug = %s
            ORDER BY year
            """,
            (tag_slug,),
        )
        tag_name = rows[0]["tag_name"] if rows else self._resolve_tag_name(tag_slug)

        yearly = [
            {
                "year": r["year"],
                "game_count": int(r["game_count"]),
                "avg_steam_pct": float(r["avg_steam_pct"])
                if r["avg_steam_pct"] is not None
                else None,
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
        return self._find_entity_portfolio("developer", developer_slug)

    def find_publisher_portfolio(self, publisher_slug: str) -> dict:
        """All games by a publisher with aggregate stats and sentiment trajectory."""
        return self._find_entity_portfolio("publisher", publisher_slug)

    def _find_entity_portfolio(self, entity: str, slug: str) -> dict:
        """Shared portfolio query for developer/publisher pages.

        `entity` must be either "developer" or "publisher" — it selects which
        slug column (developer_slug/publisher_slug) and display column
        (developer/publisher) to read from the games table.
        """
        if entity == "developer":
            slug_col = "developer_slug"
            name_col = "developer"
        elif entity == "publisher":
            slug_col = "publisher_slug"
            name_col = "publisher"
        else:
            raise ValueError(f"Unsupported entity: {entity}")

        games_rows = self._fetchall(
            f"""
            SELECT
                g.appid, g.name, g.slug, g.header_image,
                g.release_date, g.price_usd, g.is_free,
                g.review_count, g.positive_pct, g.review_score_desc,
                g.metacritic_score, g.achievements_total, g.{name_col} AS entity_name
            FROM games g
            WHERE g.{slug_col} = %s
            ORDER BY g.release_date DESC NULLS LAST
            """,
            (slug,),
        )

        summary_row = self._fetchone(
            f"""
            SELECT
                COUNT(*) AS total_games,
                SUM(g.review_count) AS total_reviews,
                ROUND(AVG(g.positive_pct), 1) AS avg_steam_pct,
                MIN(g.release_date) AS first_release,
                MAX(g.release_date) AS latest_release,
                ROUND(AVG(g.price_usd) FILTER (WHERE NOT g.is_free), 2) AS avg_price,
                COUNT(*) FILTER (WHERE g.is_free) AS free_games,
                COUNT(*) FILTER (WHERE g.positive_pct >= 70) AS well_received,
                COUNT(*) FILTER (WHERE g.positive_pct < 50) AS poorly_received
            FROM games g
            WHERE g.{slug_col} = %s
            """,
            (slug,),
        )

        entity_name = games_rows[0]["entity_name"] if games_rows else slug
        total_games = int(summary_row["total_games"]) if summary_row else 0
        overall_avg = (
            float(summary_row["avg_steam_pct"])
            if summary_row and summary_row["avg_steam_pct"] is not None
            else 0.0
        )

        # Sentiment trajectory: compare last-3 games avg vs overall avg
        ordered = sorted(
            [
                g
                for g in games_rows
                if g["release_date"] is not None and g["positive_pct"] is not None
            ],
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
            entity: entity_name,
            f"{entity}_slug": slug,
            "summary": {
                "total_games": total_games,
                "total_reviews": int(summary_row["total_reviews"])
                if summary_row and summary_row["total_reviews"]
                else 0,
                "avg_steam_pct": overall_avg,
                "first_release": str(summary_row["first_release"])
                if summary_row and summary_row["first_release"]
                else None,
                "latest_release": str(summary_row["latest_release"])
                if summary_row and summary_row["latest_release"]
                else None,
                "avg_price": float(summary_row["avg_price"])
                if summary_row and summary_row["avg_price"]
                else None,
                "free_games": int(summary_row["free_games"]) if summary_row else 0,
                "well_received": int(summary_row["well_received"]) if summary_row else 0,
                "poorly_received": int(summary_row["poorly_received"]) if summary_row else 0,
                "sentiment_trajectory": trajectory,
            },
            "games": games,
        }

    # -----------------------------------------------------------------------
    # Trend methods (analytics dashboard)
    #
    # All methods support game_type='game', 'dlc', or 'all' via the
    # game_type dimension baked into the mv_trend_* matviews.
    # find_trend_category_trend_rows() is a live query but applies the
    # same game_type filter.
    # -----------------------------------------------------------------------

    _VALID_GAME_TYPES: frozenset[str] = frozenset({"game", "dlc", "all"})

    def _trend_matview_query(
        self,
        *,
        columns: list[str],
        granularity: str,
        game_type: str,
        genre_slug: str | None,
        tag_slug: str | None,
        limit: int,
    ) -> list[dict]:
        """SELECT from the appropriate mv_trend_* matview with routing.

        Picks the right matview based on which filter is active:
          - neither genre nor tag → mv_trend_catalog
          - genre_slug set         → mv_trend_by_genre
          - tag_slug set           → mv_trend_by_tag

        game_type must be 'game', 'dlc', or 'all'.
        Combining genre_slug + tag_slug raises ValueError.
        """
        if game_type not in self._VALID_GAME_TYPES:
            raise ValueError(f"unsupported game_type={game_type!r}")
        genre_slug = genre_slug or None
        tag_slug = tag_slug or None
        if genre_slug is not None and tag_slug is not None:
            raise ValueError("combining genre and tag filters is not supported")

        if genre_slug is not None:
            table = "mv_trend_by_genre"
            filter_clause = sql.SQL("AND genre_slug = %s")
            filter_params: tuple = (genre_slug,)
        elif tag_slug is not None:
            table = "mv_trend_by_tag"
            filter_clause = sql.SQL("AND tag_slug = %s")
            filter_params = (tag_slug,)
        else:
            table = "mv_trend_catalog"
            filter_clause = sql.SQL("")
            filter_params = ()

        col_sql = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
        query = sql.SQL(
            """
            SELECT * FROM (
                SELECT period, {cols}
                FROM {table}
                WHERE granularity = %s
                  AND game_type = %s
                  {filter_clause}
                ORDER BY period DESC
                LIMIT %s
            ) sub ORDER BY period
            """
        ).format(
            cols=col_sql,
            table=sql.Identifier(table),
            filter_clause=filter_clause,
        )

        params: tuple = (granularity, game_type, *filter_params, limit)
        rows = self._fetchall(query, params)
        return [dict(r) for r in rows]

    # -- release volume -------------------------------------------------------

    def find_trend_release_volume_rows(
        self,
        granularity: str,
        game_type: str = "game",
        genre_slug: str | None = None,
        tag_slug: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return self._trend_matview_query(
            columns=["releases", "avg_steam_pct", "avg_reviews", "free_count"],
            granularity=granularity,
            game_type=game_type,
            genre_slug=genre_slug,
            tag_slug=tag_slug,
            limit=limit,
        )

    # -- sentiment distribution -----------------------------------------------

    def find_trend_sentiment_distribution_rows(
        self,
        granularity: str,
        game_type: str = "game",
        genre_slug: str | None = None,
        tag_slug: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        rows = self._trend_matview_query(
            columns=[
                "releases",
                "positive_count",
                "mixed_count",
                "negative_count",
                "avg_steam_pct",
                "avg_metacritic",
            ],
            granularity=granularity,
            game_type=game_type,
            genre_slug=genre_slug,
            tag_slug=tag_slug,
            limit=limit,
        )
        for r in rows:
            r["total"] = r.pop("releases")
        return rows

    # -- genre share ----------------------------------------------------------

    def find_trend_genre_share_rows(
        self,
        granularity: str,
        game_type: str = "game",
        limit: int = 100,
    ) -> list[dict]:
        if game_type not in self._VALID_GAME_TYPES:
            raise ValueError(f"unsupported game_type={game_type!r}")
        rows = self._fetchall(
            """
            SELECT mv.period, gn.name AS genre, mv.genre_slug, mv.releases
            FROM mv_trend_by_genre mv
            JOIN genres gn ON gn.slug = mv.genre_slug
            WHERE mv.granularity = %s
              AND mv.game_type = %s
              AND mv.period IN (
                  SELECT DISTINCT period
                  FROM mv_trend_by_genre
                  WHERE granularity = %s
                    AND game_type = %s
                  ORDER BY period DESC
                  LIMIT %s
              )
            ORDER BY mv.period, mv.releases DESC
            """,
            (granularity, game_type, granularity, game_type, limit),
        )
        return [dict(r) for r in rows]

    # -- velocity distribution ------------------------------------------------

    def find_trend_velocity_distribution_rows(
        self,
        granularity: str,
        game_type: str = "game",
        genre_slug: str | None = None,
        tag_slug: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        rows = self._trend_matview_query(
            columns=[
                "releases",
                "velocity_under_1",
                "velocity_1_10",
                "velocity_10_50",
                "velocity_50_plus",
            ],
            granularity=granularity,
            game_type=game_type,
            genre_slug=genre_slug,
            tag_slug=tag_slug,
            limit=limit,
        )
        for r in rows:
            r["total"] = r.pop("releases")
        return rows

    # -- price trend ----------------------------------------------------------

    def find_trend_price_trend_rows(
        self,
        granularity: str,
        game_type: str = "game",
        genre_slug: str | None = None,
        tag_slug: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        rows = self._trend_matview_query(
            columns=["releases", "avg_paid_price", "avg_price_incl_free", "free_count"],
            granularity=granularity,
            game_type=game_type,
            genre_slug=genre_slug,
            tag_slug=tag_slug,
            limit=limit,
        )
        for r in rows:
            r["total"] = r.pop("releases")
        return rows

    # -- EA trend -------------------------------------------------------------

    def find_trend_ea_trend_rows(
        self,
        granularity: str,
        game_type: str = "game",
        genre_slug: str | None = None,
        tag_slug: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        rows = self._trend_matview_query(
            columns=["releases", "ea_count", "ea_avg_steam_pct", "non_ea_avg_steam_pct"],
            granularity=granularity,
            game_type=game_type,
            genre_slug=genre_slug,
            tag_slug=tag_slug,
            limit=limit,
        )
        for r in rows:
            r["total_releases"] = r.pop("releases")
        return rows

    # -- platform trend -------------------------------------------------------

    def find_trend_platform_trend_rows(
        self,
        granularity: str,
        game_type: str = "game",
        genre_slug: str | None = None,
        tag_slug: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        rows = self._trend_matview_query(
            columns=[
                "releases",
                "mac_pct",
                "linux_pct",
                "deck_verified_pct",
                "deck_playable_pct",
                "deck_unsupported_pct",
            ],
            granularity=granularity,
            game_type=game_type,
            genre_slug=genre_slug,
            tag_slug=tag_slug,
            limit=limit,
        )
        for r in rows:
            r["total"] = r.pop("releases")
        return rows

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

    # -----------------------------------------------------------------------
    # Builder lens — generic metric query against pre-computed trend matviews
    # -----------------------------------------------------------------------

    def query_metrics(
        self,
        metric_ids: list[str],
        granularity: str,
        game_type: str = "game",
        genre_slug: str | None = None,
        tag_slug: str | None = None,
        limit: int = 24,
    ) -> list[dict]:
        """Generic metric query against the mv_trend_* matviews.

        Delegates to _trend_matview_query() for matview routing and filter
        validation (genre + tag combined raises ValueError). Returns rows
        as {"period": <datetime>, "<metric_id>": value, ...} sorted
        ascending by period. The service layer formats the period.
        """
        # All metrics in v1 share source=trend_matview — future sources (e.g.
        # engagement from index_insights) will add a merge step here.
        defs = [get_metric(mid) for mid in metric_ids]
        if not defs:
            raise ValueError("at least one metric is required")

        # De-duplicate column list while preserving metric_id → column mapping.
        columns: list[str] = []
        seen: set[str] = set()
        for d in defs:
            if d.column not in seen:
                columns.append(d.column)
                seen.add(d.column)

        rows = self._trend_matview_query(
            columns=columns,
            granularity=granularity,
            game_type=game_type,
            genre_slug=genre_slug,
            tag_slug=tag_slug,
            limit=limit,
        )

        # Rename columns from physical column → metric_id (1:1 in v1, but the
        # indirection lets a future metric alias a shared column).
        out: list[dict] = []
        for r in rows:
            row: dict = {"period": r["period"]}
            for d in defs:
                row[d.id] = r[d.column]
            out.append(row)
        return out

    def find_trend_category_trend_rows(
        self,
        granularity: str,
        game_type: str = "game",
        limit: int = 100,
    ) -> list[dict]:
        """Category adoption trend — remains a live query.

        No mv_trend_by_category matview exists. The hard-coded 8-category
        filter and low traffic make a dedicated matview unwarranted.
        Supports game_type='game', 'dlc', or 'all'.
        """
        if game_type not in self._VALID_GAME_TYPES:
            raise ValueError(f"unsupported game_type={game_type!r}")
        if game_type == "all":
            type_clause = "AND g.type IN ('game', 'dlc')"
        else:
            type_clause = f"AND g.type = '{game_type}'"
        # limit controls periods returned, not rows. Collect N periods first.
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
