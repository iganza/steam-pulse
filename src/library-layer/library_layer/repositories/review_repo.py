"""ReviewRepository — pure SQL I/O for the reviews table."""

from __future__ import annotations

from datetime import date, datetime, timedelta

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
                        r.get("author_steamid", ""),
                        r["voted_up"],
                        r.get("playtime_hours", 0),
                        r.get("body", ""),
                        r.get("posted_at"),
                        r.get("language", ""),
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
        row = self._fetchone(
            "SELECT COUNT(*) AS cnt FROM reviews WHERE appid = %s", (appid,)
        )
        return int(row["cnt"]) if row else 0

    def find_by_appid(
        self, appid: int, limit: int = 100, offset: int = 0
    ) -> list[Review]:
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
            SELECT DATE_TRUNC('week', posted_at) AS week,
                   COUNT(*) AS total,
                   COUNT(CASE WHEN voted_up THEN 1 END) AS positive,
                   ROUND(COUNT(CASE WHEN voted_up THEN 1 END)::numeric / COUNT(*) * 100) AS pct_positive
            FROM reviews WHERE appid = %s AND posted_at IS NOT NULL
            GROUP BY 1 ORDER BY 1
            """,
            (appid,),
        )
        bucket_rows = self._fetchall(
            """
            SELECT
              CASE
                WHEN playtime_hours = 0     THEN '0h'
                WHEN playtime_hours < 2     THEN '<2h'
                WHEN playtime_hours < 10    THEN '2-10h'
                WHEN playtime_hours < 50    THEN '10-50h'
                WHEN playtime_hours < 200   THEN '50-200h'
                ELSE '200h+'
              END AS bucket,
              COUNT(*) AS reviews,
              ROUND(COUNT(CASE WHEN voted_up THEN 1 END)::numeric / COUNT(*) * 100) AS pct_positive
            FROM reviews WHERE appid = %s
            GROUP BY 1 ORDER BY MIN(playtime_hours)
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
            days_active = max(
                (date.today() - date.fromisoformat(timeline[0]["week"])).days, 1
            )
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
