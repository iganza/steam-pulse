"""MergedSummaryRepository — Phase 2 artifact CRUD for the three-phase pipeline.

A merged_summaries row consolidates chunk summaries into a single
MergedSummary. `source_chunk_ids` always contains **leaf chunk_summaries
ids** — at every merge level, the ids are threaded transitively from the
primary chunks, not from intermediate merged_summaries rows.
`find_latest_by_source_ids()` uses this to short-circuit a merge call when
the exact same set of primary chunks already produced a cached merge under
the current prompt version.
"""

import json

import psycopg2.extras
from library_layer.models.analyzer_models import MergedSummary
from library_layer.repositories.base import BaseRepository
from library_layer.utils.db import retry_on_transient_db_error


class MergedSummaryRepository(BaseRepository):
    def find_by_id(self, merge_id: int) -> dict | None:
        """Race-free lookup by primary key.

        `run_merge_phase` uses this to re-read the exact row it just
        inserted — `find_latest_by_appid` orders by merge_level/created_at
        and races with concurrent re-analysis for the same appid.
        """
        return self._fetchone(
            """
            SELECT id, appid, merge_level, summary_json, source_chunk_ids,
                   chunks_merged, model_id, prompt_version, created_at
            FROM merged_summaries
            WHERE id = %s
            """,
            (merge_id,),
        )

    def find_latest_by_appid(self, appid: int) -> dict | None:
        return self._fetchone(
            """
            SELECT id, appid, merge_level, summary_json, source_chunk_ids,
                   chunks_merged, model_id, prompt_version, created_at
            FROM merged_summaries
            WHERE appid = %s
            -- `id DESC` is a deterministic tie-breaker for rapid
            -- successive inserts that share a created_at timestamp.
            ORDER BY merge_level DESC, created_at DESC, id DESC
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
            -- `id DESC` is a deterministic tie-breaker when two rows
            -- share a created_at timestamp (rapid successive inserts).
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (appid, prompt_version, sorted_ids),
        )

    @retry_on_transient_db_error()
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
