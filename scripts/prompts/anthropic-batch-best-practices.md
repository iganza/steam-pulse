# Anthropic Batch API — Best Practices + Execution Tracking

> Audit of `AnthropicBatchBackend` against Anthropic's Message Batches API
> documentation surfaced three gaps. Those fixes were combined with a new
> `batch_executions` tracking table that gives structured visibility into
> batch state, cost, and failures — replacing the need to dig through
> Step Functions console or CloudWatch logs.

---

## Context

Batch LLM analysis state was ephemeral — it lived in Step Functions execution
history (90-day AWS retention) and CloudWatch logs. There was no structured way
to query "which games are being processed, what phase are they in, how long did
they take, what did they cost" from our own database. The Anthropic best-practice
fixes (prompt caching, structured error logging, failed record surfacing) were
implemented alongside the tracking table since the table is where the richer
metadata gets persisted.

---

## A. Batch Execution Tracking

### Schema: `batch_executions` table (migration 0043)

One row per Anthropic/Bedrock batch API call (per game, per phase that actually
submits a job — skipped/cached phases don't get a row).

```sql
CREATE TABLE IF NOT EXISTS batch_executions (
    id                  BIGSERIAL PRIMARY KEY,
    execution_id        TEXT NOT NULL,          -- SFN execution name
    appid               INTEGER NOT NULL REFERENCES games(appid),
    phase               TEXT NOT NULL,          -- 'chunk' | 'synthesis'
    backend             TEXT NOT NULL,          -- 'anthropic' | 'bedrock'
    batch_id            TEXT NOT NULL UNIQUE,   -- Anthropic batch ID or Bedrock job ARN
    model_id            TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'submitted',
    submitted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    duration_ms         BIGINT,
    request_count       INTEGER NOT NULL,
    succeeded_count     INTEGER,
    failed_count        INTEGER,
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    cache_read_tokens   INTEGER,
    cache_write_tokens  INTEGER,
    estimated_cost_usd  NUMERIC(8, 4),
    failure_reason      TEXT,
    failed_record_ids   TEXT[],
    pipeline_version    TEXT,
    prompt_version      TEXT
);
```

Indexed on `execution_id`, `appid`, `status`, `submitted_at DESC`.

### Why per-batch-API-call granularity

- **Not per-record**: `chunk_summaries` and `reports` already track per-record
  outcomes with tokens/latency.
- **Not per-orchestrator-run**: Too coarse — need to see which specific
  game/phase is stuck or expensive.
- **Per-batch-API-call**: Maps 1:1 to an Anthropic batch ID or Bedrock job ARN.
  The natural unit of "something I submitted and am waiting for."

### Repository: `BatchExecutionRepository`

Methods: `insert`, `mark_running`, `mark_completed`, `mark_failed`,
`find_by_execution_id`, `find_active`, `find_by_appid`.

### Lambda instrumentation

- `prepare_phase.py`: inserts tracking row after `backend.submit()`.
- `check_batch_status.py`: calls `mark_running` on first "Running" poll,
  `mark_failed` on terminal failure.
- `collect_phase.py`: calls `mark_completed` with succeeded/failed counts
  and `failed_record_ids` after collection.

---

## B. Anthropic Batch Best Practices

### B1. Prompt caching on the system block

Added `cache_control: {type: "ephemeral"}` to the system content block in
`AnthropicBatchBackend.prepare()`. The chunk phase sends identical system
prompts for every request in a batch — caching stacks with the 50% batch
discount for up to 95% savings on cached input tokens.

### B2. Structured error logging

Replaced the generic `batch_record_failed` warning in `collect()` with
branched logging:
- `"errored"` records: logs `error_type` and `error_message` from
  `entry.result.error` to distinguish validation errors from transient failures.
- `"expired"` / `"canceled"` records: logs `result_type`.

### B3. `BatchCollectResult` return type

Both backends (`batch.py` and `anthropic_batch.py`) now return a structured
`BatchCollectResult` from `collect()`:

```python
class BatchCollectResult(BaseModel):
    results: list[tuple[str, BaseModel]]
    failed_ids: list[str]
    skipped: int
```

`collect_phase.py` unpacks the new shape, logs at ERROR if `failed_ids` is
non-empty, and passes `failed_ids` into `batch_exec_repo.mark_completed()`.

Actual per-record retry logic was deferred — failed records are surfaced and
persisted in `batch_executions.failed_record_ids` for observability, and the
game is re-queued on the next dispatch cycle.

---

## Non-goals

- **Batch deletion after collection** — 29-day retention is fine.
- **Explicit size-limit guards** — per-game batches are bounded well under 100k.
- **Dry-run validation** — the realtime ConverseBackend path validates the same
  request shapes continuously.
- **Per-record retry** — deferred; `failed_record_ids` surfaces failures for
  future retry work.

---

## Files touched

| File | Change |
|---|---|
| `migrations/0043_batch_executions.sql` | New table |
| `repositories/batch_execution_repo.py` | New repo |
| `llm/backend.py` | Added `BatchCollectResult` model |
| `llm/anthropic_batch.py` | `cache_control`, structured error logging, new return type |
| `llm/batch.py` | New return type, `failed_ids` tracking |
| `llm/__init__.py` | Exports `BatchCollectResult` |
| `schema.py` | Added `batch_executions` DDL |
| `batch_analysis/prepare_phase.py` | Inserts tracking row after submit |
| `batch_analysis/check_batch_status.py` | Updates tracking row on status transitions |
| `batch_analysis/collect_phase.py` | Unpacks new return, finalizes tracking row |
| `tests/repositories/test_batch_execution_repo.py` | 6 DB tests |
| `tests/handlers/test_collect_phase.py` | Adapted to `BatchCollectResult` |
| `tests/handlers/test_prepare_phase.py` | Mocks `_batch_exec_repo` |
| `tests/llm/test_batch_jsonl.py` | Adapted to `BatchCollectResult` |
