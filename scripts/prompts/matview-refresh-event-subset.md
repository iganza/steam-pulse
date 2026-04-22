# Narrow matview refresh to the views each trigger actually invalidates

## Context

The matview-refresh SFN (shipped in `feature/matview-refresh-sfn`, prompt
`scripts/prompts/matview-refresh-sfn.md`) today refreshes **all 18
matviews** on every trigger, regardless of what caused the trigger. Only
three matviews read from the `reports` table:

- `mv_catalog_reports` — `JOIN reports r ON r.appid = g.appid`
- `mv_analysis_candidates` — `LEFT JOIN reports r ON r.appid = g.appid`
- `mv_new_releases` — `EXISTS (SELECT 1 FROM reports r WHERE r.appid = ac.appid)`

A fourth, `mv_discovery_feeds`, surfaces `games.last_analyzed` (set when a
report is written) through its `just_analyzed` feed, so it also needs
refresh on a new report.

Every other view (genre / tag / price / release / platform / trend /
review / audience) does not depend on `reports`. Running a full refresh
on every `report-ready` is wasted DB load — each realtime analysis burns
the full refresh budget for a 3-to-4-view invalidation.

Triggers and what they actually invalidate:

| Trigger | Views that need refresh |
|---|---|
| SNS `report-ready` (realtime or batch collect) | `mv_catalog_reports`, `mv_analysis_candidates`, `mv_new_releases`, `mv_discovery_feeds` |
| SNS `batch-analysis-complete` | all 18 (batch landed many new reports + touched catalog state) |
| SNS `catalog-refresh-complete` | all 18 (catalog shape changed) |
| EventBridge 6h cron | all 18 (safety net) |
| `sp.py matview-refresh` | all 18 (operator knob) |

**Goal.** Narrow `report-ready` to the 4-view subset. Keep all other
triggers unchanged. Compute savings: ~14 fewer REFRESH calls per real-time
report, so DB IOPS drop proportionally on the realtime path.

**Explicitly out of scope.** No change to debounce, in-flight guard,
trigger Lambda idempotency, or the EventBridge schedule. No per-trigger
subset for anything other than `report-ready`.

## Approach

Thread the triggering event type from the SQS trigger Lambda through to
the Start step, and let Start return a filtered `views` list.

1. **Trigger** (`trigger.py`): already inspects SQS records to detect the
   force-refresh event type. Extend the output of that inspection to
   return a `trigger_event` string (`"report-ready"` /
   `"batch-analysis-complete"` / `"catalog-refresh-complete"` / `""`),
   and pass it in the SFN input:
   `{"force": bool, "trigger_event": str}`. The EventBridge rule input
   AND `sp.py matview-refresh` must also carry `trigger_event: ""` —
   `MatviewRefreshStart` reads `$.trigger_event` via `.$`, and SFN's
   ASL path evaluation fails before Lambda runs if the key is missing
   (the Pydantic default only fires after invocation). Empty string
   maps to the full-refresh path.

2. **Start** (`start.py`): after the existing debounce + in-flight guards
   run, compute the view list:
   - `trigger_event == "report-ready"` → the 4-view report subset
     (`REPORT_DEPENDENT_VIEWS`, a new constant in `matview_repo.py`
     exported alongside `MATVIEW_NAMES`).
   - Anything else (empty string, `batch-analysis-complete`,
     `catalog-refresh-complete`, operator CLI) → `list(MATVIEW_NAMES)`
     (full refresh).

3. **Debounce** stays global — a `report-ready` within 5 min of a
   `complete` cycle still debounces, because the last full refresh
   already covered those 4 views. Add a separate comment noting the
   debounce is view-list-agnostic on purpose.

4. **In-flight guard** stays global — don't start a subset cycle while a
   full cycle is running; the full one will cover the subset.

## Critical files

- `src/library-layer/library_layer/repositories/matview_repo.py`:
  - Add `REPORT_DEPENDENT_VIEWS: tuple[str, ...]` constant listing the 4
    views. Export from the module.
- `src/lambda-functions/lambda_functions/matview_refresh/trigger.py`:
  - Replace `_is_force_refresh(event) -> bool` with
    `_classify(event) -> tuple[bool, str]` returning `(force,
    trigger_event)`. Include `trigger_event` in the SFN input payload.
- `src/lambda-functions/lambda_functions/matview_refresh/start.py`:
  - Add `trigger_event: str = ""` to `StartEvent`.
  - Select view list based on `trigger_event`.
- `infra/stacks/compute_stack.py`:
  - `MatviewRefreshStart` payload gains `"trigger_event.$": "$.trigger_event"`.
  - `MatviewRefreshSchedule` EB rule input gains `"trigger_event": ""`.
  - Pass state `MatviewRecordStartTime` already just reshapes — no change
    needed if `views` is populated by Start.
- `scripts/sp.py`:
  - `cmd_matview_refresh` sends `{"force": force, "trigger_event": ""}`
    so operator-driven runs stay on the full-refresh branch.

## Verification

- `tests/repositories/test_matview_repo.py`: assert
  `REPORT_DEPENDENT_VIEWS` is a non-empty subset of `MATVIEW_NAMES`.
- `tests/handlers/test_matview_refresh_start.py`: add cases for
  `trigger_event="report-ready"` → returned `views` equals
  `list(REPORT_DEPENDENT_VIEWS)`; for `trigger_event=""` or
  `"batch-analysis-complete"` → returned `views` equals
  `list(MATVIEW_NAMES)`.
- `tests/handlers/test_matview_refresh_trigger.py`: parametrise over
  (body, expected_trigger_event). Confirm the SFN input carries the
  classified event.
- Staging: publish a synthetic `report-ready` SNS message; confirm the
  SFN execution's Map iterates 4 items (not 18) and Finalize persists
  `per_view_results` with those 4 keys.

## Future work (not this prompt)

If we ever narrow `catalog-refresh-complete` to just the catalog-shape
views (everything except `mv_audience_overlap` and the report-dependent
set), the same threading extends naturally — add a second named subset
constant and another classifier branch. Worth doing only if the catalog
refresh itself becomes a measurable source of DB load.
