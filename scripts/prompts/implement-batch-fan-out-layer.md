# Implement Batch Analysis Fan-Out Layer

## Background

The batch analysis pipeline processes **one game per Step Functions
execution**. The state machine accepts `{"appid": 440}` and runs three
phases (chunk → merge → synthesis) against that single game. This works.

What's missing is the **fan-out layer** — the mechanism that takes a list
of appids, distributes them across per-game executions, and controls how
many run in parallel.

### Current trigger scripts are broken

Both `scripts/sp.py batch 440 730` and `scripts/trigger_batch_analysis.py`
pass `{"appids": [440, 730]}` (plural) to the state machine, but the
state machine reads `$.appid` (singular). This causes immediate failure.

### What exists today

- **Per-game state machine** (`batch_analysis_stack.py`): expects
  `{"appid": int}`, runs PrepareChunk → Wait/Check → CollectChunk →
  PrepareMerge (inline) → PrepareSynthesis → Wait/Check →
  CollectSynthesis → Done. Three Lambdas: `PreparePhase`,
  `CollectPhase`, `CheckBatchStatus`.

- **CLI** (`scripts/sp.py`): `batch` subcommand accepts specific appids
  or `--all-eligible`. Calls `sfn.start_execution()` with `{"appids":
  [...]|"ALL_ELIGIBLE"}`.

- **Trigger script** (`scripts/trigger_batch_analysis.py`): same idea,
  accepts `--appids 440 730`, calls `start_execution`.

- **SSM param** `/steampulse/{env}/batch/sfn-arn` publishes the per-game
  state machine ARN.

### Why a Map state (not a script loop)

A parent state machine with a Map state is better than a script that
loops `start_execution()` N times:

- **Concurrency control.** Map state's `MaxConcurrency` is enforced by
  Step Functions. A script loop has no built-in throttle.
- **Visibility.** One parent execution in the console shows all child
  executions, their status, and any failures. N independent executions
  are scattered.
- **Error aggregation.** Map state can tolerate N failures
  (`ToleratedFailurePercentage`) without aborting the whole batch.
- **Resumability.** If the parent fails, you can see exactly which
  children completed and which didn't.

---

## Goal

Add a parent "orchestrator" state machine that accepts a list of appids,
fans out over the per-game state machine using a Map state with
configurable concurrency.

The orchestrator accepts **only explicit appid lists** for now:
`{"appids": [440, 730, 570]}`. Smart game selection (eligible games,
priority ordering, staleness checks) will be handled by a separate
upstream component in a follow-up prompt — it feeds appid lists into
this orchestrator.

**No changes to the per-game state machine, PreparePhase, CollectPhase,
or CheckBatchStatus.** The fan-out layer wraps the existing pipeline.

---

## Architecture

```
CLI (sp.py / trigger script)
  │
  │  {"appids": [440, 730, 570, ...]}
  ▼
┌─────────────────────────────────────────────────────┐
│  Orchestrator State Machine (NEW)                   │
│                                                     │
│  1. Map state (Distributed mode)                    │
│     items_path: $.appids                            │
│     MaxConcurrency: 20 (configurable)               │
│     ToleratedFailurePercentage: 10                  │
│     Each item: appid integer                        │
│     ├── StartExecution: per-game state machine      │
│     │   input: {"appid": <item>}                    │
│     └── Wait for child completion (RUN_JOB)         │
│                                                     │
│  2. Done                                            │
└─────────────────────────────────────────────────────┘
         │  (one child per appid)
         ▼
┌─────────────────────────────────────────────────────┐
│  Per-Game State Machine (EXISTING, unchanged)       │
│  PrepareChunk → Wait/Check → CollectChunk           │
│  → PrepareMerge (inline)                            │
│  → PrepareSynthesis → Wait/Check → CollectSynthesis │
│  → Done                                             │
└─────────────────────────────────────────────────────┘
```

---

## Files to Create

None. This is purely CDK infrastructure + CLI script updates.

---

## Files to Modify

### `infra/stacks/batch_analysis_stack.py`

Add the orchestrator state machine alongside the existing per-game
machine. The per-game machine is unchanged.

**New resources:**

1. **Orchestrator state machine** — STANDARD type (required for Map).

   ```
   Map: "FanOut"
     items_path: $.appids
     max_concurrency: 20
     tolerated_failure_percentage: 10
     iterator:
       StepFunctionsStartExecution:
         state_machine_arn: <per-game machine>
         integration_pattern: RUN_JOB (sync — wait for child)
         input: {"appid.$": "$"}

   Succeed: "BatchComplete"
   ```

   **Map mode:** Use `DistributedMap` for large fan-outs (>40 items).
   `INLINE` mode caps at 40 concurrent iterations. Distributed mode
   supports up to 10,000 concurrent children.

   **Sync integration:** The Map iterator uses
   `StepFunctionsStartExecution` with `RUN_JOB` integration pattern —
   the orchestrator blocks until each child execution completes. This
   gives proper status rollup in the console.

2. **SSM param** for the orchestrator ARN:
   `/steampulse/{env}/batch/orchestrator-sfn-arn`.

3. **IAM grants** — the orchestrator's execution role needs:
   - `states:StartExecution` on the per-game machine
   - `states:DescribeExecution` on the per-game machine
   - `states:StopExecution` on the per-game machine

**CDK sketch:**

```python
# ── Orchestrator state machine ─────────────────────────────────────

fan_out = sfn.DistributedMap(
    self, "FanOut",
    items_path="$.appids",
    max_concurrency=20,
    tolerated_failure_percentage=10,
)
fan_out.item_processor(
    tasks.StepFunctionsStartExecution(
        self, "RunPerGame",
        state_machine=state_machine,  # the existing per-game machine
        integration_pattern=sfn.IntegrationPattern.RUN_JOB,
        input=sfn.TaskInput.from_object({
            "appid": sfn.JsonPath.number_at("$"),
        }),
    )
)

done = sfn.Succeed(self, "BatchOrchestrationComplete")
fan_out.next(done)

orchestrator = sfn.StateMachine(
    self, "BatchOrchestrator",
    state_machine_name=f"steampulse-batch-orchestrator-{env}",
    definition_body=sfn.DefinitionBody.from_chainable(fan_out),
    state_machine_type=sfn.StateMachineType.STANDARD,
    logs=sfn.LogOptions(
        destination=logs.LogGroup(
            self,
            "OrchestratorLogs",
            log_group_name=f"/steampulse/{env}/batch-orchestrator",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        ),
        level=sfn.LogLevel.ERROR,
    ),
)

# Grant orchestrator permission to drive the per-game machine
state_machine.grant_start_execution(orchestrator)
state_machine.grant(orchestrator, "states:DescribeExecution")
state_machine.grant(orchestrator, "states:StopExecution")

# Publish orchestrator ARN to SSM
ssm.StringParameter(
    self,
    "OrchestratorSfnArnParam",
    parameter_name=f"/steampulse/{env}/batch/orchestrator-sfn-arn",
    string_value=orchestrator.state_machine_arn,
)
```

### `scripts/sp.py`

Update `cmd_batch` to target the **orchestrator** state machine:

- Read orchestrator ARN from SSM:
  `/steampulse/{env}/batch/orchestrator-sfn-arn`
- Input is `{"appids": [int, int, ...]}` — the orchestrator's Map
  state iterates over this list.
- Remove `--all-eligible` for now (that's a follow-up). The CLI accepts
  only explicit appid lists.

### `scripts/trigger_batch_analysis.py`

Same change — point at the orchestrator ARN, pass `{"appids": [...]}`.

---

## Concurrency Knobs

| Knob | Where | Default | Effect |
|------|-------|---------|--------|
| `MaxConcurrency` on Map state | CDK (`DistributedMap`) | 20 | How many per-game SFN executions run simultaneously |
| `ToleratedFailurePercentage` | CDK (`DistributedMap`) | 10 | % of child failures before the orchestrator aborts |

`MaxConcurrency=20` means at most 20 games are going through their
chunk/synthesis Anthropic batches concurrently. Each game submits at most
2 Anthropic batches (chunk + synthesis). That's 40 concurrent batches
max — well within Anthropic's 4,000 batch-creation calls/min limit.

For initial runs with thousands of games, start with
`MaxConcurrency=20` and increase if Anthropic's throughput allows.
The value is hardcoded in CDK — to make it runtime-configurable, a
follow-up can read it from a config field and pass it as a CDK
context variable.

---

## Cost Awareness

Step Functions cost is per state transition:

- Orchestrator: ~3 transitions per child (Map entry + StartExecution +
  Map exit) = 3 × N transitions.
- Per-game: ~15-20 transitions per game (prepare/wait/check/collect ×
  2 phases + merge inline).
- Standard workflow pricing: $0.025 per 1,000 transitions.
- 500 games × 23 transitions = 11,500 transitions ≈ $0.29.

The real cost is LLM tokens, not Step Functions.

---

## What This Prompt Does NOT Cover

**Game selection / eligibility / priority ordering** is deliberately
out of scope. A follow-up prompt will design the "resolve eligible
games" component that feeds appid lists into this orchestrator. That
prompt will address:

- Which games need analysis (never analyzed, stale pipeline version,
  stale data from new reviews)
- Priority ordering (recent releases first? popular games first?
  revenue-weighted?)
- Cost budgeting (how many games per day/week given token costs)
- Incremental vs full re-analysis

The orchestrator is the dumb pipe — it takes whatever list it's given
and runs it with concurrency control.

---

## Acceptance Criteria

1. `poetry run python scripts/sp.py batch 440 730 --env staging`
   starts an orchestrator execution that fans out to two per-game
   child executions. Both complete successfully.

2. Child execution failures (e.g. a game has no reviews) do NOT abort
   the entire batch — the orchestrator tolerates up to 10% failures.

3. The orchestrator execution is visible in the Step Functions console
   as a single parent with N children — not N scattered executions.

4. `poetry run python scripts/sp.py batch 440 730 --dry-run` prints
   the orchestrator ARN and input payload without starting execution.

5. Per-game state machine, PreparePhase, CollectPhase, CheckBatchStatus
   — all unchanged.

6. All existing 485+ tests pass. Ruff clean.
