"""CatalogRepository — pure SQL I/O for the app_catalog table."""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg2.extras
from library_layer.models.catalog import CatalogEntry
from library_layer.repositories.base import BaseRepository


class CatalogRepository(BaseRepository):
    """CRUD operations for the app_catalog table."""

    def bulk_upsert(self, entries: list[dict]) -> int:
        """INSERT ... ON CONFLICT DO UPDATE for GetAppList metadata.

        Updates steam_last_modified and price_change_number on conflict
        (these change over time). Only overwrites with newer/non-NULL values
        (monotonic — never regresses).

        Uses RETURNING with an xmax check to distinguish inserts from updates
        without extra COUNT queries.

        Returns:
            Number of new rows inserted (not updated).
        """
        if not entries:
            return 0
        with self.conn.cursor() as cur:
            result = psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO app_catalog (appid, name, steam_last_modified, price_change_number)
                VALUES %s
                ON CONFLICT (appid) DO UPDATE SET
                    steam_last_modified = CASE
                        WHEN EXCLUDED.steam_last_modified IS NOT NULL
                         AND (app_catalog.steam_last_modified IS NULL
                              OR EXCLUDED.steam_last_modified > app_catalog.steam_last_modified)
                        THEN EXCLUDED.steam_last_modified
                        ELSE app_catalog.steam_last_modified
                    END,
                    price_change_number = CASE
                        WHEN EXCLUDED.price_change_number IS NOT NULL
                         AND (app_catalog.price_change_number IS NULL
                              OR EXCLUDED.price_change_number > app_catalog.price_change_number)
                        THEN EXCLUDED.price_change_number
                        ELSE app_catalog.price_change_number
                    END
                RETURNING (xmax = 0) AS inserted
                """,
                [
                    (
                        e["appid"],
                        (e.get("name") or f"App {e['appid']}")[:500],
                        e.get("steam_last_modified"),
                        e.get("price_change_number"),
                    )
                    for e in entries
                ],
                page_size=1000,
                fetch=True,
            )
            new_rows = sum(1 for row in result if row["inserted"])
        self.conn.commit()
        return new_rows

    def find_by_appid(self, appid: int) -> CatalogEntry | None:
        row = self._fetchone("SELECT * FROM app_catalog WHERE appid = %s", (appid,))
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

    def find_stale_meta(self, limit: int = 2000) -> list[CatalogEntry]:
        """Return catalog entries whose metadata is stale and should be re-crawled.

        Priority tiers (ordered most to least urgent):
          1. Early Access / coming-soon games → stale after 7 days
          2. Popular games (review_count >= 1000) → stale after 7 days
          3. Everything else with meta_status='done' → stale after 30 days

        NULLS FIRST ensures legacy rows (no meta_crawled_at) get refreshed first.
        """
        rows = self._fetchall(
            """
            SELECT ac.* FROM app_catalog ac
            LEFT JOIN games g ON g.appid = ac.appid
            LEFT JOIN game_genres gg ON gg.appid = ac.appid AND gg.genre_id = 70
            WHERE ac.meta_status = 'done'
              AND (
                ((g.coming_soon = TRUE OR gg.genre_id IS NOT NULL)
                  AND (ac.meta_crawled_at IS NULL OR ac.meta_crawled_at < NOW() - INTERVAL '7 days'))
                OR
                (ac.review_count >= 1000
                  AND (ac.meta_crawled_at IS NULL OR ac.meta_crawled_at < NOW() - INTERVAL '7 days'))
                OR
                (ac.meta_crawled_at IS NULL OR ac.meta_crawled_at < NOW() - INTERVAL '30 days')
              )
            ORDER BY
              CASE
                WHEN g.coming_soon = TRUE OR gg.genre_id IS NOT NULL THEN 0
                WHEN ac.review_count >= 1000 THEN 1
                ELSE 2
              END,
              ac.meta_crawled_at ASC NULLS FIRST
            LIMIT %s
            """,
            (limit,),
        )
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

    def mark_reviews_complete(self, appid: int, completed_at: datetime | None = None) -> None:
        """Record that all reviews have been fetched for this game.

        Pass completed_at to use a specific watermark (e.g. the minimum timestamp_created
        from the early-stop batch) instead of NOW(). This avoids a gap where reviews posted
        *during* a long-running crawl would be skipped on the next re-crawl.
        """
        ts = completed_at or datetime.now(tz=timezone.utc)
        with self.conn.cursor() as cur:
            cur.execute(
                """UPDATE app_catalog
                   SET reviews_completed_at = GREATEST(
                       COALESCE(reviews_completed_at, '1970-01-01'::timestamptz), %s
                   )
                   WHERE appid = %s""",
                (ts, appid),
            )
        self.conn.commit()

    def get_reviews_completed_at(self, appid: int) -> datetime | None:
        """Return when reviews were last fully exhausted. None = never completed."""
        row = self._fetchone(
            "SELECT reviews_completed_at FROM app_catalog WHERE appid = %s", (appid,)
        )
        return row["reviews_completed_at"] if row else None

    def mark_tags_crawled(self, appid: int) -> None:
        """Set tags_crawled_at = NOW() for the given appid."""
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE app_catalog SET tags_crawled_at = NOW() WHERE appid = %s",
                (appid,),
            )
        self.conn.commit()

    def mark_reviews_crawled(self, appid: int) -> None:
        """Set review_crawled_at = NOW() for the given appid."""
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE app_catalog SET review_crawled_at = NOW() WHERE appid = %s",
                (appid,),
            )
        self.conn.commit()

    def status_summary(self) -> dict:
        """Return counts grouped by meta_status."""
        meta_rows = self._fetchall(
            "SELECT meta_status, COUNT(*) AS cnt FROM app_catalog GROUP BY meta_status"
        )
        return {
            "meta": {r["meta_status"]: int(r["cnt"]) for r in meta_rows},
        }
