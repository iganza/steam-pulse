"""BatchExecutionRepository — operational tracking for batch LLM API calls.

One row per Anthropic/Bedrock batch submission (per game, per phase).
Provides structured visibility into what's running, what completed,
how long it took, and what it cost.
"""

import psycopg2.extras
from library_layer.repositories.base import BaseRepository


class BatchExecutionRepository(BaseRepository):
    def insert(
        self,
        *,
        execution_id: str,
        appid: int,
        phase: str,
        backend: str,
        batch_id: str,
        model_id: str,
        request_count: int,
        pipeline_version: str | None,
        prompt_version: str | None,
    ) -> int:
        """Record a new batch submission. Returns the row id."""
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO batch_executions (
                    execution_id, appid, phase, backend, batch_id, model_id,
                    request_count, pipeline_version, prompt_version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    execution_id,
                    appid,
                    phase,
                    backend,
                    batch_id,
                    model_id,
                    request_count,
                    pipeline_version,
                    prompt_version,
                ),
            )
            row_id = int(cur.fetchone()["id"])
        self.conn.commit()
        return row_id

    def mark_running(self, batch_id: str) -> None:
        """Transition from submitted → running on first poll that confirms processing."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE batch_executions
                SET status = 'running'
                WHERE batch_id = %s AND status = 'submitted'
                """,
                (batch_id,),
            )
        self.conn.commit()

    def mark_completed(
        self,
        batch_id: str,
        *,
        succeeded_count: int,
        failed_count: int,
        input_tokens: int | None,
        output_tokens: int | None,
        cache_read_tokens: int | None,
        cache_write_tokens: int | None,
        estimated_cost_usd: float | None,
        failed_record_ids: list[str],
    ) -> None:
        """Finalize a batch as completed with token usage and outcome counts."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE batch_executions
                SET status = 'completed',
                    completed_at = NOW(),
                    duration_ms = EXTRACT(EPOCH FROM (NOW() - submitted_at))::INTEGER * 1000,
                    succeeded_count = %s,
                    failed_count = %s,
                    input_tokens = %s,
                    output_tokens = %s,
                    cache_read_tokens = %s,
                    cache_write_tokens = %s,
                    estimated_cost_usd = %s,
                    failed_record_ids = %s
                WHERE batch_id = %s
                """,
                (
                    succeeded_count,
                    failed_count,
                    input_tokens,
                    output_tokens,
                    cache_read_tokens,
                    cache_write_tokens,
                    estimated_cost_usd,
                    failed_record_ids or None,
                    batch_id,
                ),
            )
        self.conn.commit()

    def mark_failed(self, batch_id: str, *, failure_reason: str) -> None:
        """Mark a batch as failed with a reason."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE batch_executions
                SET status = 'failed',
                    completed_at = NOW(),
                    duration_ms = EXTRACT(EPOCH FROM (NOW() - submitted_at))::INTEGER * 1000,
                    failure_reason = %s
                WHERE batch_id = %s
                """,
                (failure_reason, batch_id),
            )
        self.conn.commit()

    def find_by_execution_id(self, execution_id: str) -> list[dict]:
        """All batch rows for a given Step Functions execution."""
        return self._fetchall(
            """
            SELECT * FROM batch_executions
            WHERE execution_id = %s
            ORDER BY submitted_at ASC
            """,
            (execution_id,),
        )

    def find_active(self) -> list[dict]:
        """All batches currently in-flight (submitted or running)."""
        return self._fetchall(
            """
            SELECT * FROM batch_executions
            WHERE status IN ('submitted', 'running')
            ORDER BY submitted_at ASC
            """,
        )

    def find_by_appid(self, appid: int, *, limit: int = 20) -> list[dict]:
        """Recent batch executions for a specific game."""
        return self._fetchall(
            """
            SELECT * FROM batch_executions
            WHERE appid = %s
            ORDER BY submitted_at DESC
            LIMIT %s
            """,
            (appid, limit),
        )
