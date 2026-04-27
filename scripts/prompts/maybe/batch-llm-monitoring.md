# Add monitoring for both batch LLM pipelines

## Context

`MonitoringStack` (`infra/stacks/monitoring_stack.py`) currently covers
Crawler, Spoke Ingest, API, Frontend, Email, and per-region spoke
queues — but has zero coverage for the batch LLM pipelines:

- **Phase 1-3 (batch analysis)** — `BatchAnalysisStack`: Lambdas
  `PreparePhaseFn`, `CollectPhaseFn`, `CheckBatchStatusFn`,
  `DispatchBatchFn`, state machines `steampulse-batch-analysis-{env}`
  (per-appid) and `steampulse-batch-orchestrator-{env}`.
- **Phase 4 (genre synthesis)** — also `BatchAnalysisStack` (co-located):
  Lambdas `GenreSynthesisPrepareFn`, `GenreSynthesisCollectFn`, state
  machines `steampulse-batch-genre-synthesis-{env}` (per-slug) and
  `steampulse-batch-genre-synthesis-orchestrator-{env}`.

Today, a failed batch Lambda or a stuck Step Functions execution is
visible only by directly inspecting CloudWatch logs, the SFN console, or
the `batch_executions` table. No alarms fire. This PR closes that gap
with a targeted addition to the monitoring stack — same construct style
(`cdk-monitoring-constructs` + `MonitoringFacade`) the rest of the stack
uses. Dashboard widgets for observability, alarms only where they'd
actually be actionable.

**Out of scope:** new CloudWatch Log-Insights queries (already handled in
`scripts/logs.py`); heartbeat alarms (both pipelines run via manual
operator triggers, not schedules, so missing invocations aren't a
signal); per-phase token/cost alarms (cost is tracked in the
`batch_executions` DB table, not CloudWatch metrics).

## Approach

Follow the existing monitoring-stack pattern exactly:

1. Publish any missing Lambda/SFN ARNs to SSM so monitoring can discover
   them without cross-stack CDK references.
2. In `monitoring_stack.py`, look them up via the existing `_lookup_fn`
   helper (add a `_lookup_sfn` counterpart) and wire them into the
   `MonitoringFacade`.
3. Alarm on Lambda faults, Lambda throttles, and Step Functions
   `ExecutionsFailed`. Dashboard-only for latency, invocations, and
   business metrics.

## Critical files

**SSM publishing** — verify / add ARN params in
`infra/stacks/batch_analysis_stack.py`:

Already published:
- `/steampulse/{env}/batch/sfn-arn` (per-appid SFN)
- `/steampulse/{env}/batch/orchestrator-sfn-arn` (orchestrator SFN)
- `/steampulse/{env}/batch/dispatch-fn-name`
- `/steampulse/{env}/genre-synthesis/sfn-arn`
- `/steampulse/{env}/genre-synthesis/orchestrator-sfn-arn`

Need to add (publish as `ssm.StringParameter` in `BatchAnalysisStack`):
- `/steampulse/{env}/batch/prepare-fn-arn`
- `/steampulse/{env}/batch/collect-fn-arn`
- `/steampulse/{env}/batch/check-status-fn-arn`
- `/steampulse/{env}/batch/dispatch-fn-arn` (ARN variant of the existing
  fn-name param)
- `/steampulse/{env}/genre-synthesis/prepare-fn-arn`
- `/steampulse/{env}/genre-synthesis/collect-fn-arn`

**Monitoring additions** — `infra/stacks/monitoring_stack.py`:

- Add a `_lookup_sfn(param_suffix, construct_id)` helper mirroring
  `_lookup_fn` / `_lookup_queue`, using
  `sfn.StateMachine.from_state_machine_arn(self, construct_id, arn)`.
- Look up all six new Lambda ARNs + the four SFN ARNs.
- Add **two new sections** to the dashboard (after "Cross-Region Spoke
  Health", before "Supporting Services"):

  **Section: Batch Analysis (Phase 1-3)**
  - `monitor_lambda_function` for each of `PreparePhaseFn`,
    `CollectPhaseFn`, `CheckBatchStatusFn`, `DispatchBatchFn`:
    - `add_fault_count_alarm` (max 0) — alarm
    - `add_throttles_count_alarm` (max 0) — alarm
    - `add_latency_p99_alarm` dashboard-only for Prepare/Collect
      (10-min timeout budget), not for CheckBatchStatus (runs in
      seconds, noise).
  - `monitor_step_function` for each of `batch-analysis-{env}` and
    `batch-orchestrator-{env}`:
    - `add_failed_execution_count_alarm` (max 0)
    - Dashboard widgets for started / succeeded / running executions.
  - `monitor_custom` business-metrics group for any `SteamPulse`
    namespace counters emitted by the batch lambdas (check
    `prepare_phase.py` / `collect_phase.py` for
    `metrics.add_metric(...)` calls — dashboard-only, no alarms).

  **Section: Genre Synthesis (Phase 4)**
  - `monitor_lambda_function` for `GenreSynthesisPrepareFn`,
    `GenreSynthesisCollectFn`:
    - Fault + throttle alarms as above.
    - Latency p99 dashboard-only.
  - `monitor_step_function` for `batch-genre-synthesis-{env}` and
    `batch-genre-synthesis-orchestrator-{env}`:
    - `add_failed_execution_count_alarm` (max 0).
    - Started / succeeded / running dashboards.
  - `monitor_custom` group for `SteamPulse` business metrics
    (`GenreSynthesisRuns`, `GenreSynthesisCacheHit` — already
    emitted by `genre_synthesis_service.py`). Dashboard-only.

**Reuse as-is:**
- `AlarmTopic` (already created in MonitoringStack) — all new alarms
  subscribe to it via the existing `SnsAlarmActionStrategy` default.
- `dims = {"environment": env}` — reuse for all `SteamPulse` namespace
  custom metrics.
- `_lookup_fn` / `_lookup_queue` discovery pattern.

## Verification

1. `poetry run cdk synth SteamPulse-{env}/Monitoring --context
   environment=staging` — confirm the new CfnResources appear: alarms
   named `SteamPulse-Staging-{PreparePhase,CollectPhase,...}Errors`
   and state-machine `FailedExecution` alarms, dashboard widgets for
   the two new sections.
2. After deploy, open the `SteamPulse-Staging` dashboard and confirm
   both new sections render and populate data during a staging batch
   run (`poetry run python scripts/sp.py batch …` for Phase 1-3,
   `trigger_genre_synthesis.py` for Phase 4).
3. Force-fail a SFN execution on staging (e.g. invalid input) and
   verify `…-FailedExecution` alarm moves to ALARM and the SNS
   subscription receives a notification.
4. `poetry run pytest tests/` — unchanged count of passing tests; no
   regressions from the new SSM params or monitoring wiring.

## Ship order

Single PR — all additions are additive (new SSM params + new
monitoring-stack sections). Deploy order:
1. `BatchAnalysisStack` — publishes the new SSM Lambda ARN params.
2. `MonitoringStack` — reads the params and wires the new widgets /
   alarms.
3. Subscribe alarm topic to email if not already done:
   `aws sns subscribe --topic-arn <AlarmTopicArn output> --protocol
   email --notification-endpoint you@example.com`
