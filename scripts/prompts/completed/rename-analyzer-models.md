# Refactor LLM Model Config to Task-Based Map

## Goal

Replace the two flat model env vars (`HAIKU_MODEL` / `SONNET_MODEL`) with a
single task-keyed dict (`LLM_MODEL`) populated via pydantic-settings' `__`
nested delimiter. This makes the config extensible — adding a new LLM task
requires only a new line in the env files, with zero changes to `config.py`.

**Pattern used:** pydantic-settings `env_nested_delimiter="__"` — the
idiomatic way to build nested/dict config from flat env vars without JSON
quoting fragility.

### Current → Target

```bash
# Current (flat, model-family-named)
HAIKU_MODEL=us.anthropic.claude-haiku-4-5-20250514-v1:0
SONNET_MODEL=us.anthropic.claude-sonnet-4-6-20250514-v1:0

# Target (task-keyed, nested delimiter)
LLM_MODEL__CHUNKING=us.anthropic.claude-haiku-4-5-20250514-v1:0
LLM_MODEL__SUMMARIZER=us.anthropic.claude-sonnet-4-6-20250514-v1:0
```

Access anywhere in code: `config.model_for("chunking")` — raises a clear
`ValueError` if the task key is missing (no silent fallback).

---

## Files to Change

### 1. `src/library-layer/library_layer/config.py`

#### a. Enable nested delimiter in `SettingsConfigDict`

```python
# Before
model_config = SettingsConfigDict(
    extra="ignore",
    env_file_encoding="utf-8",
)

# After
model_config = SettingsConfigDict(
    extra="ignore",
    env_file_encoding="utf-8",
    env_nested_delimiter="__",
)
```

#### b. Remove the two module-level default constants and replace the two flat
fields with a single `LLM_MODEL` dict field plus a `model_for()` helper:

```python
# Remove these two module-level lines entirely:
_HAIKU_DEFAULT = "us.anthropic.claude-haiku-4-5-20250514-v1:0"
_SONNET_DEFAULT = "us.anthropic.claude-sonnet-4-6-20250514-v1:0"

# Remove these two fields:
HAIKU_MODEL: str = _HAIKU_DEFAULT
SONNET_MODEL: str = _SONNET_DEFAULT

# Add in their place:
# ── LLM model routing (required — set LLM_MODEL__<task> in .env files) ────
# Known tasks: chunking, summarizer
# Add new tasks by adding LLM_MODEL__<newtask>=<model_id> to env files.
LLM_MODEL: dict[str, str]

def model_for(self, task: str) -> str:
    """Return the configured model ID for a named LLM task.

    Raises ValueError with a clear message if the task is not configured,
    so misconfiguration fails loudly rather than silently using a wrong model.

    Usage:
        config.model_for("chunking")    # Pass 1 — review chunk extraction
        config.model_for("summarizer")  # Pass 2 — final report synthesis
    """
    if task not in self.LLM_MODEL:
        configured = list(self.LLM_MODEL.keys())
        raise ValueError(
            f"No model configured for task '{task}'. "
            f"Add LLM_MODEL__{task.upper()}=<model_id> to your .env file. "
            f"Currently configured tasks: {configured}"
        )
    return self.LLM_MODEL[task]
```

---

### 2. `src/library-layer/library_layer/analyzer.py`

Remove the duplicate module-level constants and private helper functions entirely.
Replace with config import and `model_for()` calls.

```python
# Remove these entirely:
HAIKU_MODEL_DEFAULT = "anthropic.claude-3-5-haiku-20241022-v1:0"
SONNET_MODEL_DEFAULT = "anthropic.claude-3-5-sonnet-20241022-v2:0"

def _haiku_model() -> str:
    return os.getenv("HAIKU_MODEL", HAIKU_MODEL_DEFAULT)

def _sonnet_model() -> str:
    return os.getenv("SONNET_MODEL", SONNET_MODEL_DEFAULT)
```

Add config import after existing imports:

```python
from library_layer.config import SteamPulseConfig

_config = SteamPulseConfig()
```

Update the two call sites:

```python
# summarize_chunk() — Pass 1
# Before:  model=_haiku_model(),
# After:
model=_config.model_for("chunking"),

# synthesize_report() — Pass 2
# Before:  model=_sonnet_model(),
# After:
model=_config.model_for("summarizer"),
```

Update docstrings:

```python
# Module docstring
# Before: """Two-pass LLM analysis: Haiku for chunk summarization, Sonnet for synthesis."""
# After:
"""Two-pass LLM analysis pipeline.

Pass 1 (LLM_MODEL__CHUNKING):   process 50-review chunks → extract themes and signals.
Pass 2 (LLM_MODEL__SUMMARIZER): synthesize all chunk summaries → structured GameReport.

Models are configured via the LLM_MODEL task map in .env.staging / .env.production.
"""

# summarize_chunk docstring
# Before: """Pass 1: extract raw signals from a batch of reviews using Haiku with prompt caching."""
# After:  """Pass 1: extract raw signals from a batch of reviews (LLM_MODEL__CHUNKING, prompt caching enabled)."""

# synthesize_report docstring
# Before: """Pass 2: synthesize all chunk signals into a final structured report using Sonnet."""
# After:  """Pass 2: synthesize all chunk signals into a final structured report (LLM_MODEL__SUMMARIZER)."""
```

Remove `import os` if it is no longer used elsewhere in the file.

---

### 3. `src/lambda-functions/lambda_functions/api/chat.py`

Remove the duplicate constant and helper:

```python
# Remove:
SONNET_MODEL_DEFAULT = "claude-3-5-sonnet-20241022"

def _sonnet_model() -> str:
    return os.getenv("SONNET_MODEL", SONNET_MODEL_DEFAULT)
```

Add config import and replace all `_sonnet_model()` calls:

```python
from library_layer.config import SteamPulseConfig

_config = SteamPulseConfig()

# Replace _sonnet_model() with:
_config.model_for("summarizer")
```

Note: chat.py uses the summarizer model today. If/when V2 chat gets its own
dedicated model, add `LLM_MODEL__CHAT=<model_id>` to env files and update
this call to `_config.model_for("chat")` — no config.py changes needed.

---

### 4. `infra/stacks/compute_stack.py`

The CDK stacks pass model IDs as Lambda environment variables. Update both
locations (search for `HAIKU_MODEL`):

```python
# Before
"HAIKU_MODEL": config.HAIKU_MODEL,
"SONNET_MODEL": config.SONNET_MODEL,

# After — pass each task key as its own env var using the __ convention
"LLM_MODEL__CHUNKING": config.model_for("chunking"),
"LLM_MODEL__SUMMARIZER": config.model_for("summarizer"),
```

---

### 5. `infra/stacks/analysis_stack.py`

Same pattern:

```python
# Before
"HAIKU_MODEL": haiku_model,
"SONNET_MODEL": sonnet_model,

# After
"LLM_MODEL__CHUNKING": config.model_for("chunking"),
"LLM_MODEL__SUMMARIZER": config.model_for("summarizer"),
```

Also remove any local variables named `haiku_model` / `sonnet_model` and
replace with direct `config.model_for()` calls.

---

### 6. `.env.staging` and `.env.production`

```bash
# Remove:
HAIKU_MODEL=us.anthropic.claude-haiku-4-5-20250514-v1:0
SONNET_MODEL=us.anthropic.claude-sonnet-4-6-20250514-v1:0

# Add:
LLM_MODEL__CHUNKING=us.anthropic.claude-haiku-4-5-20250514-v1:0
LLM_MODEL__SUMMARIZER=us.anthropic.claude-sonnet-4-6-20250514-v1:0
```

---

### 7. `.env.example`

```bash
# Remove:
HAIKU_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
SONNET_MODEL=us.anthropic.claude-sonnet-4-6

# Add (with comment explaining the pattern):
# LLM model routing — one line per task. Add LLM_MODEL__<TASK>=<model_id> for new tasks.
LLM_MODEL__CHUNKING=us.anthropic.claude-haiku-4-5-20251001-v1:0
LLM_MODEL__SUMMARIZER=us.anthropic.claude-sonnet-4-6
```

---

## Extending Later (zero config.py changes needed)

To add a new LLM task in the future, just add a line to the env files:

```bash
LLM_MODEL__CHAT=us.anthropic.claude-sonnet-4-6-20250514-v1:0
LLM_MODEL__DESCRIPTION=us.anthropic.claude-haiku-4-5-20250514-v1:0
```

Then call `config.model_for("chat")` or `config.model_for("description")` anywhere.

---

## Tests

Add the following tests to `tests/test_config.py`. They follow the existing
pattern in that file — construct `SteamPulseConfig(**kwargs)` directly, no
mocking or patching required.

Also update `_ALL_REQUIRED` at the top of `tests/test_config.py` and
`conftest.py`'s `_TEST_ENV_DEFAULTS` dict: remove `HAIKU_MODEL` /
`SONNET_MODEL` keys (if present) and add the two new nested keys:

```python
# In _ALL_REQUIRED and _TEST_ENV_DEFAULTS:
"LLM_MODEL__CHUNKING": "us.anthropic.claude-haiku-test-v1:0",
"LLM_MODEL__SUMMARIZER": "us.anthropic.claude-sonnet-test-v1:0",
```

### New test cases

```python
def test_model_for_returns_configured_model() -> None:
    """model_for() returns the correct model ID for a known task."""
    config = SteamPulseConfig(
        **_ALL_REQUIRED,
        LLM_MODEL__CHUNKING="haiku-model-id",
        LLM_MODEL__SUMMARIZER="sonnet-model-id",
    )
    assert config.model_for("chunking") == "haiku-model-id"
    assert config.model_for("summarizer") == "sonnet-model-id"


def test_model_for_raises_on_unknown_task() -> None:
    """model_for() raises ValueError with a helpful message for unknown tasks."""
    config = SteamPulseConfig(
        **_ALL_REQUIRED,
        LLM_MODEL__CHUNKING="haiku-model-id",
        LLM_MODEL__SUMMARIZER="sonnet-model-id",
    )
    with pytest.raises(ValueError, match="No model configured for task 'chat'"):
        config.model_for("chat")


def test_model_for_same_model_both_tasks() -> None:
    """Both tasks can be set to the same model ID (e.g. for quality testing)."""
    config = SteamPulseConfig(
        **_ALL_REQUIRED,
        LLM_MODEL__CHUNKING="sonnet-model-id",
        LLM_MODEL__SUMMARIZER="sonnet-model-id",
    )
    assert config.model_for("chunking") == config.model_for("summarizer")


def test_config_raises_when_llm_model_missing() -> None:
    """SteamPulseConfig raises ValidationError if LLM_MODEL map is absent entirely."""
    with pytest.raises(ValidationError):
        SteamPulseConfig(**{k: v for k, v in _ALL_REQUIRED.items()
                            if not k.startswith("LLM_MODEL")})
```

---

## Verification

```bash
# Must return zero results
grep -r "HAIKU_MODEL\|SONNET_MODEL\|_haiku_model\|_sonnet_model\|_HAIKU_DEFAULT\|_SONNET_DEFAULT" \
  src/ tests/ infra/ .env.staging .env.production .env.example

# Tests must pass
poetry run pytest tests/ -x -q
```
