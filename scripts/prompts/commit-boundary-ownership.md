# Move Commit Ownership from Repos to Handlers

## Goal

Every repository write method currently ends in `self.conn.commit()`. The
result: a single ingest message commits 3–5 times (once per repo call),
forcing a WAL `fsync` per commit when one per-message would do. Move
transaction ownership up to the handler layer — repos issue statements,
the handler owns the commit/rollback — so each business unit of work is
exactly one transaction.

Scope-wise this is a hygiene refactor, not a rescue. It's worth ~5–15%
throughput on the ingest path and makes transaction semantics
predictable everywhere else (analysis, admin, API). Complementary to
`scripts/prompts/analysis-demand-review-crawl.md` — that prompt stops
*unneeded* crawling; this one tightens the *needed* writes.

## Problem

`BaseRepository` (`src/library-layer/library_layer/repositories/base.py`)
is a thin psycopg2 helper — no transaction semantics. Every write-side
subclass method commits at the end:

```
waitlist_repo.py:21            catalog_repo.py:61, 229, 248, 264, 273
chunk_summary_repo.py:92, 100  tag_repo.py:117, 158, 193
batch_execution_repo.py:       report_repo.py:87
  65, 89, 142, 170             matview_repo.py:350
genre_synthesis_repo.py:       job_repo.py:35
  91, 106                      merged_summary_repo.py:124, 131
analysis_request_repo.py:21    game_repo.py:
review_repo.py:65                120, 224, 243, 714, 764, 779, 781, 797
```

~30 commit sites across 14 repos. The effect in the ingest hot path:

**`_handle_reviews` (1000-review message, typical):**
1. `bulk_upsert(reviews)` → execute_values (correct, one stmt) → **commit** → fsync
2. `mark_reviews_complete(appid, ...)` → UPDATE → **commit** → fsync
3. `mark_reviews_crawled(appid)` → UPDATE → **commit** → fsync
4. (conditional) `set_has_early_access_reviews(appid)` → UPDATE → **commit** → fsync

Three to four fsyncs when the work could close with one. On `gp3` that's
~3–10 ms wasted per message; at `batch_size=40` × `max_concurrency=12`
= hundreds of extra WAL syncs per minute under load.

**`_handle_metadata`** is worse: `game_repo.upsert` + `tag_repo.upsert_genres`
(with nested DELETE + per-row INSERTs and a commit) + `tag_repo.upsert_categories`
(same shape) + `catalog_repo.set_meta_status` — 4–6 commits per metadata
message. (The per-row INSERT loop in `upsert_genres` / `upsert_categories`
is a separate smell flagged in `scripts/prompts/upgrade-rds-instance-class.md`
under "deferred sub-improvement" — out of scope here.)

Autocommit is NOT on (`psycopg2` default is off; nothing flips it except
the `REFRESH MATERIALIZED VIEW CONCURRENTLY` path in `matview_repo.py:314-337`,
which correctly saves/restores the prior setting). So we are *batching*
writes within each repo method; we're just not batching *across* them.

## Changes

### 1. Remove `conn.commit()` from every write-side repository method

Delete the trailing `self.conn.commit()` in every repo method listed
above (all 14 repo files). Leave the `self.conn.rollback()` in
`game_repo.py:781` — that's inside a narrow try/except handling a unique
constraint recovery and should stay, but retarget it so the handler
re-enters on a clean tx (note in-line or move to caller; see agent
discretion).

Do NOT touch `matview_repo.py:314-337` — the autocommit dance around
`REFRESH MATERIALIZED VIEW CONCURRENTLY` is correct and required by
Postgres; leave it exactly as-is.

### 2. Handlers own the commit boundary

Update every handler that calls repo write methods to wrap its business
unit of work in an explicit commit/rollback. Preferred pattern — a
helper on `BaseRepository` (or a free function in `utils/db.py`) that
wraps the implicit-transaction pattern cleanly:

```python
from contextlib import contextmanager

@contextmanager
def transaction(conn):
    try:
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise
```

Call sites to update (hot-path first, then the rest):

- `src/lambda-functions/lambda_functions/crawler/ingest_handler.py` —
  `_handle_metadata`, `_handle_tags`, `_handle_reviews`: wrap the DB
  work in a `with transaction(get_conn()):` block. Leave the
  `get_conn().rollback()` inside the `except Exception` at line 141 —
  redundant with the context manager but harmless safety net. Actually
  remove it once the context manager is in place; the manager handles it.
- `src/lambda-functions/lambda_functions/analysis/handler.py` — each
  Step Function task wraps its writes.
- `src/lambda-functions/lambda_functions/admin/handler.py` — per-action
  wrap.
- `src/lambda-functions/lambda_functions/api/handler.py` — any write
  endpoints (report purchase ingestion, waitlist signup) wrap.
- Any `scripts/*.py` or `sp.py` admin tooling that calls repo write
  methods directly.

Grep for `repo.<method>(…)` where the method is a known writer and
audit whether it's inside a `with transaction(...)` — anything missed
will silently not persist.

### 3. Update tests

- Repo unit tests (`tests/repositories/*`) probably assume commit-in-method
  semantics. Switch them to either commit in the test harness or use the
  new `transaction()` helper.
- Handler tests likely already mock the connection; verify they still
  pass once the handler owns the commit.
- Integration tests against `steampulse_test` should catch any missed
  callers: an uncommitted write becomes a rollback when the conn cycles,
  and the test assertion fails.

### 4. Sequencing

Do the ingest path first (`_handle_reviews`, then `_handle_metadata`,
then `_handle_tags`), deploy, watch `AWS/Lambda` `Duration.Avg` and RDS
`WriteLatency`. Then roll through analysis / admin / API handlers. Any
single commit-per-repo-method change is backward-compatible with the
caller once the caller wraps in `transaction()`.

## Files to modify

- `src/library-layer/library_layer/repositories/*.py` — 14 files, ~30
  commit-call removals.
- `src/library-layer/library_layer/utils/db.py` — add the `transaction`
  context manager (or put it on `BaseRepository`).
- `src/lambda-functions/lambda_functions/crawler/ingest_handler.py` —
  wrap all three handlers.
- `src/lambda-functions/lambda_functions/analysis/handler.py`,
  `admin/handler.py`, `api/handler.py` — wrap all write paths.
- `sp.py` and any `scripts/*.py` that calls write methods.
- Tests: `tests/repositories/*`, `tests/handlers/*` as needed.

## Out of scope

- **Bulk-ifying `upsert_genres` / `upsert_categories`** — flagged in
  `scripts/prompts/upgrade-rds-instance-class.md` under "deferred
  sub-improvement". Related but separate.
- **Stopping the blanket review crawl** — that's
  `scripts/prompts/analysis-demand-review-crawl.md`. Independent win.
- **Connection pooling / RDS Proxy** — not needed at current conn count.
- **RDS instance upgrade** — parked in `upgrade-rds-instance-class.md`.

## Verification

1. **Unit + repo tests:**
   ```
   poetry run pytest tests/repositories/ tests/handlers/
   ```
   Expect green after test updates.

2. **Ingest smoke test (local or staging):**
   - Process a batch of review SQS messages against `steampulse_test` /
     staging. Confirm reviews land in `reviews` and catalog fields
     (`reviews_completed_at`, `review_crawled_at`) update correctly.
   - Force an intentional mid-handler exception (patch a repo method
     to raise) — confirm nothing was partially committed (no review
     rows, no catalog timestamp flip).

3. **Post-deploy:**
   - `AWS/Lambda` `Duration.Avg` on `SpokeIngestFn` drops 5–15%
     (mainly on review-heavy batches).
   - RDS `CommitLatency` / `WriteIOPS` drop proportional to the fewer
     commit calls. (Aurora/RDS emits `CommitLatency` sparingly on
     t4g-class; `WriteIOPS` is the more reliable proxy.)
   - No increase in `db_write_retry` log lines
     (`src/library-layer/library_layer/utils/db.py:213`) — the
     `retry_on_transient_db_error` decorator's rollback helper
     (`_rollback_before_retry`) continues to work because the
     transaction boundary just moved up, not away.

## Risk

The refactor's blast radius is every DB write path. The safe sequencing
(ingest first, then analyze the impact before rolling through analysis/
admin/api) contains that. The transaction-in-handler pattern is the
Postgres norm — this is moving toward convention, not away from it.
