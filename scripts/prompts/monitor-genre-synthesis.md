# Monitor the Phase-4 genre synthesizer

## Context

The `feature/cross-genre-synthesizer-matview` PR shipped a new Lambda
(`lambda_functions/genre_synthesis/handler.py`), a new SQS queue
(`genre-synthesis-queue`) with DLQ, and a weekly EventBridge rule. The
monitoring stack (`infra/stacks/monitoring_stack.py`) was deliberately
left out of that PR to keep scope manageable — this follow-up closes
the gap.

Without these alarms, a persistently failing slug sits in the DLQ
silently, and a failed weekly scan means the 141-RDB synthesis never
refreshes until someone notices stale data on the web page.

## What to do

### 1. Emit the missing SSM param in `ComputeStack`

`monitoring_stack.py` discovers Lambdas by looking up
`/steampulse/{env}/compute/<name>-fn-arn`. Every other Lambda has that
param; `GenreSynthesisFn` does not. Add alongside the existing block
at the end of `compute_stack.py`:

```python
ssm.StringParameter(
    self,
    "GenreSynthesisFnArnParam",
    parameter_name=f"/steampulse/{env}/compute/genre-synthesis-fn-arn",
    string_value=genre_synthesis_fn.function_arn,
)
```

Queue + DLQ ARN SSM params already exist in `messaging_stack.py`
(`GenreSynthesisQueueArnParam`, `GenreSynthesisDlqArnParam`) — nothing
to do there.

### 2. Add a new dashboard section in `monitoring_stack.py`

After the "Supporting Services" section, add:

```python
# ══════════════════════════════════════════════════════════════════════
# Section 5: Phase-4 Genre Synthesis
# ══════════════════════════════════════════════════════════════════════
monitoring.add_large_header("Phase-4 Genre Synthesis")

genre_synthesis_fn = _lookup_fn(
    "genre-synthesis-fn-arn", "GenreSynthesisFnRef"
)
genre_synthesis_queue = _lookup_queue(
    "genre-synthesis-queue-arn", "GenreSynthesisQueueRef"
)
genre_synthesis_dlq = _lookup_queue(
    "genre-synthesis-dlq-arn", "GenreSynthesisDlqRef"
)

monitoring.monitor_lambda_function(
    lambda_function=genre_synthesis_fn,
    human_readable_name="Genre Synthesis",
    alarm_friendly_name="GenreSynthesis",
    add_fault_count_alarm={
        "GenreSynthesisErrors": ErrorCountThreshold(max_error_count=0),
    },
    add_throttles_count_alarm={
        "GenreSynthesisThrottles": ErrorCountThreshold(max_error_count=0),
    },
    # One synthesis = one Bedrock Sonnet call over ~140 reports. Expect
    # 60–180s on the p99. Alarm at 4 min so a runaway call pages before
    # the 5-min Lambda timeout kills it silently.
    add_latency_p99_alarm={
        "GenreSynthesisP99": LatencyThreshold(
            max_latency=cdk.Duration.seconds(240),
        ),
    },
)

monitoring.monitor_sqs_queue_with_dlq(
    queue=genre_synthesis_queue,
    dead_letter_queue=genre_synthesis_dlq,
    human_readable_name="Genre Synthesis Queue",
    alarm_friendly_name="GenreSynthesisQueue",
    # Weekly cadence, not hourly — a message older than 24h means the
    # Lambda stopped draining mid-batch. Looser than the crawl queues
    # (3600s) because the scan fires once a week.
    add_queue_max_message_age_alarm={
        "GenreSynthesisAge": MaxMessageAgeThreshold(
            max_age_in_seconds=86400,
        ),
    },
    # Any DLQ entry means a slug failed SQS's 3 redrives. Transient
    # Bedrock throttles shouldn't reach here (SQS handles those); a
    # landed DLQ message is a real failure — page.
    add_dead_letter_queue_max_size_alarm={
        "GenreSynthesisDlq": MaxMessageCountThreshold(max_message_count=0),
    },
)
```

### 3. Custom business-metrics panel (optional, low priority)

The handler already emits `GenreSynthesisRuns`,
`GenreSynthesisCacheHit`, `GenreSynthesisSkipped`, and
`GenreSynthesisStaleEnqueued`. A `CustomMetricGroup` panel surfacing
these on the dashboard gives a one-glance view of the weekly run
(how many slugs enqueued, how many cache-hit, how many actually
called Bedrock, how many skipped for insufficient reports).

Skip this until after the first 2–3 weekly runs so thresholds can
be set against real data, not guesses. Follow the same pattern as
"Crawler Business Metrics" in the existing stack.

### 4. Weekly scan heartbeat (optional, defer)

Analogous to `CatalogRefreshHeartbeat`: if `GenreSynthesisStaleEnqueued`
is missing for 2 consecutive weekly windows, the weekly rule is broken.
Only meaningful AFTER the `enabled=False` flag is flipped on the
EventBridge rule (see ARCHITECTURE.org) — until then, the metric will
never fire and the alarm would be permanently breaching. Revisit once
the weekly rule is enabled.

## Verification

1. **Synth clean**: `poetry run python -c "..."` on both staging and
   production env loads — no missing SSM param errors, no CDK
   validation failures.
2. **Alarms present**: `poetry run pytest tests/infra/test_monitoring_stack.py`
   still passes; add a test asserting the
   `SteamPulse-{Env}-GenreSynthesisDlq` alarm exists.
3. **SSM param created**: `aws ssm get-parameter --name
   /steampulse/staging/compute/genre-synthesis-fn-arn` returns the
   Lambda ARN after deploy.
4. **End-to-end**: force a failure (e.g. publish a malformed SQS
   message) 3× to push a message to the DLQ, observe the alarm
   fires within 1 evaluation period.

## Out of scope

- Bedrock cost/token alarms — covered separately once cost tracking
  lands for all Phase 1-4 LLM calls.
- Slack routing from the alarm topic — the stack already emits to
  `self.alarm_topic`; how that topic fans out to humans is the
  `AlarmTopicArn` output's consumer problem.
- Per-slug failure metrics (dimensioned by slug) — low ROI given the
  DLQ alarm already catches repeated failures and the logs carry the
  slug via `logger.append_keys`.
