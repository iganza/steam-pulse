"""ReviewRepository — pure SQL I/O for the reviews table."""

from __future__ import annotations

from datetime import datetime

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
                        appid, steam_review_id, voted_up, playtime_hours, body, posted_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (steam_review_id) DO UPDATE SET
                        voted_up       = EXCLUDED.voted_up,
                        playtime_hours = EXCLUDED.playtime_hours,
                        body           = EXCLUDED.body
                    """,
                    (
                        r["appid"],
                        r["steam_review_id"],
                        r["voted_up"],
                        r.get("playtime_hours", 0),
                        r.get("body", ""),
                        r.get("posted_at"),
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
