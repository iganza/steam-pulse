# Configurable DB Connect Timeout + Transient-Error Retries for Batch Lambdas

## Context

The production batch-analysis pipeline hit intermittent `timeout expired`
errors during a 10-concurrent re-queue of the roguelike-deckbuilder wedge
(2026-04-18). Root cause: `src/library-layer/library_layer/utils/db.py:67`
hard-codes `connect_timeout=5`. Under a cold-start burst (many Lambdas in
VPC acquiring ENIs simultaneously), the TCP handshake to the RDS instance
occasionally takes >5 seconds and libpq gives up.

The migrate handler (`src/lambda-functions/lambda_functions/admin/migrate_handler.py:32`)
already uses 30s with a comment acknowledging cold-start latency. The
library-layer util was left at 5s — inconsistent and too aggressive.

On top of the timeout, batch Lambdas that write to the DB should tolerate
**transient** hiccups (RDS brief unresponsiveness, connection reset during
maintenance window) with a small number of retries rather than fail the
entire analysis job. A single TCP blip currently converts a $1 analysis
into $0 of output plus ~$0.30 of wasted LLM batch tokens.

Instance class is `db.t4g.micro` (1 vCPU, 1 GB, `max_connections=79`).
Upgrading the instance is out of scope for this prompt, but the low
headroom is context for why we want to be nice to it.

## Goal

1. Make `connect_timeout` caller-configurable with a sane default.
2. Add a narrow retry-with-backoff around both connection establishment
   and transient write errors — **batch Lambdas only**, not API.
3. Keep the changes small and targeted. No refactors of unrelated code.

## Non-goals

- RDS Proxy. Connection counts peaked at 40/79 during the incident — plenty
  of headroom. Adding a proxy would add latency and complexity without
  addressing the actual root cause (timeout-too-short on cold start).
- Instance class upgrade. Separate concern.
- API Lambda retries. API has request-latency budgets and should surface
  failures directly, not hide them behind silent retries.
- SELECT-path retries. This prompt covers connection + idempotent writes.

---

## Changes

### A. `src/library-layer/library_layer/utils/db.py` — make timeout configurable, add connect retry

Current shape:

```python
def get_conn(cursor_factory=psycopg2.extras.RealDictCursor) -> psycopg2.extensions.connection:
    ...
    _state["conn"] = psycopg2.connect(
        get_db_url(),
        cursor_factory=cursor_factory,
        connect_timeout=5,
        ...
    )
```

Required changes:

1. Add a parameter: `connect_timeout: int = 30`. Default is 30s. Batch
   callers will pass 60s.

2. Wrap the `psycopg2.connect()` call with tenacity retry:
   - `tenacity` is already in `poetry.lock`; add it as an explicit
     dependency in `pyproject.toml` of the library-layer if not already
     declared.
   - Retry only on `psycopg2.OperationalError`.
   - Max 3 attempts (so: initial + 2 retries).
   - Exponential backoff: 1s, then 2s (plus ±0.5s jitter).
   - **Do not retry on auth failures.** Inspect the exception message;
     if it contains `password authentication failed`,
     `role ... does not exist`, or `database ... does not exist`, raise
     immediately with no retry. These are permanent and retrying wastes
     Lambda budget.

3. Log each retry attempt with the attempt number and the underlying
   exception message (`logger.warning(...)`), so we can tell from
   CloudWatch how often this is kicking in.

4. Keep the `_state["conn"]` caching behavior. The first caller's
   `connect_timeout` determines the cached connection's connect timeout
   for that Lambda warm instance. That's fine — `connect_timeout` only
   affects the initial connection attempt, not subsequent queries.

5. The health-check `SELECT 1` path at the top of `get_conn()` must NOT
   be wrapped in retries here. If that fails, the code already falls
   through to re-create the connection, which is the retry mechanism.

### B. Update batch-analysis Lambda entrypoints to use 60s timeout

Files (audit the directory for any I've missed):

- `src/lambda-functions/lambda_functions/batch_analysis/prepare_phase.py`
- `src/lambda-functions/lambda_functions/batch_analysis/collect_phase.py`
- `src/lambda-functions/lambda_functions/batch_analysis/dispatch_batch.py`
- `src/lambda-functions/lambda_functions/batch_analysis/check_batch_status.py`
- Any other Lambda under `batch_analysis/` that calls `get_conn()`

For each, at module top:

```python
_BATCH_CONNECT_TIMEOUT = 60  # cold-start burst tolerance
```

Replace direct `get_conn()` calls with:

```python
get_conn(connect_timeout=_BATCH_CONNECT_TIMEOUT)
```

If these Lambdas use a factory pattern to pass `get_conn` into
repositories, bind the timeout via a closure rather than changing repo
signatures:

```python
def _get_batch_conn() -> psycopg2.extensions.connection:
    return get_conn(connect_timeout=_BATCH_CONNECT_TIMEOUT)

_chunk_repo = ChunkSummaryRepository(_get_batch_conn)
```

Do **not** change the repository class signatures. The connect-timeout
decision is a per-Lambda concern, not a per-repo concern.

### C. Add retry for transient write errors in batch repositories

Create a single decorator in
`src/library-layer/library_layer/utils/db.py`:

```python
def retry_on_transient_db_error(max_attempts: int = 3):
    """Decorator that retries a DB write on transient errors only.

    Retries on: OperationalError, SerializationFailure, DeadlockDetected.
    Does NOT retry on: IntegrityError (UniqueViolation, FK violation),
    ProgrammingError (syntax), DataError (bad type).
    """
    ...
```

Implementation notes:
- Use tenacity's `@retry` with `retry_if_exception_type`, but exclude
  subclasses that are permanent. Easiest pattern:

```python
from psycopg2 import OperationalError, IntegrityError, ProgrammingError, DataError
from psycopg2.errors import SerializationFailure, DeadlockDetected

def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (IntegrityError, ProgrammingError, DataError)):
        return False
    return isinstance(exc, (OperationalError, SerializationFailure, DeadlockDetected))
```

- Exponential backoff 0.5s → 1s → 2s, with jitter.
- Log each retry with the wrapped function's name and the exception.
- On exhaustion, re-raise the original exception (don't wrap it).

Apply the decorator to the write methods in batch-phase repos:

- `ChunkSummaryRepository.insert()` — `src/library-layer/library_layer/repositories/chunk_summary_repo.py`
- `MergedSummaryRepository.insert()` — `src/library-layer/library_layer/repositories/merged_summary_repo.py`
- `ReportRepository.upsert()` — wherever it lives
- `BatchExecutionRepository.mark_completed()` and `.mark_failed()`

Do NOT apply it blanket to the base class — API path repos share these
classes and we do not want API writes to retry silently.

If tenacity's decorator conflicts with the `ON CONFLICT DO UPDATE`
semantics in any insert, prefer a manual retry loop with the same
backoff shape — the insert is already idempotent so retries are safe.

---

## Constraints (mandatory — from project CLAUDE conventions)

- Use `pydantic.BaseModel` for any new domain/context objects. No
  dataclasses. (There shouldn't be new domain models in this change, but
  if you add one, follow this rule.)
- Tests run against `steampulse_test`, never the live dev DB.
- No `git add` / `commit` / `push` — user handles all VCS operations.
- No deploy — user handles deploys.
- Avoid `| None` unless the structure genuinely can't eliminate the
  optionality.
- Don't add new comments unless the "why" is non-obvious. The retry
  guardrails (what's transient vs. permanent) are worth one comment.

## Tests

Add under `tests/utils/` (the repo's existing home for utility-module tests; there is no `tests/library_layer/` directory):

1. **Connect retry on transient error** — mock `psycopg2.connect` to
   raise `OperationalError("timeout expired")` twice, then return a mock
   connection. Assert `get_conn()` returns that connection and
   `psycopg2.connect` was called 3 times.

2. **Connect retry exhaustion** — mock `psycopg2.connect` to raise
   `OperationalError` on all attempts. Assert `get_conn()` raises
   `OperationalError` after 3 attempts, not wrapped in tenacity's own
   `RetryError`.

3. **Auth failure is NOT retried** — mock `psycopg2.connect` to raise
   `OperationalError("FATAL: password authentication failed for user ...")`.
   Assert `psycopg2.connect` was called exactly once and the exception
   propagated unchanged.

4. **Write retry on transient OperationalError** — unit test of the
   decorator: function raises `OperationalError` on first call, succeeds
   on second. Assert final return value + 2 calls made.

5. **Write retry does NOT retry IntegrityError** — function raises
   `UniqueViolation`. Assert exactly 1 call, exception propagates.

6. **Integration smoke** against `steampulse_test`: call
   `ChunkSummaryRepository.insert()` happy path, assert the row lands.
   Just to confirm the decorator didn't break the success path.

## Implementation order

1. Add `connect_timeout` parameter + connect retry in `utils/db.py`.
   Unit tests 1–3. Verify locally against `steampulse_test`.
2. Add `retry_on_transient_db_error` decorator in `utils/db.py`.
   Unit tests 4–5.
3. Apply decorator to the four batch write paths listed in §C.
   Integration test 6.
4. Update the batch-analysis Lambda entrypoints to pass
   `connect_timeout=60`. No new tests needed — the Lambdas are
   integration-tested end-to-end by existing smoke tests.

## Verification

Before handing back: run `poetry run pytest tests/utils/test_db.py -v`
(plus the existing `tests/repositories/` suite to confirm the decorator
didn't break any batch-write happy paths) and paste the result into
the PR description.

Do NOT run against production. Do NOT deploy. User handles both.
