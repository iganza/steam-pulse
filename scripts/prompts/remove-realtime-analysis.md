# Remove Real-Time Analysis Flow

## Context

The project currently has two analysis paths: a real-time path (Express SFN → AnalysisFn → Bedrock
Converse API) and a batch path (STANDARD SFN → 5 batch Lambdas → Bedrock Batch Inference). The
real-time path is unused in favour of the batch path, and the user wants it removed to keep the
codebase trim. The `/api/preview` and `/api/status/{job_id}` endpoints that depended on it are also
removed. What stays: all batch utilities in `analyzer.py`, the batch Lambda functions, and the
`BatchAnalysisStack`.

---

## Files to DELETE entirely

| Path | Reason |
|---|---|
| `src/lambda-functions/lambda_functions/analysis/` (handler.py, events.py) | Real-time analysis handler |
| `src/library-layer/library_layer/services/analysis_service.py` | Orphaned service — never imported anywhere |

---

## Files to MODIFY

### `infra/stacks/compute_stack.py`
- Remove `AnalysisFn` `PythonFunction` construct
- Remove Express `StateMachine` and its definition chain (PrepareReviews → InvokeAnalysis)
- Remove both SSM `StringParameter` publishes: `/steampulse/{env}/compute/sfn-arn`
- Keep all batch-related constructs (BatchAnalysisStack is a separate stack — no change needed)

### `src/lambda-functions/lambda_functions/api/handler.py`
- Remove `_trigger_analysis()` helper
- Remove `POST /api/preview` route
- Remove `GET /api/status/{job_id}` route
- Remove `_sfn_arn` module-level SSM resolution (`get_parameter(config.SFN_PARAM_NAME)`)
- Remove `_sfn` boto3 client (`boto3.client("stepfunctions", ...)`)

### `src/library-layer/library_layer/config.py`
- Remove `SFN_PARAM_NAME: str` field
- Remove `STEP_FUNCTIONS_PARAM_NAME: str` field (alias)

### `src/lambda-functions/lambda_functions/crawler/handler.py`
- Remove `_sfn` boto3 client and `_sfn_arn` SSM resolution
- Remove call to `crawl_service.trigger_analysis(sfn_arn=_sfn_arn, sfn_client=_sfn)` (or equivalent)

### `src/library-layer/library_layer/services/crawl_service.py`
- Remove `sfn_arn` and `sfn_client` parameters from `trigger_analysis()` or whichever method uses them
- Remove any Step Functions invocation logic from this service

### `src/library-layer/library_layer/analyzer.py`
Remove ONLY the real-time functions:
- `_get_instructor_client()`
- `_summarize_chunk()` (uses instructor + Converse API)
- `_synthesize()` (uses instructor + Converse API)
- `analyze_reviews()` (the top-level async orchestrator)
- Any `import instructor` / `import anthropic` lines that are no longer needed

**Keep everything used by batch path:**
- `CHUNK_SYSTEM_PROMPT`, `SYNTHESIS_SYSTEM_PROMPT`, `CHUNK_SIZE`
- `_chunk_reviews()`
- `_aggregate_chunk_summaries()`
- `_build_chunk_user_message()`
- `_build_synthesis_user_message()`

### `tests/services/test_analyzer.py`
- Remove 3 tests that call `analyze_reviews()` (the async real-time entry point)
- Keep all tests for batch utilities (`_build_chunk_user_message`, `_build_synthesis_user_message`, score helpers)

### `tests/infra/test_compute_stack.py`
- Remove `SFN_PARAM_NAME` and `STEP_FUNCTIONS_PARAM_NAME` from test config dict

### `tests/conftest.py`
- Remove `SFN_PARAM_NAME` and `STEP_FUNCTIONS_PARAM_NAME` from `_TEST_ENV_DEFAULTS`

### `.env.staging` / `.env.production`
- Remove `SFN_PARAM_NAME` and `STEP_FUNCTIONS_PARAM_NAME` lines

### `main.py` (CLI local testing tool)
- Remove or stub the `analyze_reviews()` call if it references the deleted function (may already be removed — verify)

---

## What NOT to touch

- `infra/stacks/batch_analysis_stack.py` — stays as-is
- `src/lambda-functions/lambda_functions/batch_analysis/` — stays as-is
- `src/library-layer/library_layer/analyzer.py` batch utilities — stays
- `tests/handlers/test_batch_analysis.py` — stays
- `ARCHITECTURE.org` — update to remove the real-time analysis flow diagram/section

---

## Verification

```bash
poetry run cdk synth          # must pass — no AnalysisFn or Express SFN
poetry run pytest -v          # all tests pass
poetry run ruff check .       # no lint errors
```
