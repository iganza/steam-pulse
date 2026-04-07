"""AnalyticsService — business logic for catalog-wide analytics dashboard."""

from collections import defaultdict
from datetime import datetime

from library_layer.repositories.analytics_repo import AnalyticsRepository

VALID_GRANULARITIES = {"week", "month", "quarter", "year"}


class AnalyticsService:
    def __init__(self, analytics_repo: AnalyticsRepository) -> None:
        self._repo = analytics_repo

    def _validate_granularity(self, granularity: str) -> str:
        if granularity not in VALID_GRANULARITIES:
            raise ValueError(f"Invalid granularity: {granularity!r}")
        return granularity

    def _format_period(self, period: datetime, granularity: str) -> str:
        if granularity == "year":
            return str(period.year)
        if granularity == "quarter":
            q = (period.month - 1) // 3 + 1
            return f"{period.year}-Q{q}"
        if granularity == "week":
            iso_year, week, _ = period.isocalendar()
            return f"{iso_year}-W{week:02d}"
        # month
        return f"{period.year}-{period.month:02d}"

    def _compute_trend(self, values: list[int | float]) -> str:
        """Compare mean of last 3 values vs overall mean."""
        if len(values) < 4:
            return "stable"
        overall = sum(values) / len(values)
        if overall == 0:
            return "stable"
        recent = sum(values[-3:]) / 3
        ratio = recent / overall
        if ratio > 1.2:
            return "increasing"
        if ratio < 0.8:
            return "decreasing"
        return "stable"

    def _safe_pct(self, part: int | float, total: int | float) -> float:
        if not total:
            return 0.0
        return round(part / total * 100, 1)

    # -------------------------------------------------------------------
    # Public service methods
    # -------------------------------------------------------------------

    def get_release_volume(
        self,
        granularity: str = "month",
        genre_slug: str | None = None,
        tag_slug: str | None = None,
        game_type: str = "game",
        limit: int = 100,
    ) -> dict:
        g = self._validate_granularity(granularity)
        rows = self._repo.find_release_volume_rows(g, genre_slug, tag_slug, game_type, limit)
        periods = []
        for r in rows:
            periods.append(
                {
                    "period": self._format_period(r["period"], g),
                    "releases": int(r["releases"]),
                    "avg_steam_pct": float(r["avg_steam_pct"])
                    if r["avg_steam_pct"] is not None
                    else None,
                    "avg_reviews": int(r["avg_reviews"]) if r["avg_reviews"] is not None else 0,
                    "free_count": int(r["free_count"]),
                }
            )

        release_counts = [p["releases"] for p in periods]
        total = sum(release_counts)
        avg_per = round(total / len(release_counts)) if release_counts else 0
        trend = self._compute_trend(release_counts)

        filt: dict = {}
        if genre_slug:
            filt["genre"] = genre_slug
        if tag_slug:
            filt["tag"] = tag_slug

        return {
            "granularity": g,
            "filter": filt,
            "periods": periods,
            "summary": {"total_releases": total, "avg_per_period": avg_per, "trend": trend},
        }

    def get_sentiment_distribution(
        self,
        granularity: str = "month",
        genre_slug: str | None = None,
        game_type: str = "game",
        limit: int = 100,
    ) -> dict:
        g = self._validate_granularity(granularity)
        rows = self._repo.find_sentiment_distribution_rows(g, genre_slug, game_type, limit)
        periods = []
        for r in rows:
            total = int(r["total"])
            periods.append(
                {
                    "period": self._format_period(r["period"], g),
                    "total": total,
                    "positive_count": int(r["positive_count"]),
                    "mixed_count": int(r["mixed_count"]),
                    "negative_count": int(r["negative_count"]),
                    "positive_pct": self._safe_pct(int(r["positive_count"]), total),
                    "avg_steam_pct": float(r["avg_steam_pct"])
                    if r["avg_steam_pct"] is not None
                    else None,
                    "avg_metacritic": float(r["avg_metacritic"])
                    if r["avg_metacritic"] is not None
                    else None,
                }
            )
        return {"granularity": g, "periods": periods}

    def get_genre_share(
        self,
        granularity: str = "year",
        top_n: int = 5,
        game_type: str = "game",
        limit: int = 100,
    ) -> dict:
        g = self._validate_granularity(granularity)
        rows = self._repo.find_genre_share_rows(g, game_type, limit)

        # Rank genres by total volume across all periods
        genre_totals: dict[str, int] = defaultdict(int)
        period_genre_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        period_totals: dict[str, int] = defaultdict(int)

        for r in rows:
            period_key = self._format_period(r["period"], g)
            genre = r["genre"]
            count = int(r["releases"])
            genre_totals[genre] += count
            period_genre_counts[period_key][genre] += count
            period_totals[period_key] += count

        top_genres = sorted(genre_totals.keys(), key=lambda x: genre_totals[x], reverse=True)[
            :top_n
        ]
        genre_labels = [*top_genres, "Other"]

        periods = []
        for period_key in sorted(period_genre_counts.keys()):
            total = period_totals[period_key]
            shares: dict[str, float] = {}
            other = 0
            for genre, count in period_genre_counts[period_key].items():
                if genre in top_genres:
                    shares[genre] = round(count / total, 2) if total else 0
                else:
                    other += count
            shares["Other"] = round(other / total, 2) if total else 0
            periods.append({"period": period_key, "total": total, "shares": shares})

        return {"granularity": g, "genres": genre_labels, "periods": periods}

    def get_velocity_distribution(
        self,
        granularity: str = "month",
        genre_slug: str | None = None,
        game_type: str = "game",
        limit: int = 100,
    ) -> dict:
        g = self._validate_granularity(granularity)
        rows = self._repo.find_velocity_distribution_rows(g, genre_slug, game_type, limit)
        periods = []
        for r in rows:
            periods.append(
                {
                    "period": self._format_period(r["period"], g),
                    "total": int(r["total"]),
                    "velocity_under_1": int(r["velocity_under_1"]),
                    "velocity_1_10": int(r["velocity_1_10"]),
                    "velocity_10_50": int(r["velocity_10_50"]),
                    "velocity_50_plus": int(r["velocity_50_plus"]),
                }
            )
        return {"granularity": g, "periods": periods}

    def get_price_trend(
        self,
        granularity: str = "year",
        genre_slug: str | None = None,
        game_type: str = "game",
        limit: int = 100,
    ) -> dict:
        g = self._validate_granularity(granularity)
        rows = self._repo.find_price_trend_rows(g, genre_slug, game_type, limit)
        periods = []
        for r in rows:
            total = int(r["total"])
            free_count = int(r["free_count"])
            periods.append(
                {
                    "period": self._format_period(r["period"], g),
                    "total": total,
                    "avg_paid_price": float(r["avg_paid_price"])
                    if r["avg_paid_price"] is not None
                    else None,
                    "avg_price_incl_free": float(r["avg_price_incl_free"])
                    if r["avg_price_incl_free"] is not None
                    else None,
                    "free_count": free_count,
                    "free_pct": self._safe_pct(free_count, total),
                }
            )
        return {"granularity": g, "periods": periods}

    def get_ea_trend(
        self,
        granularity: str = "year",
        game_type: str = "game",
        limit: int = 100,
    ) -> dict:
        g = self._validate_granularity(granularity)
        rows = self._repo.find_ea_trend_rows(g, game_type, limit)
        periods = []
        for r in rows:
            total = int(r["total_releases"])
            ea_count = int(r["ea_count"])
            periods.append(
                {
                    "period": self._format_period(r["period"], g),
                    "total_releases": total,
                    "ea_count": ea_count,
                    "ea_pct": self._safe_pct(ea_count, total),
                    "ea_avg_steam_pct": float(r["ea_avg_steam_pct"])
                    if r["ea_avg_steam_pct"] is not None
                    else None,
                    "non_ea_avg_steam_pct": float(r["non_ea_avg_steam_pct"])
                    if r["non_ea_avg_steam_pct"] is not None
                    else None,
                }
            )
        return {"granularity": g, "periods": periods}

    def get_platform_trend(
        self,
        granularity: str = "year",
        genre_slug: str | None = None,
        game_type: str = "game",
        limit: int = 100,
    ) -> dict:
        g = self._validate_granularity(granularity)
        rows = self._repo.find_platform_trend_rows(g, genre_slug, game_type, limit)
        periods = []
        for r in rows:
            total = int(r["total"])
            periods.append(
                {
                    "period": self._format_period(r["period"], g),
                    "total": total,
                    "mac_pct": self._safe_pct(int(r["mac_count"]), total),
                    "linux_pct": self._safe_pct(int(r["linux_count"]), total),
                    "deck_verified_pct": self._safe_pct(int(r["deck_verified"]), total),
                    "deck_playable_pct": self._safe_pct(int(r["deck_playable"]), total),
                    "deck_unsupported_pct": self._safe_pct(int(r["deck_unsupported"]), total),
                }
            )
        return {"granularity": g, "periods": periods}

    def get_engagement_depth(
        self,
        granularity: str = "year",
        genre_slug: str | None = None,
        limit: int = 100,
    ) -> dict:
        g = self._validate_granularity(granularity)
        rows = self._repo.find_engagement_depth_rows(g, genre_slug)
        if not rows:
            return {"granularity": g, "data_available": False, "periods": []}

        periods = []
        for r in rows[:limit]:
            total = int(r.get("total_reviews", 0))
            if total == 0:
                continue
            raw_period = r.get("period", "")
            try:
                period_dt = datetime.fromisoformat(str(raw_period)) if raw_period else None
                formatted_period = (
                    self._format_period(period_dt, g) if period_dt else str(raw_period)
                )
            except (ValueError, TypeError):
                formatted_period = str(raw_period)
            periods.append(
                {
                    "period": formatted_period,
                    "total_reviews": total,
                    "playtime_under_2h_pct": self._safe_pct(
                        int(r.get("playtime_under_2h", 0)), total
                    ),
                    "playtime_2_10h_pct": self._safe_pct(int(r.get("playtime_2_10h", 0)), total),
                    "playtime_10_50h_pct": self._safe_pct(int(r.get("playtime_10_50h", 0)), total),
                    "playtime_50_200h_pct": self._safe_pct(
                        int(r.get("playtime_50_200h", 0)), total
                    ),
                    "playtime_200h_plus_pct": self._safe_pct(
                        int(r.get("playtime_200h_plus", 0)), total
                    ),
                }
            )
        return {"granularity": g, "data_available": bool(periods), "periods": periods}

    def get_category_trend(
        self,
        granularity: str = "year",
        top_n: int = 4,
        game_type: str = "game",
        limit: int = 100,
    ) -> dict:
        g = self._validate_granularity(granularity)
        cat_rows = self._repo.find_category_trend_rows(g, game_type, limit)
        vol_rows = self._repo.find_release_volume_rows(g, game_type=game_type, limit=limit)

        # Build period totals from release volume
        period_totals: dict[str, int] = {}
        for r in vol_rows:
            period_totals[self._format_period(r["period"], g)] = int(r["releases"])

        # Aggregate category counts by period
        cat_totals: dict[str, int] = defaultdict(int)
        period_cat_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in cat_rows:
            period_key = self._format_period(r["period"], g)
            cat = r["category_name"]
            count = int(r["games_with_category"])
            cat_totals[cat] += count
            period_cat_counts[period_key][cat] += count

        top_cats = sorted(cat_totals.keys(), key=lambda x: cat_totals[x], reverse=True)[:top_n]

        periods = []
        for period_key in sorted(period_cat_counts.keys()):
            total = period_totals.get(period_key, 0)
            adoption: dict[str, float] = {}
            for cat in top_cats:
                count = period_cat_counts[period_key].get(cat, 0)
                adoption[cat] = round(count / total, 2) if total else 0
            periods.append({"period": period_key, "total": total, "adoption": adoption})

        return {"granularity": g, "categories": top_cats, "periods": periods}
