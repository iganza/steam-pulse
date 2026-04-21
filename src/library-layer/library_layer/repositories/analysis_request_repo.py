"""AnalysisRequestRepository — SQL I/O for the analysis_requests table."""

from __future__ import annotations

from library_layer.repositories.base import BaseRepository


class AnalysisRequestRepository(BaseRepository):
    """Track user-submitted requests for game analysis."""

    def add(self, *, appid: int, email: str) -> bool:
        """Insert a request. Returns True if newly inserted, False if duplicate."""
        sql = """
            INSERT INTO analysis_requests (appid, email)
            VALUES (%s, %s)
            ON CONFLICT (appid, email) DO NOTHING
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (appid, email))
            inserted = cur.rowcount > 0
        return inserted

    def count_for_appid(self, *, appid: int) -> int:
        """Count distinct requests for a game."""
        row = self._fetchone(
            "SELECT COUNT(*) AS c FROM analysis_requests WHERE appid = %s",
            (appid,),
        )
        return int(row["c"]) if row else 0
