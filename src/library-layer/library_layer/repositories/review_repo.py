"""ReviewRepository — pure SQL I/O for the reviews table."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from library_layer.models.review import Review
from library_layer.repositories.base import BaseRepository


class ReviewRepository(BaseRepository):
    """CRUD operations for the reviews table."""

    def bulk_upsert(self, reviews: list[dict]) -> int:
        """INSERT ... ON CONFLICT (steam_review_id) DO UPDATE.

        Returns:
            Number of rows processed (not deduplicated count).
        """
        if not reviews:
            return 0
        upserted = 0
        with self.conn.cursor() as cur:
            for r in reviews:
                cur.execute(
                    """
                    INSERT INTO reviews (
                        appid, steam_review_id, author_steamid, voted_up, playtime_hours,
                        body, posted_at, language, votes_helpful, votes_funny,
                        written_during_early_access, received_for_free
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (steam_review_id) DO UPDATE SET
                        voted_up                    = EXCLUDED.voted_up,
                        playtime_hours              = EXCLUDED.playtime_hours,
                        body                        = EXCLUDED.body,
                        author_steamid              = EXCLUDED.author_steamid,
                        language                    = EXCLUDED.language,
                        votes_helpful               = EXCLUDED.votes_helpful,
                        votes_funny                 = EXCLUDED.votes_funny,
                        written_during_early_access = EXCLUDED.written_during_early_access,
                        received_for_free           = EXCLUDED.received_for_free
                    """,
                    (
                        r["appid"],
                        r["steam_review_id"],
                        r.get("author_steamid"),
                        r["voted_up"],
                        r.get("playtime_hours", 0),
                        r.get("body", ""),
                        r.get("posted_at"),
                        r.get("language"),
                        r.get("votes_helpful", 0),
                        r.get("votes_funny", 0),
                        r.get("written_during_early_access", False),
                        r.get("received_for_free", False),
                    ),
                )
                upserted += 1
        self.conn.commit()
        return upserted

    def count_by_appid(self, appid: int) -> int:
        row = self._fetchone("SELECT COUNT(*) AS cnt FROM reviews WHERE appid = %s", (appid,))
        return int(row["cnt"]) if row else 0

    def find_by_appid(self, appid: int, limit: int = 100, offset: int = 0) -> list[Review]:
        rows = self._fetchall(
            """
            SELECT * FROM reviews
            WHERE appid = %s
            ORDER BY posted_at DESC NULLS LAST
            LIMIT %s OFFSET %s
            """,
            (appid, limit, offset),
        )
        return [Review.model_validate(dict(r)) for r in rows]

    def latest_posted_at(self, appid: int) -> datetime | None:
        row = self._fetchone(
            "SELECT MAX(posted_at) AS latest FROM reviews WHERE appid = %s", (appid,)
        )
        return row["latest"] if row else None

    def find_review_stats(self, appid: int) -> dict:
        """Return timeline (weekly) and playtime-bucket sentiment stats."""
        timeline_rows = self._fetchall(
            """
            SELECT DATE_TRUNC('week', r.posted_at) AS week,
                   COUNT(*) AS total,
                   COUNT(CASE WHEN r.voted_up THEN 1 END) AS positive,
                   ROUND(COUNT(CASE WHEN r.voted_up THEN 1 END)::numeric / COUNT(*) * 100) AS pct_positive
            FROM reviews r
            JOIN games g ON g.appid = r.appid
            WHERE r.appid = %s
              AND r.posted_at IS NOT NULL
              AND (g.release_date IS NULL OR r.posted_at >= g.release_date)
            GROUP BY 1 ORDER BY 1
            """,
            (appid,),
        )
        bucket_rows = self._fetchall(
            """
            SELECT
              CASE
                WHEN r.playtime_hours = 0     THEN '0h'
                WHEN r.playtime_hours < 2     THEN '<2h'
                WHEN r.playtime_hours < 10    THEN '2-10h'
                WHEN r.playtime_hours < 50    THEN '10-50h'
                WHEN r.playtime_hours < 200   THEN '50-200h'
                ELSE '200h+'
              END AS bucket,
              COUNT(*) AS reviews,
              ROUND(COUNT(CASE WHEN r.voted_up THEN 1 END)::numeric / COUNT(*) * 100) AS pct_positive
            FROM reviews r
            JOIN games g ON g.appid = r.appid
            WHERE r.appid = %s
              AND (g.release_date IS NULL OR r.posted_at >= g.release_date)
            GROUP BY 1 ORDER BY MIN(r.playtime_hours)
            """,
            (appid,),
        )

        timeline = [
            {
                "week": str(r["week"].date()),
                "total": int(r["total"]),
                "positive": int(r["positive"]),
                "pct_positive": int(r["pct_positive"]),
            }
            for r in timeline_rows
            if r["week"]
        ]

        total_reviews = sum(t["total"] for t in timeline)
        if timeline:
            days_active = max((date.today() - date.fromisoformat(timeline[0]["week"])).days, 1)
            reviews_per_day = round(total_reviews / days_active, 1)
            cutoff = (date.today() - timedelta(days=30)).isoformat()
            reviews_last_30 = sum(t["total"] for t in timeline if t["week"] >= cutoff)
        else:
            reviews_per_day = 0.0
            reviews_last_30 = 0

        return {
            "timeline": timeline,
            "playtime_buckets": [
                {
                    "bucket": r["bucket"],
                    "reviews": int(r["reviews"]),
                    "pct_positive": int(r["pct_positive"]),
                }
                for r in bucket_rows
            ],
            "review_velocity": {
                "reviews_per_day": reviews_per_day,
                "reviews_last_30_days": reviews_last_30,
            },
        }

    def find_playtime_sentiment(self, appid: int) -> dict:
        """Finer-grained playtime x sentiment with churn wall detection."""
        bucket_rows = self._fetchall(
            """
            SELECT
                CASE
                    WHEN r.playtime_hours IS NULL THEN 'unknown'
                    WHEN r.playtime_hours = 0 THEN '0h'
                    WHEN r.playtime_hours < 1 THEN '<1h'
                    WHEN r.playtime_hours < 2 THEN '1-2h'
                    WHEN r.playtime_hours < 5 THEN '2-5h'
                    WHEN r.playtime_hours < 10 THEN '5-10h'
                    WHEN r.playtime_hours < 20 THEN '10-20h'
                    WHEN r.playtime_hours < 50 THEN '20-50h'
                    WHEN r.playtime_hours < 100 THEN '50-100h'
                    WHEN r.playtime_hours < 200 THEN '100-200h'
                    WHEN r.playtime_hours < 500 THEN '200-500h'
                    ELSE '500h+'
                END AS bucket,
                MIN(r.playtime_hours) AS bucket_min,
                COUNT(*) AS total,
                COUNT(CASE WHEN r.voted_up THEN 1 END) AS positive,
                COUNT(CASE WHEN NOT r.voted_up THEN 1 END) AS negative,
                ROUND(COUNT(CASE WHEN r.voted_up THEN 1 END)::numeric
                      / NULLIF(COUNT(*), 0) * 100, 1) AS pct_positive
            FROM reviews r
            JOIN games g ON g.appid = r.appid
            WHERE r.appid = %s
              AND (g.release_date IS NULL OR r.posted_at >= g.release_date)
            GROUP BY 1
            ORDER BY MIN(r.playtime_hours)
            """,
            (appid,),
        )

        median_row = self._fetchone(
            """
            SELECT (PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r.playtime_hours))::numeric AS median_playtime,
                   g.price_usd, g.is_free
            FROM reviews r
            JOIN games g ON g.appid = r.appid
            WHERE r.appid = %s
              AND r.playtime_hours IS NOT NULL
              AND (g.release_date IS NULL OR r.posted_at >= g.release_date)
            GROUP BY g.price_usd, g.is_free
            """,
            (appid,),
        )

        buckets = [
            {
                "bucket": r["bucket"],
                "total": int(r["total"]),
                "positive": int(r["positive"]),
                "negative": int(r["negative"]),
                "pct_positive": float(r["pct_positive"]) if r["pct_positive"] is not None else 0.0,
            }
            for r in bucket_rows
        ]

        # Churn wall: first bucket where pct_positive drops >= 10 pts from previous
        # (both buckets must have >= 20 reviews — fragile metric, needs strong evidence)
        known_buckets = [b for b in buckets if b["bucket"] != "unknown"]
        churn_point: dict[str, Any] | None = None
        for i in range(1, len(known_buckets)):
            prev = known_buckets[i - 1]
            curr = known_buckets[i]
            if prev["total"] >= 20 and curr["total"] >= 20:
                delta = curr["pct_positive"] - prev["pct_positive"]
                if delta <= -10:
                    churn_point = {
                        "bucket": curr["bucket"],
                        "drop_from": prev["pct_positive"],
                        "drop_to": curr["pct_positive"],
                        "delta": round(delta, 1),
                    }
                    break

        median_playtime = (
            float(median_row["median_playtime"])
            if median_row and median_row["median_playtime"] is not None
            else 0.0
        )
        value_score: float | None = None
        if median_row and not median_row["is_free"] and median_row["price_usd"]:
            price = float(median_row["price_usd"])
            if price > 0:
                value_score = round(median_playtime / price, 2)

        return {
            "buckets": buckets,
            "churn_point": churn_point,
            "median_playtime_hours": median_playtime,
            "value_score": value_score,
        }

    def find_early_access_impact(self, appid: int) -> dict:
        """Compare EA-era reviews vs. post-launch reviews."""
        rows = self._fetchall(
            """
            SELECT
                written_during_early_access AS is_ea,
                COUNT(*) AS total,
                COUNT(CASE WHEN voted_up THEN 1 END) AS positive,
                ROUND(COUNT(CASE WHEN voted_up THEN 1 END)::numeric
                      / NULLIF(COUNT(*), 0) * 100, 1) AS pct_positive,
                ROUND(AVG(playtime_hours), 1) AS avg_playtime
            FROM reviews
            WHERE appid = %s
            GROUP BY written_during_early_access
            """,
            (appid,),
        )

        ea_data: dict | None = None
        post_data: dict | None = None
        for r in rows:
            entry = {
                "total": int(r["total"]),
                "positive": int(r["positive"]),
                "pct_positive": float(r["pct_positive"]) if r["pct_positive"] is not None else 0.0,
                "avg_playtime": float(r["avg_playtime"]) if r["avg_playtime"] is not None else 0.0,
            }
            if r["is_ea"]:
                ea_data = entry
            else:
                post_data = entry

        ea_count = ea_data["total"] if ea_data else 0
        post_count = post_data["total"] if post_data else 0

        if ea_data is None:
            return {
                "has_ea_reviews": False,
                "early_access": None,
                "post_launch": post_data,
                "impact_delta": None,
                "verdict": "no_ea",
                "ea_reviews": ea_count,
                "post_reviews": post_count,
                "reliable": False,
            }

        if post_data is None:
            return {
                "has_ea_reviews": True,
                "early_access": ea_data,
                "post_launch": None,
                "impact_delta": None,
                "verdict": "no_post",
                "ea_reviews": ea_count,
                "post_reviews": post_count,
                "reliable": False,
            }

        delta = post_data["pct_positive"] - ea_data["pct_positive"]
        if delta >= 5:
            verdict = "improved"
        elif delta <= -5:
            verdict = "declined"
        else:
            verdict = "stable"

        return {
            "has_ea_reviews": True,
            "early_access": ea_data,
            "post_launch": post_data,
            "impact_delta": round(delta, 1),
            "verdict": verdict,
            "ea_reviews": ea_count,
            "post_reviews": post_count,
            "reliable": ea_count >= 50 and post_count >= 50,
        }

    def find_review_velocity(self, appid: int) -> dict:
        """Monthly review volume trend over last 24 months."""
        rows = self._fetchall(
            """
            SELECT
                DATE_TRUNC('month', posted_at) AS month,
                COUNT(*) AS total,
                COUNT(CASE WHEN voted_up THEN 1 END) AS positive,
                ROUND(COUNT(CASE WHEN voted_up THEN 1 END)::numeric
                      / NULLIF(COUNT(*), 0) * 100, 1) AS pct_positive
            FROM reviews
            WHERE appid = %s AND posted_at >= NOW() - INTERVAL '24 months'
            GROUP BY 1
            ORDER BY 1
            """,
            (appid,),
        )

        monthly = [
            {
                "month": r["month"].strftime("%Y-%m") if r["month"] else None,
                "total": int(r["total"]),
                "positive": int(r["positive"]),
                "pct_positive": float(r["pct_positive"]) if r["pct_positive"] is not None else 0.0,
            }
            for r in rows
            if r["month"]
        ]

        if not monthly:
            return {
                "monthly": [],
                "smoothed": [],
                "summary": {
                    "avg_monthly": 0.0,
                    "last_30_days": 0,
                    "last_3_months_avg": 0.0,
                    "peak_month": None,
                    "trend": "stable",
                },
            }

        last_30_row = self._fetchone(
            "SELECT COUNT(*) AS total FROM reviews WHERE appid = %s AND posted_at >= NOW() - INTERVAL '30 days'",
            (appid,),
        )
        last_30_days = int(last_30_row["total"]) if last_30_row else 0

        # avg_monthly excludes months with <5 reviews (early/dead months distort the mean)
        meaningful_totals = [m["total"] for m in monthly if m["total"] >= 5]
        avg_monthly = (
            round(sum(meaningful_totals) / len(meaningful_totals), 1) if meaningful_totals else 0.0
        )
        totals = [m["total"] for m in monthly]
        last_3_avg = round(sum(totals[-3:]) / min(3, len(totals)), 1)
        peak = max(monthly, key=lambda m: m["total"])

        # 3-month centered rolling average for charting
        smoothed: list[dict] = []
        for i, m in enumerate(monthly):
            window = monthly[max(0, i - 1) : i + 2]
            avg = round(sum(w["total"] for w in window) / len(window), 1)
            smoothed.append({"month": m["month"], "total_smoothed": avg})

        if avg_monthly > 0 and last_3_avg > avg_monthly * 1.2:
            trend = "accelerating"
        elif avg_monthly > 0 and last_3_avg < avg_monthly * 0.8:
            trend = "decelerating"
        else:
            trend = "stable"

        return {
            "monthly": monthly,
            "smoothed": smoothed,
            "summary": {
                "avg_monthly": avg_monthly,
                "last_30_days": last_30_days,
                "last_3_months_avg": last_3_avg,
                "peak_month": {"month": peak["month"], "total": peak["total"]},
                "trend": trend,
            },
        }

    def find_top_reviews(self, appid: int, sort: str = "helpful", limit: int = 10) -> list:
        """Top reviews by helpfulness or humor votes.

        Whitelist prevents SQL injection — order_col is never user input directly.
        """
        if sort not in ("helpful", "funny"):
            sort = "helpful"
        order_col = "votes_helpful" if sort == "helpful" else "votes_funny"
        rows = self._fetchall(
            f"""
            SELECT steam_review_id, voted_up, playtime_hours,
                   LEFT(body, 500) AS body_preview,
                   votes_helpful, votes_funny, posted_at,
                   written_during_early_access, received_for_free
            FROM reviews
            WHERE appid = %s AND {order_col} > 0
            ORDER BY {order_col} DESC
            LIMIT %s
            """,
            (appid, limit),
        )
        return [
            {
                "steam_review_id": r["steam_review_id"],
                "voted_up": r["voted_up"],
                "playtime_hours": r["playtime_hours"],
                "body_preview": r["body_preview"],
                "votes_helpful": r["votes_helpful"],
                "votes_funny": r["votes_funny"],
                "posted_at": r["posted_at"].isoformat() if r["posted_at"] else None,
                "written_during_early_access": r["written_during_early_access"],
                "received_for_free": r["received_for_free"],
            }
            for r in rows
        ]
