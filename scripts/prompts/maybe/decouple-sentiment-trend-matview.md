# Decouple sentiment_trend into a matview

## Context

`sentiment_trend`, `sentiment_trend_note`, `sentiment_trend_sample_size`,
and `sentiment_trend_reliable` are computed in Python during synthesis
and frozen into `reports.report_json`. Once a report is written, the
label never updates — even though the underlying review data continues
to roll forward in the `reviews` table.

Trend is the *single most* freshness-sensitive field in the report
(it's literally about change). Freezing it into JSON is the worst
place for it to live. Move it into a matview that refreshes on the
existing schedule.

For background on why the corpus shape makes this the right priority,
see `ARCHITECTURE.org` → "Review corpus shape: rolling-recent window."

## What to do

### 1. New matview: `mv_sentiment_trend`

One row per appid, built from the `reviews` table directly. Columns:

- `appid`
- `recent_window_start`, `recent_window_end`, `recent_count`,
  `recent_positive_pct`
- `prior_window_start`, `prior_window_end`, `prior_count`,
  `prior_positive_pct`
- `trend` — `improving | stable | declining`, computed from the delta
  between the two windows using the same thresholds the Python code
  uses today (lift the rule verbatim into the matview DDL or a SQL
  helper — do not duplicate the rule in two places).
- `reliable` — boolean, true when both windows have ≥ 50 reviews.
- `computed_at` — `now()` at refresh.

Window sizes are config knobs, not hardcoded:
- `SENTIMENT_TREND_RECENT_DAYS` (default 30)
- `SENTIMENT_TREND_PRIOR_DAYS` (default 180)

The matview DDL reads them from a single SQL function (e.g.
`sentiment_trend_windows()`) so the values aren't sprinkled through
DDL. If config changes the windows, the migration that changes the
function also drops + recreates the matview (standard
`MATERIALIZED_VIEWS` / `MATVIEW_NAMES` flow).

`UNIQUE INDEX ON (appid)` is mandatory (`REFRESH CONCURRENTLY`).

### 2. Mirror in `schema.py`

Append the DDL to `MATERIALIZED_VIEWS` and add the matview name to the
drop-before-rebuild list in `create_matviews()` so test DBs pick up
future shape changes automatically.

### 3. Repository

`SentimentTrendRepository` extending `BaseRepository`, with a single
method `get_for_appid(appid: int) -> SentimentTrendRow | None`,
returning a pydantic model. Pure
`SELECT FROM mv_sentiment_trend WHERE appid = $1`. No business logic.

### 4. Refresh wire-up

Add the matview name to `MATVIEW_NAMES` in
`library_layer/repositories/matview_repo.py`. The existing
`matview_refresh_handler.py` Lambda picks it up automatically. **Do
not** write a new refresh path.

### 5. API wire-up (deploy A)

Endpoints currently returning `sentiment_trend` from the report —
`/api/games/{appid}/report` and `/api/games/{appid}/review-stats` —
join the matview row at the API/service layer and serve *those*
fields, not the frozen ones in `report_json`.

Frontend: no schema change. Same field names returned; values are
now live.

### 6. Remove from synthesis (deploy B, follow-up)

Per CLAUDE.md's two-phase rule: only after deploy A is live and the
endpoints are reading from the matview, do a second deploy that:

- Stops computing the four `sentiment_trend_*` fields in
  `analyzer.py` (synthesis Phase 3).
- Removes them from `GameReport`.
- Removes the trend label from the synthesis prompt context — the
  synthesizer should not narrate the trend at all (it doesn't have
  fresh data for it).
- Deletes the now-unused trend computation helpers and their tests.
  Do not leave dead code.

## Verification

1. **Matview correctness.** Apply migration locally, refresh the
   matview, spot-check 5 appids: matview values should agree with
   what a hand-written window query returns. `EXPLAIN ANALYZE` the
   refresh — it should be index-supported, not a full reviews scan.
2. **Live update.** Re-run a refresh after inserting a synthetic
   recent review with negative sentiment for an "improving" game.
   Trend label should flip without touching `report_json`.
3. **API contract preserved.** Smoke-test `/api/games/440/report` —
   the response shape must still include the four `sentiment_trend_*`
   fields with sensible values, now sourced from the matview.
4. **Smoke tests updated.** Per CLAUDE.md, any API change updates
   `tests/smoke/`. Update assertions to expect values matching the
   matview rather than `report_json`.
5. `poetry run pytest -v && poetry run ruff check .`

## Rollout

- Two deploys (CLAUDE.md two-phase rename rule):
  - **Deploy A**: migration + matview + repo + API switch.
  - **Deploy B** (follow-up): remove the dead fields from `GameReport`
    and the synthesis pipeline.
- Existing `reports` are not invalidated by deploy A — the trend
  fields in `report_json` simply stop being read. They get cleaned
  up in deploy B.
- No deploy from Claude — user runs `bash scripts/deploy.sh`
  themselves.
