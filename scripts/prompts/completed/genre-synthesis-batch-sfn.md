# Phase 4 — Migrate genre synthesis to Anthropic batch + Step Functions

## Context

Phase 4 cross-genre synthesis today is an SQS-triggered Lambda
(`src/lambda-functions/lambda_functions/genre_synthesis/handler.py`) that calls
`GenreSynthesisService.synthesize(slug, prompt_version)` using the real-time
Bedrock Converse path (`make_converse_backend`). Every other LLM workflow in
SteamPulse (Phase 1-3 chunk / merge / synthesis) goes through
`AnthropicBatchBackend` orchestrated by Step Functions, producing structured
tracking in `batch_executions` and ~50% LLM cost.

Phase 4 is the outlier: no `batch_executions` row (so `scripts/logs.py
--batches` can't see it), no in-flight visibility beyond CloudWatch, and full
real-time LLM pricing. The Anthropic batch API accepts single-request batches
at the same 50% discount — the only meaningful cost is baseline latency (1-5
min typical, up to 24 h worst case) and ~500 LOC of scaffolding that can
largely mirror Phase 1-3.

Goal: rebuild Phase 4 to match the Phase 1-3 pattern exactly — same
state-machine shape, same `batch_executions` tracking, same
`AnthropicBatchBackend` — so operators get a single consistent LLM workflow
across the stack.

**Explicitly out of scope:** any EventBridge / scheduled-refresh wiring. This
prompt migrates the execution model only. The existing weekly
`GenreSynthesisWeeklyRule` (currently `enabled=False` per
`compute_stack.py:821-835`) is left untouched and the old `scan_stale` branch
in the current handler is simply deleted — no cron replacement, no new
scheduled Lambda. Manual operator trigger via `trigger_genre_synthesis.py` is
the only entry point.

## Approach

Reuse everything reusable: `AnthropicBatchBackend` (`prepare` / `submit` /
`status` / `collect` — unchanged), `BatchExecutionRepository` (arbitrary
`phase` string — add `"genre_synthesis"`), `check_batch_status.py` Lambda
(works off `job_id` — no changes). Split `GenreSynthesisService.synthesize()`
into `prepare_batch()` + `collect_batch()` methods threaded via Step Function
state. Build one per-slug SFN and one orchestrator SFN that fans out across
slugs (mirror `batch_analysis_stack.py` structure). Delete the SQS queue,
DLQ, the SQS-triggered handler, and the SSM queue URL param.

## Critical files

**Service refactor:**
- `src/library-layer/library_layer/services/genre_synthesis_service.py` —
  split `synthesize()` into:
  - `prepare_batch(slug, prompt_version, execution_id) -> PrepareResult`:
    resolve slug → eligibility query → `MIN_REPORTS_PER_GENRE` floor →
    compute `input_hash` → cache-hit short-circuit (return `skip=True`,
    `touch_computed_at`, do not submit) → build `LLMRequest` →
    `backend.prepare([request], phase='genre_synthesis')` →
    `backend.submit(prepared, 'genre_synthesis', phase='genre_synthesis')` →
    `batch_executions.insert(phase='genre_synthesis', …)` → return
    `PrepareResult` with `job_id`, `selected_appids`, `display_name`,
    `avg_positive_pct`, `median_review_count`, `input_hash`.
  - `collect_batch(slug, job_id, selected_appids, display_name,
    avg_positive_pct, median_review_count, input_hash, prompt_version) ->
    GenreSynthesisRow`:
    `backend.collect(job_id, default_response_model=GenreSynthesis)` →
    extract single result → build `GenreSynthesisRow` → `synthesis_repo.upsert` →
    `batch_executions.mark_completed(...)` with token counts.
  - Delete the old `synthesize()` method entirely in PR 1 and rewrite
    `tests/services/test_genre_synthesis_service.py` against the two new
    methods — no compatibility wrapper (pre-launch, no consumers besides
    tests).
  - Change `__init__` param `llm_backend: ConverseBackend` to
    `llm_backend: AnthropicBatchBackend` and drop the `ConverseBackend`
    import. `batch_executions` is written by prepare/collect, so inject a
    `BatchExecutionRepository` dep alongside the existing repos.

**New Lambda handlers** (`src/lambda-functions/lambda_functions/genre_synthesis/`):
- `prepare.py` — thin shell around `GenreSynthesisService.prepare_batch`.
  Input: `{"slug", "prompt_version", "execution_id"}`. Output:
  `{"slug", "job_id" | null, "skip": bool, "display_name", "selected_appids",
  "avg_positive_pct", "median_review_count", "input_hash", "prompt_version",
  "execution_id"}` — same threading shape Phase 1-3's `prepare_phase` uses.
- `collect.py` — shell around `GenreSynthesisService.collect_batch`. Input
  is the prepare output fields threaded forward by Step Functions
  (`slug`, `job_id`, `execution_id`, `selected_appids`, `display_name`,
  `avg_positive_pct`, `median_review_count`, `input_hash`,
  `prompt_version`) — the `CheckStatus` result lives at
  `$.status_result` and is consumed by the SFN Choice, not by Collect.
  Writes `mv_genre_synthesis` row, marks `batch_executions` completed.
- **Delete:** `handler.py` (SQS + scan_stale branches, both gone).

**Reuse as-is (no changes):**
- `src/library-layer/library_layer/llm/anthropic_batch.py` — batch backend.
- `src/lambda-functions/lambda_functions/batch_analysis/check_batch_status.py` —
  operates on `job_id` only; already supports the Anthropic path. Shared
  across Phase 1-3 and Phase 4 SFNs.

**Schema change (needed for slug-keyed tracking):**
- New migration `src/lambda-functions/migrations/0053_batch_executions_slug.sql`:
  `ALTER TABLE batch_executions ALTER COLUMN appid DROP NOT NULL;` +
  `ADD COLUMN slug TEXT;` + `ADD CONSTRAINT batch_executions_subject_check
  CHECK ((appid IS NOT NULL) <> (slug IS NOT NULL));` + index on `slug`.
  The FK `REFERENCES games(appid)` is preserved (nullable FK is valid).
- `BatchExecutionRepository.insert`: make `appid: int | None = None`, add
  `slug: str | None = None`. Raise if neither/both set.
- `BatchExecution` model: `appid: int | None = None`, `slug: str | None =
  None`. Nullable-on-both-sides maps directly to the DB column shape so
  NULL round-trips cleanly without a translation layer.
- `scripts/logs.py` query adds `be.slug`; rendering splits the
  first column into a narrow `subject` (appid or `—` for slug rows) and
  a wider `name` (game_name or slug) so the `genre` badge + slug read
  cleanly alongside Phase 1-3 rows.

**CDK** (`infra/stacks/`):
- `compute_stack.py` — delete the `GenreSynthesisFn` PythonFunction,
  its dedicated `genre_synthesis_role`, its SQS event source, and the
  `GenreSynthesisWeeklyRule` + target wiring. Drop the
  `genre_synthesis_queue` constructor param from `ComputeStack.__init__`
  and from `application_stage.py`. No replacement Lambda here — the new
  prepare/collect functions live in `batch_analysis_stack.py` (below).
- `batch_analysis_stack.py` — co-locate the new genre-synthesis Lambdas
  and state machines at the bottom of the stack, reusing the existing
  `batch_lambda_role`, `_make_batch_fn` helper, `check_status_fn`
  poller, and the `steampulse-batch-*-{env}` IAM wildcard for
  parent→child `StartExecution`:
  - `GenreSynthesisPrepareFn`, `GenreSynthesisCollectFn` via
    `_make_batch_fn` (same role/env/layer as Phase 1-3 Lambdas).
  - **Per-slug SFN** `steampulse-batch-genre-synthesis-{env}`
    (name uses the `-batch-` prefix so it matches the IAM wildcard
    on `batch_lambda_role`; mirrors the Phase 1-3 shape):
    `PrepareGenreSynthesis` → `GenreSynthesisSkipped? (Choice —
    skip==true → Done)` → `WaitGenreSynthesis (Wait 300s)` →
    `CheckGenreSynthesisStatus` (invokes shared `check_status_fn`) →
    `GenreSynthesisBatchComplete? (Completed → Collect; Failed →
    Fail; else → Wait)` → `CollectGenreSynthesis` → `Done`.
  - **Orchestrator SFN** `steampulse-batch-genre-synthesis-orchestrator-{env}`:
    `CountSlugs (Pass)` → `FanOutSlugs (DistributedMap,
    max_concurrency=2, tolerated_failure_percentage=10)` → invoke
    per-slug SFN via `StepFunctionsStartExecution(RUN_JOB)` → `Done`.
    Input contract: `{"slugs": [...], "prompt_version": "..."}`. No
    `scan_stale` shape, no EventBridge entry point.
  - `genre_state_machine.grant_start_execution(genre_orchestrator)` +
    `states:DescribeExecution` / `states:StopExecution` grants.
- New SSM params (published from `batch_analysis_stack.py`):
  - `/steampulse/{env}/genre-synthesis/sfn-arn`
  - `/steampulse/{env}/genre-synthesis/orchestrator-sfn-arn`
- `messaging_stack.py` — delete `genre_synthesis_queue`,
  `genre_synthesis_dlq`, their visibility config, their tags, and the
  `GenreSynthesisQueueUrlParam` / `GenreSynthesisQueueArnParam` /
  `GenreSynthesisDlqArnParam` SSM outputs.
- `library_layer/config.py` — delete `GENRE_SYNTHESIS_QUEUE_PARAM_NAME`.
  Add `GENRE_SYNTHESIS_ORCHESTRATOR_SFN_PARAM_NAME: str = ""` for the
  trigger script to resolve.
- `library_layer/events.py` — delete `GenreSynthesisJobMessage` and the
  `"genre_synthesis_job"` entry in `SqsMessageType`.
- `.env.staging` / `.env.production` — swap
  `GENRE_SYNTHESIS_QUEUE_PARAM_NAME=/.../messaging/genre-synthesis-queue-url`
  for
  `GENRE_SYNTHESIS_ORCHESTRATOR_SFN_PARAM_NAME=/.../genre-synthesis/orchestrator-sfn-arn`.

**CLI updates:**
- `scripts/trigger_genre_synthesis.py` — swap the SQS publish for
  `boto3.client("stepfunctions").start_execution` on the orchestrator SFN.
  Payload: `{"slugs": args.slugs, "prompt_version": prompt_version}`. Print
  execution ARN + console URL (mirror `scripts/sp.py:cmd_batch`). Resolve
  SFN ARN via SSM `GENRE_SYNTHESIS_ORCHESTRATOR_SFN_PARAM_NAME` path per env.
- `scripts/logs.py`:
  - Add `"genre_synthesis": "genre"` to `_PHASE_SHORT` so `--batches`
    renders the badge correctly.
  - Include `be.slug` in the `_fetch_batches` query and group on it in
    `_group_by_execution`; split the first column into a narrow
    `subject` (appid or `—`) and a wider `name` (game_name or slug)
    so slug-keyed rows render cleanly.
  - Add `"synthesis"` / `"synthesis-collect"` log-group shorthands
    (`/steampulse/{env}/batch-genre-synthesis-{prepare,collect}`) and
    two saved queries (`synthesis-activity`, `synthesis-errors`) that
    search across both log groups via `extra_groups`.

## Ship order

Phase 4 has no live consumers besides the trigger script, so the five
PR-slicing below is optional scaffolding; shipping the full cutover in
one branch is fine pre-launch (no dual-path flag, no staging soak
between steps). The outline is preserved as a sequencing guide.

1. **Service refactor (PR 1).** Extract `prepare_batch` + `collect_batch`
   from `synthesize()` in `genre_synthesis_service.py`. Unit tests against
   `steampulse_test` DB covering: eligibility floor, cache-hit short-circuit
   in prepare, collect upserts row + marks `batch_executions` completed,
   `input_hash` stability across re-runs.
2. **Lambdas (PR 2).** Write `prepare.py`, `collect.py`. Handler-shell
   tests cover input/output shape.
3. **CDK scaffolding (PR 3).** Add the two new state machines + two new
   Lambdas + SSM params in `batch_analysis_stack.py`. Delete the old
   `GenreSynthesisFn` + SQS event source from `compute_stack.py` in the
   same PR — there are no live consumers to keep alive in parallel.
4. **Cutover (PR 4).** Update `trigger_genre_synthesis.py` to start the
   orchestrator SFN. Deploy to staging, manually trigger for a slug with
   ≥30 reports, watch SFN execution + `batch_executions` row + final
   `mv_genre_synthesis` row.
5. **Cleanup (PR 5, or folded into PR 3).** Delete the SQS queue + DLQ
   from `messaging_stack.py`, the `genre_synthesis_queue` param from
   `ComputeStack.__init__` + `application_stage.py`, the
   `GENRE_SYNTHESIS_QUEUE_PARAM_NAME` field from config + env files,
   and the `GenreSynthesisJobMessage` event class. Add
   `"genre_synthesis": "genre"` to `_PHASE_SHORT` in `scripts/logs.py`.

## Verification

**Unit / integration** (PR 1 + 2):
- `tests/services/test_genre_synthesis_service.py`:
  - `prepare_batch` returns `skip=True` when an `mv_genre_synthesis` row with
    matching `input_hash` exists; no batch submitted; no `batch_executions`
    row inserted.
  - `prepare_batch` raises `NotEnoughReportsError` when eligible reports <
    `MIN_REPORTS_PER_GENRE`.
  - `prepare_batch` inserts a `batch_executions` row with
    `phase="genre_synthesis"` and returns a `job_id` when eligible ≥ min.
  - `collect_batch` upserts `mv_genre_synthesis` and calls `mark_completed`
    with token counts populated.
  - `collect_batch` guards against silent corruption: `record_id`
    mismatch, multiple results, or zero results all flip the tracking
    row to `failed` via `mark_failed`.
  - `collect_batch` safety net: an unknown model_id in the pricing
    table logs + records cost=0 rather than leaving the tracking row
    stranded in `submitted`.
- `tests/handlers/test_genre_synthesis_prepare.py` and
  `tests/handlers/test_genre_synthesis_collect.py`: Lambda-shell input /
  output shape validation, including numeric coercion for fields that
  arrive as strings from JSONPath (`avg_positive_pct`,
  `median_review_count`, `selected_appids`).
- `tests/models/test_batch_execution.py`: round-trip `appid`/`slug`
  nullability matches the DB XOR shape.
- Tests must use `steampulse_test` DB (repo convention).

**Staging end-to-end** (PR 4):
1. Seed staging with enough RDB per-game reports (≥30 games with
   `review_count >= 200`) so the eligibility floor is met.
2. `poetry run python scripts/trigger_genre_synthesis.py --env staging
   --slugs <seeded-slug>` → prints SFN execution ARN.
3. Watch execution in AWS console: Prepare → Wait → CheckStatus (polls
   Anthropic) → Collect → Done. Typical duration 1-5 min.
4. Confirm `SELECT * FROM batch_executions WHERE phase='genre_synthesis'
   ORDER BY submitted_at DESC LIMIT 1` has a completed row with non-null
   `input_tokens`, `output_tokens`, `estimated_cost_usd`.
5. Confirm `SELECT computed_at, input_hash FROM mv_genre_synthesis WHERE
   slug=<slug>` has a fresh row.
6. Re-run step 2 with the same slug — SFN short-circuits at Prepare
   (`skip=true`), no batch submitted, `computed_at` bumped via
   `touch_computed_at`.
7. `poetry run python scripts/logs.py --batches --all` shows the
   `genre_synthesis` row alongside Phase 1-3 rows with the `genre` badge
   (after PR 5 adds the mapping).

**Post-cleanup** (PR 5):
- `aws sqs list-queues --queue-name-prefix
  SteamPulse-Staging-Messaging-GenreSynthesis` returns nothing.
- `aws lambda list-functions --query 'Functions[?contains(FunctionName,
  \`GenreSynthesisFn\`)]'` shows only the two new Lambdas (Prepare /
  Collect), not the old `GenreSynthesisFn`.
- `grep -rn "GENRE_SYNTHESIS_QUEUE_PARAM_NAME\|genre_synthesis_queue"
  src/ infra/ scripts/` returns empty.
