"""CatalogRepository — pure SQL I/O for the app_catalog table."""

from __future__ import annotations

from datetime import UTC, datetime

import psycopg2.extras
from library_layer.models.catalog import CatalogEntry
from library_layer.repositories.base import BaseRepository


class CatalogRepository(BaseRepository):
    """CRUD operations for the app_catalog table."""

    def bulk_upsert(self, entries: list[dict]) -> int:
        """INSERT ... ON CONFLICT (appid) DO NOTHING.

        Returns:
            Number of new rows inserted.
        """
        if not entries:
            return 0
        with self.conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO app_catalog (appid, name)
                VALUES %s
                ON CONFLICT (appid) DO NOTHING
                """,
                [
                    (e["appid"], (e.get("name") or f"App {e['appid']}")[:500])
                    for e in entries
                ],
                page_size=1000,
            )
            new_rows = cur.rowcount
        self.conn.commit()
        return new_rows

    def find_by_appid(self, appid: int) -> CatalogEntry | None:
        row = self._fetchone(
            "SELECT * FROM app_catalog WHERE appid = %s", (appid,)
        )
        if row is None:
            return None
        return CatalogEntry.model_validate(dict(row))

    def find_pending_meta(self, limit: int | None = None) -> list[CatalogEntry]:
        sql = "SELECT * FROM app_catalog WHERE meta_status = 'pending' ORDER BY discovered_at"
        params: tuple = ()
        if limit is not None:
            sql += " LIMIT %s"
            params = (limit,)
        rows = self._fetchall(sql, params)
        return [CatalogEntry.model_validate(dict(r)) for r in rows]

    def set_meta_status(
        self,
        appid: int,
        status: str,
        review_count: int | None = None,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_catalog (appid, name, meta_status, meta_crawled_at, review_count)
                VALUES (%s, %s, %s, NOW(), %s)
                ON CONFLICT (appid) DO UPDATE SET
                    meta_status     = EXCLUDED.meta_status,
                    meta_crawled_at = NOW(),
                    review_count    = COALESCE(EXCLUDED.review_count, app_catalog.review_count)
                """,
                (appid, f"App {appid}", status, review_count),
            )
        self.conn.commit()

    def get_review_cursor(self, appid: int) -> str | None:
        """Return saved Steam review cursor. None = not started or complete."""
        row = self._fetchone(
            "SELECT review_cursor FROM app_catalog WHERE appid = %s", (appid,)
        )
        if row is None:
            return None
        return row["review_cursor"]

    def save_review_cursor(self, appid: int, cursor: str) -> None:
        """Persist a mid-stream cursor so the next batch can resume."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE app_catalog
                SET review_cursor = %s, review_cursor_updated_at = NOW()
                WHERE appid = %s
                """,
                (cursor, appid),
            )
        self.conn.commit()

    def mark_reviews_complete(self, appid: int, completed_at: datetime | None = None) -> None:
        """Clear in-flight cursor and record that all reviews have been fetched.

        Pass completed_at to use a specific watermark (e.g. the minimum timestamp_created
        from the early-stop batch) instead of NOW(). This avoids a gap where reviews posted
        *during* a long-running crawl would be skipped on the next re-crawl.
        """
        ts = completed_at or datetime.now(tz=UTC)
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE app_catalog
                SET review_cursor            = NULL,
                    review_cursor_updated_at = NOW(),
                    reviews_completed_at     = %s
                WHERE appid = %s
                """,
                (ts, appid),
            )
        self.conn.commit()

    def get_reviews_completed_at(self, appid: int) -> datetime | None:
        """Return when reviews were last fully exhausted. None = never completed."""
        row = self._fetchone(
            "SELECT reviews_completed_at FROM app_catalog WHERE appid = %s", (appid,)
        )
        return row["reviews_completed_at"] if row else None

    def get_reviews_target(self, appid: int) -> int | None:
        """Return the max-reviews target set at queue time. None = fetch all."""
        row = self._fetchone(
            "SELECT reviews_target FROM app_catalog WHERE appid = %s", (appid,)
        )
        if row is None:
            return None
        return row["reviews_target"]

    def set_reviews_target(self, appid: int, target: int | None) -> None:
        """Persist the stopping point for the review-fetch chain."""
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE app_catalog SET reviews_target = %s WHERE appid = %s",
                (target, appid),
            )
        self.conn.commit()

    def find_uncrawled_eligible(self, threshold: int, limit: int) -> list[int]:
        """Appids ready for first review crawl, ordered newest-released first."""
        rows = self._fetchall(
            """
            SELECT ac.appid
            FROM app_catalog ac
            JOIN games g ON g.appid = ac.appid
            WHERE ac.meta_status = 'done'
              AND ac.review_cursor IS NULL
              AND ac.reviews_completed_at IS NULL
              AND g.coming_soon = false
              AND g.review_count_english >= %s
              AND g.release_date IS NOT NULL
            ORDER BY g.release_date DESC
            LIMIT %s
            """,
            (threshold, limit),
        )
        return [row["appid"] for row in rows]

    def status_summary(self) -> dict:
        """Return counts grouped by meta_status."""
        meta_rows = self._fetchall(
            "SELECT meta_status, COUNT(*) AS cnt FROM app_catalog GROUP BY meta_status"
        )
        return {
            "meta": {r["meta_status"]: int(r["cnt"]) for r in meta_rows},
        }
