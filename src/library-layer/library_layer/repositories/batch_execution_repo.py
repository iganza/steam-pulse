"""BatchExecutionRepository — operational tracking for batch LLM API calls.

One row per Anthropic/Bedrock batch submission (per game, per phase).
Provides structured visibility into what's running, what completed,
how long it took, and what it cost.
"""

from decimal import Decimal

import psycopg2.extras
from aws_lambda_powertools import Logger
from library_layer.models.batch_execution import BatchExecution
from library_layer.repositories.base import BaseRepository
from library_layer.utils.db import retry_on_transient_db_error

logger = Logger()


class BatchExecutionRepository(BaseRepository):
    def insert(
        self,
        *,
        execution_id: str,
        phase: str,
        backend: str,
        batch_id: str,
        model_id: str,
        request_count: int,
        pipeline_version: str,
        prompt_version: str,
        appid: int | None = None,
        slug: str | None = None,
    ) -> int:
        """Record a new batch submission. Returns the row id.

        Exactly one of ``appid`` or ``slug`` must be set — Phase 1-3 jobs
        are per-game (appid), Phase 4 genre synthesis is per-genre (slug).
        The underlying CHECK constraint enforces this at the DB level too.

        Idempotent on `batch_id` — Step Functions retries that re-submit the
        same batch will return the existing row's id. Uses a no-op UPDATE
        on conflict so RETURNING works in a single statement (DO NOTHING
        + separate SELECT is not concurrency-safe).
        """
        if (appid is None) == (slug is None):
            raise ValueError(
                "BatchExecutionRepository.insert requires exactly one of "
                f"appid={appid!r} or slug={slug!r} to be set."
            )
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO batch_executions (
                    execution_id, appid, slug, phase, backend, batch_id, model_id,
                    request_count, pipeline_version, prompt_version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (batch_id) DO UPDATE
                SET batch_id = EXCLUDED.batch_id
                RETURNING id
                """,
                (
                    execution_id,
                    appid,
                    slug,
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
        """Transition from submitted → running on the first non-terminal poll.

        The caller maps provider-specific lifecycle states into the coarse
        ``running`` state, which may include queued or pre-processing
        statuses in addition to true in-progress execution.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE batch_executions
                SET status = 'running'
                WHERE batch_id = %s AND status IN ('submitted', 'running')
                """,
                (batch_id,),
            )
            if cur.rowcount == 0:
                logger.warning(
                    "batch_execution_mark_running_noop",
                    extra={"batch_id": batch_id},
                )
        self.conn.commit()

    @retry_on_transient_db_error()
    def mark_completed(
        self,
        batch_id: str,
        *,
        succeeded_count: int,
        failed_count: int,
        failed_record_ids: list[str],
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_write_tokens: int,
        estimated_cost_usd: Decimal,
    ) -> None:
        """Finalize a batch as completed with outcome counts, token usage, and cost."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE batch_executions
                SET status = 'completed',
                    completed_at = NOW(),
                    duration_ms = (EXTRACT(EPOCH FROM (NOW() - submitted_at)) * 1000)::BIGINT,
                    succeeded_count = %s,
                    failed_count = %s,
                    failed_record_ids = %s,
                    input_tokens = %s,
                    output_tokens = %s,
                    cache_read_tokens = %s,
                    cache_write_tokens = %s,
                    estimated_cost_usd = %s
                WHERE batch_id = %s
                  AND status IN ('submitted', 'running')
                  AND completed_at IS NULL
                """,
                (
                    succeeded_count,
                    failed_count,
                    failed_record_ids,
                    input_tokens,
                    output_tokens,
                    cache_read_tokens,
                    cache_write_tokens,
                    estimated_cost_usd,
                    batch_id,
                ),
            )
            if cur.rowcount == 0:
                logger.warning(
                    "batch_execution_mark_completed_noop",
                    extra={"batch_id": batch_id},
                )
        self.conn.commit()

    @retry_on_transient_db_error()
    def mark_failed(self, batch_id: str, *, failure_reason: str) -> None:
        """Mark a batch as failed with a reason.

        Accepts status 'completed' too — a completed batch can be flipped to
        failed when all records fail validation (tokens/cost already recorded
        by mark_completed, then this overwrites status + adds failure_reason).
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE batch_executions
                SET status = 'failed',
                    completed_at = NOW(),
                    duration_ms = (EXTRACT(EPOCH FROM (NOW() - submitted_at)) * 1000)::BIGINT,
                    failure_reason = %s
                WHERE batch_id = %s
                  AND status IN ('submitted', 'running', 'completed')
                """,
                (failure_reason, batch_id),
            )
            if cur.rowcount == 0:
                logger.warning(
                    "batch_execution_mark_failed_noop",
                    extra={"batch_id": batch_id, "failure_reason": failure_reason},
                )
        self.conn.commit()

    def _rows_to_models(self, rows: list[dict]) -> list[BatchExecution]:
        return [BatchExecution.model_validate(dict(r)) for r in rows]

    def find_by_execution_id(self, execution_id: str) -> list[BatchExecution]:
        """All batch rows for a given Step Functions execution."""
        rows = self._fetchall(
            """
            SELECT * FROM batch_executions
            WHERE execution_id = %s
            ORDER BY submitted_at ASC
            """,
            (execution_id,),
        )
        return self._rows_to_models(rows)

    def find_active(self) -> list[BatchExecution]:
        """All batches currently in-flight (submitted or running)."""
        rows = self._fetchall(
            """
            SELECT * FROM batch_executions
            WHERE status IN ('submitted', 'running')
            ORDER BY submitted_at ASC
            """,
        )
        return self._rows_to_models(rows)

    def find_by_appid(self, appid: int, *, limit: int) -> list[BatchExecution]:
        """Recent batch executions for a specific game."""
        rows = self._fetchall(
            """
            SELECT * FROM batch_executions
            WHERE appid = %s
            ORDER BY submitted_at DESC
            LIMIT %s
            """,
            (appid, limit),
        )
        return self._rows_to_models(rows)

    def find_by_slug(self, slug: str, *, limit: int) -> list[BatchExecution]:
        """Recent batch executions for a specific genre slug."""
        rows = self._fetchall(
            """
            SELECT * FROM batch_executions
            WHERE slug = %s
            ORDER BY submitted_at DESC
            LIMIT %s
            """,
            (slug, limit),
        )
        return self._rows_to_models(rows)
