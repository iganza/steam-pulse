"""MergedSummaryRepository — Phase 2 artifact CRUD for the three-phase pipeline.

A merged_summaries row consolidates a set of chunk_summaries (at
merge_level=1) or prior merged_summaries (at merge_level>=2) into a single
MergedSummary. `source_chunk_ids` is the sorted list of row ids that fed
the merge; `find_latest_by_source_ids()` uses it to short-circuit a merge
call when the same set of inputs already produced a cached merge under the
current prompt version.
"""

import json

import psycopg2.extras
from library_layer.models.analyzer_models import MergedSummary
from library_layer.repositories.base import BaseRepository


class MergedSummaryRepository(BaseRepository):
    def find_latest_by_appid(self, appid: int) -> dict | None:
        return self._fetchone(
            """
            SELECT id, appid, merge_level, summary_json, source_chunk_ids,
                   chunks_merged, model_id, prompt_version, created_at
            FROM merged_summaries
            WHERE appid = %s
            ORDER BY merge_level DESC, created_at DESC
            LIMIT 1
            """,
            (appid,),
        )

    def find_latest_by_source_ids(
        self,
        appid: int,
        source_chunk_ids: list[int],
        prompt_version: str,
    ) -> dict | None:
        """Return the most recent merge row whose source ids exactly match.

        Uses array equality (order-insensitive via a sorted copy passed in
        by the caller) so a retried pipeline with the same inputs reuses
        the stored merge artifact.
        """
        sorted_ids = sorted(source_chunk_ids)
        return self._fetchone(
            """
            SELECT id, appid, merge_level, summary_json, source_chunk_ids,
                   chunks_merged, model_id, prompt_version, created_at
            FROM merged_summaries
            WHERE appid = %s
              AND prompt_version = %s
              AND source_chunk_ids = %s::bigint[]
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (appid, prompt_version, sorted_ids),
        )

    def insert(
        self,
        appid: int,
        merge_level: int,
        summary: MergedSummary,
        source_chunk_ids: list[int],
        chunks_merged: int,
        *,
        model_id: str,
        prompt_version: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
    ) -> int:
        # Explicit RealDictCursor so `fetchone()["id"]` works whether the
        # connection default is dict or tuple (tests use RealDictCursor).
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO merged_summaries (
                    appid, merge_level, summary_json, source_chunk_ids,
                    chunks_merged, model_id, prompt_version,
                    input_tokens, output_tokens, latency_ms
                )
                VALUES (%s, %s, %s::jsonb, %s::bigint[], %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    appid,
                    merge_level,
                    json.dumps(summary.model_dump(mode="json")),
                    sorted(source_chunk_ids),
                    chunks_merged,
                    model_id,
                    prompt_version,
                    input_tokens,
                    output_tokens,
                    latency_ms,
                ),
            )
            row_id = int(cur.fetchone()["id"])
        self.conn.commit()
        return row_id

    def delete_by_appid(self, appid: int) -> int:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM merged_summaries WHERE appid = %s", (appid,))
            deleted = cur.rowcount
        self.conn.commit()
        return deleted
