"""CatalogRepository — pure SQL I/O for the app_catalog table."""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg2.extras
from library_layer.config import SteamPulseConfig
from library_layer.models.catalog import CatalogEntry
from library_layer.repositories.base import BaseRepository


class CatalogRepository(BaseRepository):
    """CRUD operations for the app_catalog table."""

    def bulk_upsert(self, entries: list[dict]) -> int:
        """INSERT ... ON CONFLICT DO UPDATE for GetAppList metadata.

        Updates steam_last_modified and price_change_number on conflict,
        but only when the incoming value is newer (monotonic — never regresses).
        The WHERE clause ensures Postgres skips rows where nothing changed,
        avoiding unnecessary row-version churn on 160k+ existing rows.

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
                    steam_last_modified = COALESCE(EXCLUDED.steam_last_modified, app_catalog.steam_last_modified),
                    price_change_number = COALESCE(EXCLUDED.price_change_number, app_catalog.price_change_number)
                WHERE
                    (EXCLUDED.steam_last_modified IS NOT NULL
                     AND (app_catalog.steam_last_modified IS NULL
                          OR EXCLUDED.steam_last_modified > app_catalog.steam_last_modified))
                    OR
                    (EXCLUDED.price_change_number IS NOT NULL
                     AND (app_catalog.price_change_number IS NULL
                          OR EXCLUDED.price_change_number > app_catalog.price_change_number))
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

    def find_due_meta(
        self, limit: int, config: SteamPulseConfig
    ) -> list[CatalogEntry]:
        """Return catalog entries whose metadata refresh window has elapsed.

        Tiers (first match wins): S (top popularity) → A (EA/coming-soon/popular)
        → B (analysis-eligible). Tier C (long tail, review_count below the B
        threshold and not EA/coming-soon) is refresh-exempt — the long-tail
        share of hourly ingest dominated write IOPS on a small RDS, and those
        games' metadata barely drifts. Graduation out of C is operator-driven
        via `scripts/trigger_crawl.py`; the next dispatcher run picks the game
        up at its new tier once its review_count catches up.

        Deterministic smearing: a game's due time is offset into its tier's
        window by `abs(hashtext(appid::text)::bigint) % window_secs` (bigint
        cast is required because hashtext returns int4 and `abs(INT_MIN)`
        overflows), so work spreads evenly instead of spiking at every tier
        boundary. Same appid always hashes to the same slot — no "due / not
        due" oscillation.

        NULLS FIRST ensures legacy rows (no meta_crawled_at) refresh first.
        """
        s_secs = config.REFRESH_META_TIER_S_DAYS * 86400
        a_secs = config.REFRESH_META_TIER_A_DAYS * 86400
        b_secs = config.REFRESH_META_TIER_B_DAYS * 86400
        rows = self._fetchall(
            """
            WITH tiered AS (
              SELECT
                ac.*,
                CASE
                  WHEN g.review_count >= %(s_threshold)s THEN %(s_secs)s
                  WHEN COALESCE(g.coming_soon, FALSE) = TRUE
                    OR gg.genre_id IS NOT NULL
                    OR g.review_count >= %(a_threshold)s THEN %(a_secs)s
                  ELSE %(b_secs)s
                END AS window_secs,
                CASE
                  WHEN g.review_count >= %(s_threshold)s THEN 0
                  WHEN COALESCE(g.coming_soon, FALSE) = TRUE
                    OR gg.genre_id IS NOT NULL
                    OR g.review_count >= %(a_threshold)s THEN 1
                  ELSE 2
                END AS tier_rank
              FROM app_catalog ac
              JOIN games g ON g.appid = ac.appid
              LEFT JOIN game_genres gg ON gg.appid = ac.appid AND gg.genre_id = 70
              WHERE ac.meta_status = 'done'
                AND (
                  COALESCE(g.coming_soon, FALSE) = TRUE
                  OR gg.genre_id IS NOT NULL
                  OR g.review_count >= %(b_threshold)s
                )
            )
            SELECT * FROM tiered
            WHERE
              meta_crawled_at IS NULL
              OR meta_crawled_at
                 + (window_secs * INTERVAL '1 second')
                 + ((abs(hashtext(appid::text)::bigint) %% window_secs) * INTERVAL '1 second')
                 < NOW()
            ORDER BY tier_rank, meta_crawled_at ASC NULLS FIRST
            LIMIT %(limit)s
            """,
            {
                "s_threshold": config.REFRESH_TIER_S_REVIEW_COUNT,
                "a_threshold": config.REFRESH_TIER_A_REVIEW_COUNT,
                "b_threshold": config.REFRESH_TIER_B_REVIEW_COUNT,
                "s_secs": s_secs,
                "a_secs": a_secs,
                "b_secs": b_secs,
                "limit": limit,
            },
        )
        return [CatalogEntry.model_validate(dict(r)) for r in rows]

    def find_due_reviews(
        self, limit: int, config: SteamPulseConfig
    ) -> list[CatalogEntry]:
        """Return catalog entries whose review refresh window has elapsed.

        Same tier + smearing shape as find_due_meta, but:
          - Operates on review_crawled_at
          - Tier C excluded (no review refresh — low-signal long tail)
          - coming_soon=TRUE excluded (no reviews to refresh until launch;
            release detection happens via metadata crawl, and the game
            naturally enters review refresh once review_count crosses the
            B-tier threshold)
        """
        s_secs = config.REFRESH_REVIEWS_TIER_S_DAYS * 86400
        a_secs = config.REFRESH_REVIEWS_TIER_A_DAYS * 86400
        b_secs = config.REFRESH_REVIEWS_TIER_B_DAYS * 86400
        rows = self._fetchall(
            """
            WITH tiered AS (
              SELECT
                ac.*,
                CASE
                  WHEN g.review_count >= %(s_threshold)s THEN %(s_secs)s
                  WHEN gg.genre_id IS NOT NULL
                    OR g.review_count >= %(a_threshold)s THEN %(a_secs)s
                  ELSE %(b_secs)s
                END AS window_secs,
                CASE
                  WHEN g.review_count >= %(s_threshold)s THEN 0
                  WHEN gg.genre_id IS NOT NULL
                    OR g.review_count >= %(a_threshold)s THEN 1
                  ELSE 2
                END AS tier_rank
              FROM app_catalog ac
              JOIN games g ON g.appid = ac.appid
              LEFT JOIN game_genres gg ON gg.appid = ac.appid AND gg.genre_id = 70
              WHERE ac.meta_status = 'done'
                AND COALESCE(g.coming_soon, FALSE) = FALSE
                AND g.review_count >= %(b_threshold)s
            )
            SELECT * FROM tiered
            WHERE
              review_crawled_at IS NULL
              OR review_crawled_at
                 + (window_secs * INTERVAL '1 second')
                 + ((abs(hashtext(appid::text)::bigint) %% window_secs) * INTERVAL '1 second')
                 < NOW()
            ORDER BY tier_rank, review_crawled_at ASC NULLS FIRST
            LIMIT %(limit)s
            """,
            {
                "s_threshold": config.REFRESH_TIER_S_REVIEW_COUNT,
                "a_threshold": config.REFRESH_TIER_A_REVIEW_COUNT,
                "b_threshold": config.REFRESH_TIER_B_REVIEW_COUNT,
                "s_secs": s_secs,
                "a_secs": a_secs,
                "b_secs": b_secs,
                "limit": limit,
            },
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

    def mark_reviews_complete_and_crawled(
        self, appid: int, completed_at: datetime | None = None
    ) -> None:
        """Combined form of mark_reviews_complete + mark_reviews_crawled.

        One UPDATE + one commit instead of two. Called at review-termination
        branches (exhausted / early_stop / target_hit) where both timestamps
        always advance together.
        """
        ts = completed_at or datetime.now(tz=timezone.utc)
        with self.conn.cursor() as cur:
            cur.execute(
                """UPDATE app_catalog
                   SET reviews_completed_at = GREATEST(
                           COALESCE(reviews_completed_at, '1970-01-01'::timestamptz), %s
                       ),
                       review_crawled_at = NOW()
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
