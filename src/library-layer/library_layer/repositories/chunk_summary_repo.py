"""ChunkSummaryRepository — Phase 1 artifact CRUD for the three-phase pipeline.

Every row is keyed by `(appid, chunk_hash, prompt_version)`, making Phase 1
idempotent: the analyzer computes `compute_chunk_hash(chunk)` from the set
of steam_review_ids in the chunk and calls `find_by_hash()` before paying
for a fresh LLM call.
"""

import json

import psycopg2.extras
from library_layer.models.analyzer_models import RichChunkSummary
from library_layer.repositories.base import BaseRepository
from library_layer.utils.db import retry_on_transient_db_error


class ChunkSummaryRepository(BaseRepository):
    def find_by_hash(self, appid: int, chunk_hash: str, prompt_version: str) -> dict | None:
        return self._fetchone(
            """
            SELECT id, appid, chunk_index, chunk_hash, review_count,
                   summary_json, model_id, prompt_version, created_at
            FROM chunk_summaries
            WHERE appid = %s AND chunk_hash = %s AND prompt_version = %s
            """,
            (appid, chunk_hash, prompt_version),
        )

    def find_by_appid(self, appid: int, prompt_version: str) -> list[dict]:
        return self._fetchall(
            """
            SELECT id, appid, chunk_index, chunk_hash, review_count,
                   summary_json, model_id, prompt_version, created_at
            FROM chunk_summaries
            WHERE appid = %s AND prompt_version = %s
            ORDER BY chunk_index ASC, id ASC
            """,
            (appid, prompt_version),
        )

    @retry_on_transient_db_error()
    def insert(
        self,
        appid: int,
        chunk_index: int,
        chunk_hash: str,
        review_count: int,
        summary: RichChunkSummary,
        *,
        model_id: str,
        prompt_version: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
    ) -> int:
        """Insert a chunk summary row and return its id.

        On conflict (same appid + chunk_hash + prompt_version) returns the
        existing row's id — callers can rely on the result being the
        canonical id for that chunk.
        """
        # Explicit RealDictCursor for the RETURNING clause so the row_id
        # access works whether the connection default is dict or tuple
        # (test conftest opens the conn with RealDictCursor; prod uses
        # the plain tuple default).
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO chunk_summaries (
                    appid, chunk_index, chunk_hash, review_count, summary_json,
                    model_id, prompt_version, input_tokens, output_tokens, latency_ms
                )
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
                ON CONFLICT (appid, chunk_hash, prompt_version) DO UPDATE
                SET chunk_index = EXCLUDED.chunk_index
                RETURNING id
                """,
                (
                    appid,
                    chunk_index,
                    chunk_hash,
                    review_count,
                    json.dumps(summary.model_dump(mode="json")),
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
        """Drop all chunk_summaries for a game (forces full re-analysis)."""
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM chunk_summaries WHERE appid = %s", (appid,))
            deleted = cur.rowcount
        self.conn.commit()
        return deleted
