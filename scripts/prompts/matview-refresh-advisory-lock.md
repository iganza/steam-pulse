# Guard `MatviewRepository.refresh_one()` with a Postgres Advisory Lock

## Context

Production Postgres reported `psycopg2.errors.DeadlockDetected` on
`REFRESH MATERIALIZED VIEW CONCURRENTLY mv_audience_overlap`. The
canonical Postgres deadlock pattern for parallel `CONCURRENTLY` refresh:
two refreshes on the same matview both attempt the brief
`AccessExclusiveLock` at swap time and fight over the unique index
`mv_audience_overlap_pk` (`migrations/0044_audience_overlap_matview.sql:60-61`).

A snapshot of `pg_stat_activity` immediately after showed zero REFRESH
backends — Postgres aborted the victim, the survivor finished, and the
table is quiet again. So the deadlock event was point-in-time and has
self-resolved.

### Root cause — confirmed via `aws stepfunctions list-executions`

Inspecting `MatviewRefreshMachine` execution history for the four days
preceding the report revealed the exact pattern:

- **Apr 23 14:54: six SFN executions started in 30 seconds**
  (`14:54:06`, `14:54:07` ×2, `14:54:27`, `14:54:30`, `14:54:36`).
  Three FAILED immediately, two SUCCEEDED after victims were aborted,
  one FAILED again. Six parallel SFN executions each fanning out 18
  REFRESH workers, racing for the same matview locks.
- **Apr 23–24: hourly cadence** (~15–17 min past each hour). The
  hourly `RefreshMetaRule` (`infra/stacks/compute_stack.py:1070-1085`)
  and `RefreshReviewsRule` (`compute_stack.py:1089-1104`) drove crawler
  runs that produced `report-ready` events. The cache-invalidation-queue
  subscription filter for those events was still live at the time —
  the `env-cost-reduction` filter cleanup had been merged but not yet
  deployed.
- **Execution names `sqs-<hash>`** indicate the deployed `trigger.py`
  at the time used per-message naming, not the date-based
  `daily-YYYY-MM-DD` dedupe in current source
  (`src/lambda-functions/lambda_functions/matview_refresh/trigger.py:27-29`).
  Two messages within seconds produced two parallel SFN executions
  instead of one collapsing on `ExecutionAlreadyExists`.
- **Apr 25 00:16: a single `daily-2026-04-25` execution** — first run
  after both new dedupe and SNS disable were deployed. Still FAILED
  but solo; probably a leftover queued SQS message draining through.
- **Apr 25 00:16 onward: zero executions**. The disable in commit
  `30b06e4` is fully effective. Nothing has fired the SFN in 26+ hours.

The deadlock is therefore a **historical artifact of the pre-disable
period**. It has already stopped. But the underlying primitive —
`MatviewRepository.refresh_one()` issuing a bare
`REFRESH MATERIALIZED VIEW CONCURRENTLY` with no concurrency guard —
remains a foot-gun. Any future re-enable of the SFN, manual `sp.py
matview-refresh` double-fire, operator local-cron overlap, or ad-hoc
psql REFRESH while a Lambda is mid-flight reproduces the same deadlock.

The intent recorded in `30b06e4` was to migrate matview refresh to "an
operator-driven local cron that doesn't have the Lambda 15-min timeout."
That migration is half-done: AWS auto-triggers are removed, but the
refresh primitive doesn't prevent overlap. Add a structural guard now
so the pending operator-cron work — and any future re-enable — can't
re-introduce this deadlock.

## Goal

Make overlapping `REFRESH MATERIALIZED VIEW CONCURRENTLY` against the
**same matview** structurally impossible at the source — inside
`MatviewRepository.refresh_one()` — using a Postgres advisory lock keyed
on the matview name. A duplicate concurrent call should become a clean
*skip* (logged, returns success-with-zero-duration), not a deadlock.

Different matviews must remain independent — refreshing
`mv_catalog_reports` must never block `mv_audience_overlap`.

## Design

### 1. Add advisory-lock guard to `refresh_one`

File: `src/library-layer/library_layer/repositories/matview_repo.py`
(around lines 300-320, the `refresh_one` method)

Wrap the REFRESH in `pg_try_advisory_lock(hashtext(name))`:

- **`pg_try_advisory_lock`** (non-blocking) returns `false` immediately
  if another session already holds the lock — what we want, so a
  duplicate becomes a fast skip rather than blocking.
- **Session-scoped** (not transaction-scoped — REFRESH CONCURRENTLY
  can't run in an explicit transaction anyway). Released automatically
  when the connection closes, which neatly handles the
  Lambda-killed-mid-REFRESH case: when TCP keepalive eventually kills
  the orphan backend, the lock releases and the next run proceeds.
- **Keyed on `hashtext(name)`** so every matview gets its own lock
  namespace. Refreshing different matviews never blocks each other.

Sketch:

```python
def refresh_one(self, name: str) -> int:
    """REFRESH MATERIALIZED VIEW CONCURRENTLY <name>. Returns duration_ms,
    or -1 if another session already holds the per-matview advisory lock
    (treated as success-with-skip by callers)."""
    if name not in MATVIEW_NAMES:
        raise ValueError(f"Unknown matview name: {name!r}")
    start = time.monotonic()
    with self._get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (name,))
            acquired = cur.fetchone()[0]
            if not acquired:
                logger.warning(
                    "Skipping REFRESH — another session holds the matview lock",
                    extra={"matview": name},
                )
                return -1
            cur.execute(
                sql.SQL("REFRESH MATERIALIZED VIEW CONCURRENTLY {}").format(
                    sql.Identifier(name)
                )
            )
    return int((time.monotonic() - start) * 1000)
```

Implementation notes:
- The existing `refresh_one` already opens a fresh connection per call
  and uses `autocommit`; preserve that.
- `hashtext(name)` returns `int4`, which fits the single-arg
  `pg_try_advisory_lock(bigint)` overload.
- Do NOT call `pg_advisory_unlock` explicitly — connection close
  releases all session locks, which is the desired semantic for the
  Lambda-timeout case.

### 2. Handle the `-1` skip sentinel in the worker Lambda

File: `src/lambda-functions/lambda_functions/matview_refresh/refresh_one.py`
(around lines 34-42, the `handler()` body)

Treat `duration_ms == -1` as success-with-skip:

```python
duration_ms = _repo.refresh_one(parsed.name)
if duration_ms < 0:
    logger.info(
        "Refresh skipped — lock held by concurrent session",
        extra={"matview": parsed.name, "cycle_id": parsed.cycle_id},
    )
    return WorkerResult(
        name=parsed.name, success=True, duration_ms=0
    ).model_dump()
```

Rationale: the SFN's Map step (`compute_stack.py:763-774`) treats any
`success=False` as a per-view failure that the finalize step records.
A skipped-due-to-lock run isn't a failure — another in-flight run is
already doing the work. Reporting it as `success=True, duration_ms=0`
lets the Map continue and finalize records "skipped" cleanly.

### 3. Concurrency tests

File: `tests/repositories/test_matview_repo.py`

Add tests against `steampulse_test` (per `memory/feedback_test_db.md`):

- **`test_refresh_one_skips_when_lock_held`**: open connection A, take
  `pg_advisory_lock(hashtext('mv_audience_overlap'))` manually, then
  call `repo.refresh_one('mv_audience_overlap')` from a *different*
  connection. Assert it returns `-1` and does NOT issue REFRESH (verify
  via `pg_stat_statements` or by checking the matview's
  last-modified time hasn't advanced).
- **`test_refresh_one_succeeds_after_lock_release`**: take and release
  the manual lock; subsequent `refresh_one` call returns
  `duration_ms > 0`.
- **`test_different_matviews_do_not_block`**: hold the lock on
  `mv_catalog_reports`, call `refresh_one('mv_audience_overlap')` —
  must succeed (different lock keys).

Use two psycopg2 connections in the same test process. Skip per
`feedback_no_script_tests.md` — these are repository tests, not script
tests.

## Files Touched

| File | Change |
|------|--------|
| `src/library-layer/library_layer/repositories/matview_repo.py` | Add `pg_try_advisory_lock` guard around the REFRESH; return `-1` on skip |
| `src/lambda-functions/lambda_functions/matview_refresh/refresh_one.py` | Treat `duration_ms == -1` as success-with-skip; log the skip |
| `tests/repositories/test_matview_repo.py` | Three new concurrency tests against `steampulse_test` |

## Verification

1. Unit + concurrency tests:
   ```sh
   poetry run pytest tests/repositories/test_matview_repo.py -k 'advisory or lock' -v
   ```
2. End-to-end on staging (no schedules in staging — safe):
   ```sh
   poetry run python scripts/sp.py matview-refresh --env staging
   # While the first SFN run is still inside the Map step, in another shell:
   poetry run python scripts/sp.py matview-refresh --env staging
   ```
   The second run's worker Lambdas should log
   `"Refresh skipped — lock held by concurrent session"` for each matview
   the first run is currently REFRESHing. Both SFN executions reach
   SUCCEEDED; the finalize step on the second run records skipped views
   with `duration_ms=0`.
3. Manual deadlock simulation against `steampulse_test`:
   ```sh
   psql steampulse_test -c "BEGIN; LOCK mv_audience_overlap;" &
   poetry run python -c "
   from library_layer.repositories.matview_repo import MatviewRepository
   from library_layer.utils.db import get_conn
   print(MatviewRepository(get_conn).refresh_one('mv_audience_overlap'))
   "
   # Expect: -1, with no deadlock and no REFRESH issued.
   ```

## Out of scope

- Deleting the matview SFN, trigger Lambda, or cache-invalidation-queue
  resources. The disable in `30b06e4` keeps these for future
  re-enablement; only the SNS subscription was disabled.
- Building the new operator-driven local-cron REFRESH script — that's
  the work the original `30b06e4` commit pointed toward; the advisory
  lock is the prerequisite that makes it safe.
- Tuning psycopg2 keepalives in `library_layer/utils/db.py:get_conn` to
  kill orphan backends faster after Lambda timeouts. Worth doing
  eventually as a separate prompt; the advisory lock makes it
  unnecessary for correctness here.
- Per-matview lock metrics / dashboard for skip counts. The Lambda
  log line is sufficient for now; if skips become frequent enough to
  matter, a CloudWatch metric filter can be added later.
