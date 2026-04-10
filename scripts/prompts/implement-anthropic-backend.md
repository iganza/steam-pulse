# Implement Anthropic Direct API + Batches Backend

## Background

The LLM layer today is exclusively AWS Bedrock:

- **Realtime:** `ConverseBackend` in `llm/converse.py` — synchronous
  `instructor.from_anthropic(anthropic.AnthropicBedrock())` with thread-pool
  fan-out for chunks. Used by `analysis/handler.py` (Lambda) and
  `scripts/dev/run_phase.py` (local).
- **Batch:** `BatchBackend` in `llm/batch.py` — JSONL → S3 →
  `create_model_invocation_job` → poll → read output JSONL from S3. Driven
  by Step Functions via `prepare_phase.py` / `collect_phase.py`.

Both sit below a clean protocol seam in `llm/backend.py`:

- `LLMRequest` — transport-agnostic (system, user, max_tokens,
  response_model, record_id, task). No Bedrock fields.
- `LLMBackend` protocol — `run(requests, *, on_result)` for realtime.
- `BatchBackend` — `prepare/submit/status/collect` for async batch.

Everything above this seam — `analyzer.py` (prompts, phase helpers,
`analyze_game`), repositories, handlers, tests — is backend-agnostic.

### Why switch

1. **Bedrock throttling.** Low default rate limits on Bedrock Converse
   prevent local bulk runs (50 games × 40 chunks = 2000 concurrent-ish
   calls). Anthropic's direct API has higher default rate limits.
2. **Anthropic Message Batches API gives 50% off** input and output
   tokens (Sonnet: $1.50/M in, $7.50/M out vs $3/$15). Same models,
   same tool_use schemas, 24h SLA. Batch Inference on Bedrock has
   similar discounts but is harder to set up (IAM roles, S3 buckets,
   job management).
3. **Simpler batch infrastructure.** Anthropic batches are pure HTTP —
   no S3, no IAM role for the job, no output-JSONL parsing. Submit a
   JSON array, poll a status endpoint, fetch results from a single
   endpoint.

### Goal

Add two new backend classes alongside the existing Bedrock ones:

- `AnthropicConverseBackend` — realtime, direct Anthropic Messages API.
- `AnthropicBatchBackend` — Anthropic Message Batches API.

A config flag (`LLM_BACKEND=bedrock|anthropic`) selects which pair the
handlers instantiate. Both backends operate on the same `LLMRequest`
objects, return the same pydantic models, and satisfy the same
`LLMBackend` protocol / `prepare/submit/status/collect` lifecycle.

**No changes above the seam.** Analyzer, repositories, handlers, tests,
state machine shape — all unchanged. The switch is purely `llm/` layer
+ config + env vars.

---

## Existing Code Orientation

### `llm/backend.py` — the protocol

```python
LLMTask = Literal["chunking", "merging", "summarizer"]

class LLMUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int

LLMResultCallback = Callable[[int, BaseModel, LLMUsage], None]

class LLMRequest(BaseModel):
    record_id: str
    task: LLMTask
    system: str
    user: str
    max_tokens: int
    response_model: type[BaseModel]

class LLMBackend(Protocol):
    mode: Literal["realtime", "batch"]
    def run(self, requests: list[LLMRequest], *,
            on_result: LLMResultCallback | None = None) -> list[BaseModel]: ...
```

### `llm/converse.py` — realtime Bedrock (the thing to clone)

Key moving parts:
- `__init__`: `instructor.from_anthropic(anthropic.AnthropicBedrock())`
- `_execute_one(request) -> (BaseModel, LLMUsage)`:
  - `config.model_for(request.task)` → model ID
  - `self._client.messages.create_with_completion(model=..., max_tokens=...,
    response_model=..., max_retries=..., system=[{text, cache_control}],
    messages=[{role, content}])` → `(response, completion)`
  - `completion.usage` → `LLMUsage`
- `run(requests, *, on_result)`:
  - Single request → call `_execute_one` directly
  - Multiple → `ThreadPoolExecutor` + `as_completed`, calls `on_result(idx, result, usage)` as each future resolves
  - Streaming persistence via `on_result` callback (CLAUDE.md mandatory pattern)

### `llm/batch.py` — batch Bedrock (the lifecycle to mirror)

Four methods:
- `prepare(requests, *, phase) -> s3_uri` — serialize to Bedrock JSONL,
  upload to S3
- `submit(s3_uri, task, *, phase) -> job_id` — `create_model_invocation_job`
- `status(job_id) -> "running"|"completed"|"failed"` — poll Bedrock status
- `collect(job_id, ...) -> list[(record_id, BaseModel)]` — read output JSONL
  from S3, parse with pydantic, skip bad records

### `SteamPulseConfig` model routing

```python
# config.py
def model_for(self, task: LLMTask) -> str:
    """Return the Bedrock model ID for a given task."""
```

Model IDs differ between Bedrock and direct Anthropic:
- Bedrock: `us.anthropic.claude-sonnet-4-6`
- Anthropic direct: `claude-sonnet-4-6`

### Callers (what NOT to change)

- `analyzer.py` — `analyze_game()`, `run_chunk_phase()`, `run_merge_phase()`,
  `run_synthesis_phase()` — all call `backend.run(requests, on_result=...)`.
  Backend-agnostic.
- `analysis/handler.py` — instantiates `ConverseBackend`, calls `analyze_game`.
  Just swap which backend class.
- `batch_analysis/prepare_phase.py` — instantiates `BatchBackend` and
  `ConverseBackend` (for inline merge). Just swap classes.
- `batch_analysis/collect_phase.py` — instantiates `BatchBackend`. Swap.
- `scripts/dev/run_phase.py` — instantiates `ConverseBackend`. Swap.

---

## Files to Create

### `llm/anthropic_converse.py` — realtime direct API

Clone `converse.py` with these changes:

1. `__init__`:
   - `instructor.from_anthropic(anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY))`
     instead of `AnthropicBedrock()`.
   - Same `max_workers`, `max_retries` constructor params.
2. `_execute_one`:
   - Same `create_with_completion` call — instructor's interface is
     identical for `Anthropic` and `AnthropicBedrock`. The model ID
     is the only semantic difference and that comes from config.
   - `cache_control: {"type": "ephemeral"}` works the same way on the
     direct API (Anthropic prompt caching).
   - `completion.usage` fields are identical: `input_tokens`,
     `output_tokens`, `cache_read_input_tokens`,
     `cache_creation_input_tokens`.
3. `run()` — identical to `ConverseBackend.run()`. Consider extracting
   a shared `_ThreadPoolRunner` mixin or base class to avoid copying
   the ~50-line thread-pool + `on_result` + cancel-on-error body.
   Or just inherit from `ConverseBackend` and override `__init__` only.

**Simplest path:** subclass `ConverseBackend`, override `__init__` to
use `anthropic.Anthropic` instead of `AnthropicBedrock`. Everything
else — `run()`, `_execute_one`, thread pool, `on_result` streaming —
is inherited unchanged. ~15 lines.

```python
class AnthropicConverseBackend(ConverseBackend):
    def __init__(self, config: SteamPulseConfig, *, max_workers: int,
                 max_retries: int = 2) -> None:
        super().__init__(config, max_workers=max_workers, max_retries=max_retries)
        self._client = instructor.from_anthropic(
            anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        )
```

### `llm/anthropic_batch.py` — Anthropic Message Batches API

New class implementing the same `prepare/submit/status/collect` lifecycle
as `BatchBackend` but against Anthropic's HTTP API instead of
Bedrock + S3.

```python
class AnthropicBatchBackend:
    mode = "batch"

    def __init__(self, config: SteamPulseConfig, *,
                 api_key: str | None = None) -> None:
        self._config = config
        self._client = anthropic.Anthropic(api_key=api_key or config.ANTHROPIC_API_KEY)
```

**`prepare(requests, *, phase) -> list[dict]`**

No S3. Build the requests array in memory:

```python
def prepare(self, requests: list[LLMRequest], *, phase: str) -> list[dict]:
    return [
        {
            "custom_id": req.record_id,
            "params": {
                "model": self._config.model_for(req.task),
                "max_tokens": req.max_tokens,
                "system": [{"type": "text", "text": req.system}],
                "messages": [{"role": "user", "content": req.user}],
            },
        }
        for req in requests
    ]
```

**`submit(prepared_requests, task, *, phase) -> batch_id`**

```python
def submit(self, prepared: list[dict], task: LLMTask, *, phase: str) -> str:
    batch = self._client.messages.batches.create(requests=prepared)
    return batch.id
```

**`status(batch_id) -> BatchStatus`**

```python
def status(self, batch_id: str) -> BatchStatus:
    batch = self._client.messages.batches.retrieve(batch_id)
    match batch.processing_status:
        case "in_progress":
            return "running"
        case "ended":
            return "completed"
        case "canceling" | "canceled" | "expired":
            return "failed"
        case _:
            return "failed"
```

**`collect(batch_id, ...) -> list[(record_id, BaseModel)]`**

```python
def collect(self, batch_id: str, *,
            default_response_model: type[BaseModel] | None = None,
            response_models: dict[str, type[BaseModel]] | None = None,
            ) -> list[tuple[str, BaseModel]]:
    response_models = response_models or {}
    results = []
    for entry in self._client.messages.batches.results(batch_id):
        record_id = entry.custom_id
        if entry.result.type != "succeeded":
            logger.warning("batch_record_failed", extra={...})
            continue
        message = entry.result.message
        content = message.content
        # Extract tool_use text — same shape as Bedrock output
        text = content[0].input  # tool_use block
        response_cls = response_models.get(record_id) or default_response_model
        parsed = response_cls.model_validate(text)
        results.append((record_id, parsed))
    return results
```

Note: Anthropic batch results stream as an iterator — no S3 pagination
needed. Each entry has `custom_id`, `result.type` ("succeeded"|"errored"|
"expired"|"canceled"), and `result.message` (the full Message object).

The `tool_use` block in `result.message.content` carries the structured
output — same shape instructor would parse. Use
`response_cls.model_validate(content[0].input)` to get the pydantic
object (the `input` field on a `ToolUseBlock` is already a dict).

### `llm/__init__.py` — factory function

Add a factory that reads config and returns the right backend pair:

```python
def make_converse_backend(config: SteamPulseConfig, *,
                          max_workers: int, max_retries: int = 2) -> LLMBackend:
    if config.LLM_BACKEND == "anthropic":
        from llm.anthropic_converse import AnthropicConverseBackend
        return AnthropicConverseBackend(config, max_workers=..., max_retries=...)
    from llm.converse import ConverseBackend
    return ConverseBackend(config, max_workers=..., max_retries=...)

def make_batch_backend(config: SteamPulseConfig, **kwargs) -> BatchBackend | AnthropicBatchBackend:
    ...
```

Callers (`analysis/handler.py`, `prepare_phase.py`, `collect_phase.py`,
`run_phase.py`) replace direct `ConverseBackend(...)` / `BatchBackend(...)`
with `make_converse_backend(...)` / `make_batch_backend(...)`.

---

## Files to Modify

### `config.py`

Add:
```python
LLM_BACKEND: Literal["bedrock", "anthropic"] = "bedrock"
ANTHROPIC_API_KEY: str = ""  # required when LLM_BACKEND == "anthropic"
```

`ANTHROPIC_API_KEY` can be empty when `LLM_BACKEND == "bedrock"` (IAM
auth, no key needed). Fail loud at cold start if `LLM_BACKEND ==
"anthropic"` and the key is missing.

### `.env` / `.env.example`

Add:
```bash
# Backend selection: "bedrock" (default) or "anthropic" (direct API)
LLM_BACKEND=anthropic

# Required when LLM_BACKEND=anthropic. Get from https://console.anthropic.com/
ANTHROPIC_API_KEY=sk-ant-...

# Model IDs — drop the "us.anthropic." prefix for direct API
LLM_MODEL__CHUNKING=claude-sonnet-4-6
LLM_MODEL__MERGING=claude-sonnet-4-6
LLM_MODEL__SUMMARIZER=claude-sonnet-4-6
```

### `.env.staging` / `.env.production`

Keep as-is (Bedrock). The `LLM_BACKEND=bedrock` default means no
staging/prod env change is needed until we decide to switch.

### Callers — minimal changes

Replace direct class instantiation with factory calls:

- `analysis/handler.py`: `ConverseBackend(config, ...)` →
  `make_converse_backend(config, ...)`
- `prepare_phase.py`: `BatchBackend(config, ...)` →
  `make_batch_backend(config, ...)`, `ConverseBackend(config, ...)` →
  `make_converse_backend(config, ...)`
- `collect_phase.py`: `BatchBackend(config, ...)` →
  `make_batch_backend(config, ...)`
- `run_phase.py`: `ConverseBackend(config, ...)` →
  `make_converse_backend(config, ...)`

### `batch_analysis_stack.py` — CDK (no change needed yet)

The Step Functions state machine shape (Prepare → Wait → Check →
Collect) is the same for both batch backends. The Lambda handlers
decide which backend class to use at runtime based on `LLM_BACKEND`.
No CDK changes.

If we later want to remove the S3 bucket / Bedrock IAM role when
running pure Anthropic batch, that's an optional CDK cleanup — not
required for functionality.

---

## Signature Differences to Handle

### `prepare()` return type

- Bedrock: returns `str` (S3 URI)
- Anthropic: returns `list[dict]` (in-memory requests array)

The `prepare_phase.py` Lambda passes the result of `prepare()` into
`submit()`. Both backends accept their own prepare output — the Lambda
doesn't inspect it. But the type changes from `str` to `list[dict]`.

**Fix:** type the Lambda's local variable as `object` or use the
factory pattern where `make_batch_backend` returns a protocol that
types prepare/submit consistently. Or define a `BatchPrepareResult =
str | list[dict]` union.

### `submit()` first param

- Bedrock: `submit(s3_uri: str, task, *, phase) -> str` (ARN)
- Anthropic: `submit(prepared: list[dict], task, *, phase) -> str` (batch ID)

Same fix — the Lambda hands the output of prepare directly to submit
without inspecting it.

### `collect()` response parsing

- Bedrock: reads JSONL from S3, parses `content[0].text` as JSON string
  → `model_validate_json(text)`
- Anthropic: reads `entry.result.message.content[0].input` which is
  already a dict → `model_validate(input_dict)`

This difference is internal to each backend's `collect()`. Callers see
the same `list[(record_id, BaseModel)]` return.

---

## Tests

### `tests/llm/test_anthropic_converse.py`

- Verify `AnthropicConverseBackend` is a subclass of `ConverseBackend`
  (or implements the same protocol).
- Mock `anthropic.Anthropic` and verify `create_with_completion` is
  called with the right model ID (no `us.` prefix).
- Verify `on_result` callback is invoked with `LLMUsage` containing
  real token counts from the mocked completion.

### `tests/llm/test_anthropic_batch.py`

- Mock `anthropic.Anthropic().messages.batches.create/retrieve/results`.
- Test `prepare()` returns the expected request dicts.
- Test `submit()` passes the prepared list to `.batches.create`.
- Test `status()` maps `processing_status` values correctly.
- Test `collect()` parses `tool_use` blocks from result entries and
  returns `(custom_id, BaseModel)` tuples.
- Test `collect()` skips errored/expired entries without crashing.

### Existing test suite — no changes expected

All 485 existing tests use `_FakeBackend` (in-memory) or mock the
backend at the caller boundary. None instantiate a real
`ConverseBackend` or `BatchBackend`. The factory function is only
called in the handler/script entry points, not in test code.

---

## Migration Path

### Phase 1: local dev (this PR)

- Set `.env` to `LLM_BACKEND=anthropic` + `ANTHROPIC_API_KEY=sk-ant-...`
- Model IDs in `.env` drop the `us.anthropic.` prefix.
- `run_phase.py` and `run_test_games.py` use the Anthropic direct API.
- No Bedrock throttling. Same token costs.
- Staging/prod unchanged — still `LLM_BACKEND=bedrock` (the default).

### Phase 2: batch analysis (follow-up)

- `AnthropicBatchBackend` wired into the batch Lambdas.
- 50% cost reduction on bulk analysis runs.
- Step Functions shape unchanged.
- `ANTHROPIC_API_KEY` stored in Secrets Manager, read at Lambda cold
  start via `ANTHROPIC_API_KEY_SECRET_NAME`.

### Phase 3: production cutover (optional)

- Flip `.env.production` to `LLM_BACKEND=anthropic` once we're
  confident the direct API is stable under prod load.
- Remove Bedrock Batch IAM role + S3 bucket if no longer needed.
- Keep the Bedrock backend code — it's a fallback if Anthropic's API
  has availability issues.

---

## Acceptance Criteria

1. `LLM_BACKEND=anthropic` in `.env` → `run_phase.py --appid 2358720
   --phase chunk` successfully calls the Anthropic Messages API (not
   Bedrock), persists chunk_summaries with real token counts, and
   produces an identical org dump to the Bedrock path.
2. `LLM_BACKEND=bedrock` (default) → all existing behavior unchanged.
   485 tests pass. No Lambda handler or CDK change.
3. `AnthropicBatchBackend.prepare/submit/status/collect` pass unit
   tests against mocked `anthropic.Anthropic()`.
4. `cost_estimate.py` correctly prices both Bedrock and Anthropic
   model IDs (the `_PRICING` table keys on the normalized model name,
   which is the same after stripping the `us.` prefix).
5. `poetry run ruff check .` clean on all new/modified files.
