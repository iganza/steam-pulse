"""ReportRepository — pure SQL I/O for the reports table."""

from __future__ import annotations

import json

from library_layer.models.report import Report
from library_layer.repositories.base import BaseRepository


class ReportRepository(BaseRepository):
    """CRUD operations for the reports table."""

    def upsert(self, report: dict) -> None:
        """Insert or update a report by appid."""
        appid: int = report["appid"]
        reviews_analyzed: int = report.get("total_reviews_analyzed", 0)
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reports (appid, report_json, reviews_analyzed, last_analyzed)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (appid) DO UPDATE SET
                    report_json      = EXCLUDED.report_json,
                    reviews_analyzed = EXCLUDED.reviews_analyzed,
                    last_analyzed    = NOW()
                """,
                (appid, json.dumps(report), reviews_analyzed),
            )
        self.conn.commit()

    def find_by_appid(self, appid: int) -> Report | None:
        row = self._fetchone(
            "SELECT * FROM reports WHERE appid = %s", (appid,)
        )
        if row is None:
            return None
        return Report.model_validate(dict(row))

    def count_all(self) -> int:
        """Return the total number of rows in the reports table."""
        row = self._fetchone("SELECT COUNT(*) AS cnt FROM reports")
        return int(row["cnt"]) if row else 0

    def find_public(self, limit: int = 50, offset: int = 0) -> list[Report]:
        rows = self._fetchall(
            """
            SELECT * FROM reports
            WHERE is_public = TRUE
            ORDER BY last_analyzed DESC NULLS LAST
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        return [Report.model_validate(dict(r)) for r in rows]
