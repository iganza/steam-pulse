"""JobRepository — pure SQL I/O for the analysis_jobs table."""

from __future__ import annotations

from library_layer.repositories.base import BaseRepository


class JobRepository(BaseRepository):
    """CRUD operations for the analysis_jobs table."""

    def find(self, job_id: str) -> dict | None:
        """Return job_id, status, appid for the given job_id, or None if not found."""
        row = self._fetchone(
            "SELECT job_id, status, appid FROM analysis_jobs WHERE job_id = %s",
            (job_id,),
        )
        if row is None:
            return None
        return dict(row)

    def upsert(self, job_id: str, status: str, appid: int) -> None:
        """Insert or update a job record by job_id."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO analysis_jobs (job_id, status, appid, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (job_id) DO UPDATE
                    SET status     = EXCLUDED.status,
                        appid      = EXCLUDED.appid,
                        updated_at = NOW()
                """,
                (job_id, status, appid),
            )
        self.conn.commit()
