# Post-Batch Matview Refresh

## Context

When a batch of N games completes analysis, each game's `_collect_synthesis` publishes a
`ReportReadyEvent` to the content-events SNS topic. The matview refresh handler has a
5-minute debounce — so the first game triggers a refresh, and the remaining N-1 events
are skipped. This means matviews reflect a partial batch until the debounce expires and
another event arrives (or the 6h EventBridge fallback fires).

We want one final refresh after ALL games in the batch complete, so matviews reflect the
complete batch immediately.

## Approach

The batch orchestrator state machine (`steampulse-batch-orchestrator-{env}`) uses a
DistributedMap to fan out per-game executions. After the Map state succeeds (all games
done), add a final Lambda task that publishes a `BatchAnalysisCompleteEvent` to the system-events
topic. The matview refresh handler already subscribes to system-events (via the
`catalog-refresh-complete` filter on `cache-invalidation-queue`). Add a new filter for
`batch-analysis-complete`.

The refresh handler's debounce must be **bypassed** for this event — the whole point is
to force a refresh after the batch, even if one happened < 5 minutes ago during the batch
run.

## Changes

### 1. Rename + fix event: `BatchAnalysisCompleteEvent`

File: `src/library-layer/library_layer/events.py`

Rename `"batch-complete"` → `"batch-analysis-complete"` in the `EventType` literal, then rename the class and align fields:

```python
class BatchAnalysisCompleteEvent(BaseEvent):
    event_type: EventType = "batch-analysis-complete"
    execution_id: str
    appids_completed: int = 0
    appids_failed: int = 0
```

### 2. Publish from orchestrator completion

Reuse `dispatch_batch.py` with a `"action": "post_batch"` branch that reads the Map
output (succeeded/failed counts) and publishes `BatchAnalysisCompleteEvent` to system-events-topic.

Add a Task state after the DistributedMap in the orchestrator state machine
(`infra/stacks/batch_analysis_stack.py`) that invokes dispatch with `{"action": "post_batch"}`.

### 3. Subscribe matview refresh to `batch-analysis-complete`

File: `infra/stacks/messaging_stack.py`

Add SNS subscription filter on `cache-invalidation-queue` for
`event_type = "batch-analysis-complete"` from `system-events-topic`.

### 4. Bypass debounce for `batch-analysis-complete`

File: `src/lambda-functions/lambda_functions/admin/matview_refresh_handler.py`

When the SQS message body contains `"event_type": "batch-analysis-complete"`, skip the debounce
check and always proceed with refresh. Other event types keep the existing 5-minute debounce.

## Files Touched

| File | Change |
|------|--------|
| `events.py` | Rename `BatchCompleteEvent` → `BatchAnalysisCompleteEvent`, update fields + `EventType` |
| `dispatch_batch.py` | Add `post_batch` action: publish `BatchAnalysisCompleteEvent` |
| `matview_refresh_handler.py` | Bypass debounce for `batch-analysis-complete` events |
| `batch_analysis_stack.py` | Add post-Map Task state invoking dispatch with `post_batch` |
| `messaging_stack.py` | Add `batch-analysis-complete` filter to `cache-invalidation-queue` subscription |
