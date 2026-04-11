"""ReportRepository — pure SQL I/O for the reports table."""

from __future__ import annotations

import json

from library_layer.models.report import Report
from library_layer.repositories.base import BaseRepository


class ReportRepository(BaseRepository):
    """CRUD operations for the reports table."""

    def upsert(self, report: dict) -> None:
        """Insert or update a report by appid.

        Callers must pass a complete GameReport dict — report_json is
        overwritten wholesale on conflict (no merge). Partial dicts will
        discard previously stored keys from report_json.

        Pipeline-bookkeeping keys are pulled off the dict and written to
        their own columns (added in migration 0036). All three are required:
            pipeline_version: str   — bump to invalidate cached reports
            chunk_count:      int   — how many Phase 1 chunks fed the merge
            merged_summary_id: int  — FK-like pointer into merged_summaries

        Also syncs denormalized hidden_gem_score and last_analyzed onto the
        games table so catalog queries avoid the JSONB LEFT JOIN. The games
        sync only updates keys present in the dict as a defensive measure.

        Note: sentiment_score was dropped from games in 0021 — Steam's
        positive_pct is the only sentiment number now. Even if a legacy report
        dict still contains a "sentiment_score" key, it is ignored here.
        """
        appid: int = report["appid"]
        reviews_analyzed: int = report.get("total_reviews_analyzed", 0)
        pipeline_version: str = report["pipeline_version"]
        chunk_count: int = report["chunk_count"]
        merged_summary_id: int = report["merged_summary_id"]
        # Strip the pipeline bookkeeping out of the JSONB blob — those keys
        # live in dedicated columns now, keeping the JSON a pure GameReport.
        report_json = {
            k: v
            for k, v in report.items()
            if k not in {"pipeline_version", "chunk_count", "merged_summary_id"}
        }
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reports (
                    appid, report_json, reviews_analyzed, last_analyzed,
                    pipeline_version, chunk_count, merged_summary_id
                )
                VALUES (%s, %s, %s, NOW(), %s, %s, %s)
                ON CONFLICT (appid) DO UPDATE SET
                    report_json       = EXCLUDED.report_json,
                    reviews_analyzed  = EXCLUDED.reviews_analyzed,
                    last_analyzed     = NOW(),
                    pipeline_version  = EXCLUDED.pipeline_version,
                    chunk_count       = EXCLUDED.chunk_count,
                    merged_summary_id = EXCLUDED.merged_summary_id
                """,
                (
                    appid,
                    json.dumps(report_json),
                    reviews_analyzed,
                    pipeline_version,
                    chunk_count,
                    merged_summary_id,
                ),
            )
            # Sync denormalized fields to games table — only update columns present
            # in the report dict to avoid nulling omitted fields on partial payloads.
            # last_analyzed is always set to NOW() on every upsert.
            score_sets: list[str] = ["last_analyzed = NOW()"]
            score_vals: list[object] = []
            if "hidden_gem_score" in report:
                score_sets.append("hidden_gem_score = %s")
                score_vals.append(report["hidden_gem_score"])
            score_vals.append(appid)
            cur.execute(
                f"UPDATE games SET {', '.join(score_sets)} WHERE appid = %s",
                score_vals,
            )
        self.conn.commit()

    def find_by_appid(self, appid: int) -> Report | None:
        row = self._fetchone("SELECT * FROM reports WHERE appid = %s", (appid,))
        if row is None:
            return None
        return Report.model_validate(dict(row))

    def has_current_report(self, appid: int, pipeline_version: str) -> bool:
        """Return True if a report exists for this appid at the given pipeline version."""
        row = self._fetchone(
            "SELECT 1 FROM reports WHERE appid = %s AND pipeline_version = %s",
            (appid, pipeline_version),
        )
        return row is not None

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
