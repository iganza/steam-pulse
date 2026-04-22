# Migrate matview refresh to Step Functions with per-view fan-out

## Context

Today the `matview_refresh_fn` Lambda
(`src/lambda-functions/lambda_functions/admin/matview_refresh_handler.py`)
runs `REFRESH MATERIALIZED VIEW CONCURRENTLY` sequentially over the 18
names in `MATVIEW_NAMES` (`src/library-layer/library_layer/repositories/matview_repo.py:10-29`).
It has a 5-minute timeout, `reserved_concurrent_executions=1`, and is
triggered three ways (`infra/stacks/compute_stack.py:572-629`):

1. `cache_invalidation_queue` SQS (SNS fan-in: `report-ready`,
   `catalog-refresh-complete`, `batch-analysis-complete`).
2. `MatviewRefreshSchedule` EventBridge rule — `rate(6 hours)`, prod only.
3. Force-refresh bypass when the SNS event is `batch-analysis-complete`
   (debounce is skipped).

**The problem.** Total refresh time is climbing as the catalog grows and
new views are added (recent additions `mv_catalog_reports`,
`mv_audience_overlap`, `mv_discovery_feeds` are large). When total
duration exceeds 5 min the Lambda times out mid-loop:

- Remaining views are not refreshed that cycle.
- The SQS message retries (`max_receive=3`) and ultimately DLQs if the
  same timeout keeps firing.
- There is no per-view observability — `matview_refresh_log` records a
  single `views_refreshed TEXT[]` on full success, nothing on partial
  progress.
- `reserved_concurrency=1` means a stuck refresh blocks all triggers.

**Why not a true "async kickoff + poll" pattern.** Postgres
`REFRESH MATERIALIZED VIEW` is synchronous on the client connection —
whoever issues the statement holds the connection until it finishes.
The obvious async options are each blocked on RDS:

- `dblink_send_query` kicks off async on a named connection, but the
  connection dies with the Lambda and the query aborts — Lambda's
  stateless model breaks the polling cycle.
- `pg_background` (`pg_background_launch`) detaches cleanly but is not
  available on RDS PostgreSQL.
- `pg_cron` + queue-table works but adds an extension, a cron schedule,
  and a new operational surface for a problem the fan-out solves.

Someone has to hold the DB connection open for the duration of each
`REFRESH`. The cheapest "someone" that fits the existing stack is a
short-lived Lambda bounded per-view — not the 5-minute aggregate Lambda
we have today.

**Goal.** Replace the single aggregate Lambda with a **Step Function
orchestrator + Map state + per-view worker Lambda**, mirroring the
shape of `batch_analysis_stack.py` so operators see a consistent
pattern. Each worker gets a 15-min ceiling (3× the current aggregate
budget for one view) and runs in parallel with configurable
`MaxConcurrency`. Per-view success/failure/duration lands in an extended
`matview_refresh_log`. Compute cost is negligible (~$0.0001/cycle × 4
cycles/day) and fits the fixed-cost-infra preference.

**Explicitly out of scope.** No migration to pg_cron / dblink / any
DB-side scheduler. No change to downstream consumers of the
refresh-complete signal (none exist yet — nothing listens for matview
refresh today). No expansion of the `MATVIEW_NAMES` list. No pre-launch
feature flag (per repo convention) — single cutover.

## Approach

Keep `MATVIEW_NAMES` as the source of truth. Replace the single handler
with a three-Lambda pipeline wired through a Step Function:

1. **Start** — debounce gate + cycle bookkeeping; returns the view list
   to fan out or `skip=true`.
2. **Map** — one worker Lambda per view, `REFRESH MATERIALIZED VIEW
   CONCURRENTLY <name>` (exactly what `refresh_all` does today, but
   scoped to one view). Errors don't abort the Map
   (`tolerated_failure_percentage=100`); partial failures are captured
   and surface at Finalize.
3. **Finalize** — aggregate per-view results into the existing
   `matview_refresh_log` row, set final `status`.

The SFN is triggered by the same three sources, but routed differently:

- EventBridge rule → `StartExecution` directly (prod only).
- SQS → a **shrunken trigger Lambda** that reads the SQS batch, detects
  the force-refresh flag, and calls `StartExecution` with
  `{"force": true|false}`. Keeping a Lambda between SQS and SFN (rather
  than EventBridge Pipes) preserves the force-refresh detection logic
  and keeps one place for the debounce-bypass rule.

MaxConcurrency on the Map state is **1** — serial execution, one view
at a time, preserving today's DB load profile. The win over the
current Lambda loop isn't parallelism; it's that each view gets its
own 15-min invocation budget (so no single slow view can time-out the
whole cycle) plus per-view observability and retry semantics from the
SFN. Worker Lambda `reserved_concurrent_executions=1` matches. If DB
headroom ever justifies parallelism, MaxConcurrency is a one-line
bump — but default to serial.

## Critical files

**Repo refactor:**
- `src/library-layer/library_layer/repositories/matview_repo.py`:
  - Add `refresh_one(name: str) -> int`: validates `name in
    MATVIEW_NAMES` (raise `ValueError` otherwise — SQL injection guard
    on the `sql.Identifier` path), opens autocommit, runs `REFRESH
    MATERIALIZED VIEW CONCURRENTLY <name>`, returns `duration_ms`.
    Callers get exceptions on failure; no swallow-and-log.
  - Extend `log_refresh` signature to match the new schema (below).
    Replace the old `(duration_ms, views)` shape with `start_cycle(
    cycle_id) -> None` (insert `status='running'` row) and
    `complete_cycle(cycle_id, duration_ms, per_view_results) -> None`
    (update to `complete` / `partial_failure` / `failed`).
  - Keep `refresh_all()` and mark deprecated — delete in the same PR
    once the new handlers land. Only `admin/matview_refresh_handler.py`
    calls it today (verify with grep before delete).

**Schema (migration `0054_matview_refresh_log_detail.sql`):**
```sql
-- depends: 0053_batch_executions_slug

ALTER TABLE matview_refresh_log
    ADD COLUMN IF NOT EXISTS cycle_id TEXT,
    ADD COLUMN IF NOT EXISTS status TEXT
        CHECK (status IN ('running', 'complete', 'partial_failure', 'failed')),
    ADD COLUMN IF NOT EXISTS per_view_results JSONB,
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS idx_matview_refresh_log_cycle_id
    ON matview_refresh_log(cycle_id) WHERE cycle_id IS NOT NULL;
```
Also mirror the new columns in
`src/library-layer/library_layer/schema.py:403` so fresh test DBs have
them. Backfill-safe: existing rows have `cycle_id=NULL`, `status=NULL`
and are treated as "legacy, ignore" by the new debounce read.

**New Lambdas** (`src/lambda-functions/lambda_functions/matview_refresh/`;
delete `admin/matview_refresh_handler.py`):

- `start.py` — Input: `{"force": bool, "cycle_id": str}` (cycle_id = SFN
  execution name, threaded in via `$$.Execution.Name`). Behavior:
  - If `not force` and `get_last_refresh_time() < DEBOUNCE_SECONDS`
    ago: return `{"skip": true}`.
  - Else: `start_cycle(cycle_id)`, return `{"skip": false, "cycle_id":
    cycle_id, "views": list(MATVIEW_NAMES)}`.
- `refresh_one.py` — Worker. Input: `{"name": str, "cycle_id": str}`.
  Calls `matview_repo.refresh_one(name)`; returns `{"name", "success":
  true, "duration_ms"}`. On exception: return `{"name", "success":
  false, "duration_ms", "error": str(e)}` (DO NOT re-raise — Map state
  must see a "successful" task result so it can aggregate failures at
  Finalize, otherwise the whole Map aborts under default retry
  behavior). Lambda timeout: 15 minutes. Memory: 256 MB.
- `finalize.py` — Input: `{"cycle_id": str, "start_time_ms": int,
  "results": [{"name", "success", "duration_ms", "error"?}]}`.
  Computes total duration, per-view results JSONB, sets status:
  - all success → `complete`
  - some failures → `partial_failure` (DON'T raise — failure is
    already logged per-view; raising would retry the SFN)
  - all failures → `failed` + raise so the SFN fails visibly.
- `trigger.py` — SQS shell. Reads the batch, extracts `force` via the
  same `_is_force_refresh` logic currently in `matview_refresh_handler`,
  calls `stepfunctions.start_execution(stateMachineArn=<from env>,
  name=<uuid>, input=json.dumps({"force": force}))`. Returns
  immediately; no debounce check here (Start does it).

**CDK** (`infra/stacks/compute_stack.py`):
- Delete `MatviewRefreshFn`, `MatviewRefreshRole`, the SQS event source
  wiring (lines 572-619), and the `MatviewRefreshSchedule` EventBridge
  rule (lines 621-629).
- Add three Lambdas via a small helper (mirror `_make_batch_fn` pattern):
  `MatviewRefreshStartFn`, `MatviewRefreshWorkerFn`
  (`reserved_concurrent_executions=1`), `MatviewRefreshFinalizeFn`. All
  share a single role with VPC access + `db_secret` read. Log group
  `/steampulse/{env}/matview-refresh-{start,worker,finalize}`, 1-week
  retention.
- Add `MatviewRefreshTriggerFn` (not VPC — no DB access; only calls
  `sfn:StartExecution`) with the SQS event source from
  `cache_invalidation_queue`, batch size 1. Grant
  `sfn.grant_start_execution(trigger_fn)`.
- Build the state machine `steampulse-matview-refresh-{env}`:
  ```
  Start (LambdaInvoke: MatviewRefreshStartFn)
    ├─ skip==true  → Done (Succeed)
    └─ skip==false → RecordStartTime (Pass, sets $.start_time_ms)
                   → Map (MATVIEW_NAMES, MaxConcurrency=1,
                          tolerated_failure_percentage=100,
                          ItemsPath=$.views,
                          ItemSelector={"name.$":"$$.Map.Item.Value",
                                        "cycle_id.$":"$.cycle_id"})
                        └─ iter: RefreshOne (LambdaInvoke:
                                 MatviewRefreshWorkerFn,
                                 Retry: [Lambda.ServiceException:
                                 2 attempts, 5s backoff])
                   → Finalize (LambdaInvoke:
                               MatviewRefreshFinalizeFn,
                               ResultPath=$.finalize)
                   → Done
  ```
  Use `JsonPath.string_at("$$.Execution.Name")` for `cycle_id`
  threading. `type=StateMachineType.STANDARD` (needs long execution +
  history visibility).
- Add EventBridge rule `MatviewRefreshSchedule` targeting the SFN
  directly via `events_targets.SfnStateMachine(state_machine,
  input=events.RuleTargetInput.from_object({"force": false}))`.
  `enabled=config.is_production` (per `feedback_no_staging_schedules`).
- SSM param: `/steampulse/{env}/matview-refresh/sfn-arn`.
- Consumer: `MatviewRefreshTriggerFn` reads the ARN from env (populated
  via `config.to_lambda_env`).

**Config** (`src/library-layer/library_layer/config.py`):
- Add `MATVIEW_REFRESH_SFN_ARN_PARAM_NAME: str = ""`.
- `.env.staging` / `.env.production`:
  `MATVIEW_REFRESH_SFN_ARN_PARAM_NAME=/steampulse/{env}/matview-refresh/sfn-arn`.

**Operator CLI** (`scripts/sp.py`):
- Add `sp.py matview-refresh --env {staging,production} [--force]` that
  resolves the SFN ARN from SSM and calls `start_execution` with
  `{"force": args.force}`. Prints execution ARN + console URL. This
  replaces today's ad-hoc SQS publish trick for manual staging refresh.

## Ship order

No live external consumers of the refresh-complete signal; pre-launch
catalog (per repo convention). One bundled PR is fine, but the below
sequencing keeps review chunks small:

1. **Migration + repo (PR 1).** `0054_matview_refresh_log_detail.sql`,
   `refresh_one`, `start_cycle` / `complete_cycle`, schema.py sync.
   Delete `refresh_all` once callers are gone in PR 2. Tests against
   `steampulse_test` DB.
2. **Lambdas (PR 2).** `start.py`, `refresh_one.py`, `finalize.py`,
   `trigger.py`. Delete `admin/matview_refresh_handler.py` and its
   test file. Handler-shell tests for each.
3. **CDK (PR 3).** New Lambdas + SFN + EventBridge + SSM + SQS event
   source on `trigger_fn`. Delete old `MatviewRefreshFn`,
   `MatviewRefreshRole`, `MatviewRefreshSchedule`, and the old Lambda's
   SQS event source in the same PR (no dual path).
4. **Staging verification.** Deploy; run `sp.py matview-refresh --env
   staging`; eyeball SFN execution; eyeball `matview_refresh_log`.
5. **Prod rollout.** User deploys (per `feedback_no_deploy`).

## Verification

**Unit / integration** (`steampulse_test` DB):
- `tests/repositories/test_matview_repo.py`:
  - `refresh_one("mv_genre_counts")` succeeds, returns `duration_ms >
    0`, matview's data is updated (INSERT a row in source table, call
    refresh, assert matview reflects it).
  - `refresh_one("not_a_view")` raises `ValueError`.
  - `start_cycle("abc")` inserts a row with `status='running'`,
    `cycle_id='abc'`, `started_at=NOW()`.
  - `complete_cycle("abc", 1234, {...})` updates the row to
    `status='complete'`, `duration_ms=1234`,
    `per_view_results=<jsonb>`.
  - `get_last_refresh_time()` returns the most recent
    `status='complete'` row's `refreshed_at`, ignores `running` /
    `failed` / legacy-NULL-status rows.
- `tests/handlers/test_matview_refresh_start.py`:
  - `force=false` + recent complete cycle → `skip=true`, no
    `start_cycle` insert.
  - `force=false` + no recent cycle → `skip=false`, `start_cycle`
    inserted, `views` equals `list(MATVIEW_NAMES)`.
  - `force=true` + recent cycle → `skip=false` (debounce bypassed).
- `tests/handlers/test_matview_refresh_worker.py`:
  - Success path returns `{"name", "success": true, "duration_ms"}`.
  - `refresh_one` raising psycopg2.Error → returns `{"success":
    false, "error": <str>}`, does NOT re-raise.
- `tests/handlers/test_matview_refresh_finalize.py`:
  - All successes → `status='complete'`, no raise.
  - Mixed → `status='partial_failure'`, no raise.
  - All failures → `status='failed'`, raises.
- `tests/handlers/test_matview_refresh_trigger.py`:
  - Force-event SQS batch → `start_execution` called with
    `force=true`.
  - Non-force SQS batch → `start_execution` called with `force=false`.
  - Malformed record → skipped (warn), other records processed.
- All tests use `steampulse_test` (repo convention); no mocked DB.

**Staging e2e:**
1. `poetry run python scripts/sp.py matview-refresh --env staging` →
   prints execution ARN.
2. Watch in AWS console: Start → Map (serial, one view at a time) →
   Finalize → Done. Expect the 18 iterations to walk through
   sequentially at roughly the current aggregate duration (the SFN
   doesn't speed things up — it just removes the 5-min ceiling and
   gives per-view visibility).
3. `SELECT cycle_id, status, duration_ms,
   jsonb_object_keys(per_view_results) FROM matview_refresh_log WHERE
   cycle_id IS NOT NULL ORDER BY refreshed_at DESC LIMIT 1;` — confirm
   `status='complete'`, 18 view keys in `per_view_results`.
4. Re-run within 5 min → Start returns `skip=true`, SFN ends at the
   Succeed state with no Map invocations.
5. Force-refresh via SNS publish (mirrors `batch-analysis-complete`
   production path):
   ```
   aws sns publish --topic-arn <system-events-topic> --message \
     '{"event_type":"batch-analysis-complete"}'
   ```
   Confirm SFN fires despite being inside the debounce window.
6. Inject a failing view (temporarily add a bogus `ALTER MATERIALIZED
   VIEW mv_genre_counts RENAME TO ...` + revert; or point `refresh_one`
   at a non-existent view in a one-off test) → confirm SFN reaches
   Finalize with `status='partial_failure'` and the bad view's entry
   has `success: false` + error string.

**Post-cleanup:**
- `aws lambda list-functions --query 'Functions[?contains(FunctionName,
  \`MatviewRefresh\`)]'` shows exactly four: Start, Worker, Finalize,
  Trigger.
- `aws events list-rules --name-prefix MatviewRefreshSchedule` shows
  the new SFN target, not the old Lambda target.
- `grep -rn "admin/matview_refresh_handler\|refresh_all" src/ infra/
  scripts/` returns empty (except the migration history).
- Monitoring: add a CloudWatch alarm on
  `states:ExecutionsFailed{StateMachineArn=<arn>}` (threshold: 1 in
  30 min) in `monitoring_stack.py` — optional, folded into PR 3 if the
  stack already has similar alarms.

## Future work (not this PR)

If a single view's `REFRESH` ever approaches 15 min, the worker
Lambda's timeout becomes the next ceiling. At that point the right
move is likely a **pg_cron + queue-table** pattern: the Step Function
inserts `(cycle_id, view_name, status='pending')` rows into
`matview_refresh_queue`; a `pg_cron` job polls the queue every 30s and
runs `REFRESH` inside the DB; the SFN polls the queue for
`status='complete'`. That truly decouples Lambda from REFRESH
runtime, at the cost of enabling `pg_cron` in RDS parameter groups
and owning a queue processor function. Not needed today — flag it if
worker p99 creeps past 5 min.
