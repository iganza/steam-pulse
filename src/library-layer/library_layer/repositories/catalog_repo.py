"""CatalogRepository — pure SQL I/O for the app_catalog table."""

from __future__ import annotations

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

    def find_pending_reviews(self, limit: int | None = None) -> list[CatalogEntry]:
        sql = "SELECT * FROM app_catalog WHERE review_status = 'pending' ORDER BY discovered_at"
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
        review_status: str | None = None,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_catalog (appid, name, meta_status, meta_crawled_at,
                                         review_count, review_status)
                VALUES (%s, %s, %s, NOW(), %s, %s)
                ON CONFLICT (appid) DO UPDATE SET
                    meta_status     = EXCLUDED.meta_status,
                    meta_crawled_at = NOW(),
                    review_count    = COALESCE(EXCLUDED.review_count, app_catalog.review_count),
                    review_status   = CASE
                        WHEN EXCLUDED.review_status IS NOT NULL
                            AND app_catalog.review_status NOT IN ('done', 'failed')
                        THEN EXCLUDED.review_status
                        ELSE app_catalog.review_status
                    END
                """,
                (
                    appid,
                    f"App {appid}",
                    status,
                    review_count,
                    review_status,
                ),
            )
        self.conn.commit()

    def set_review_status(self, appid: int, status: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE app_catalog SET review_status = %s, review_crawled_at = NOW()
                WHERE appid = %s
                """,
                (status, appid),
            )
        self.conn.commit()

    def status_summary(self) -> dict:
        """Return counts grouped by meta_status and review_status."""
        meta_rows = self._fetchall(
            "SELECT meta_status, COUNT(*) AS cnt FROM app_catalog GROUP BY meta_status"
        )
        review_rows = self._fetchall(
            "SELECT review_status, COUNT(*) AS cnt FROM app_catalog GROUP BY review_status"
        )
        return {
            "meta": {r["meta_status"]: int(r["cnt"]) for r in meta_rows},
            "review": {r["review_status"]: int(r["cnt"]) for r in review_rows},
        }
