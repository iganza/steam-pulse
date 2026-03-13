# Task: Refactor `steampulse/` into `src/` layout

Read `CLAUDE.md` before starting.

## Goal

Eliminate the root `steampulse/` package. All code moves into `src/` following the rule:
- **Shared code** (used by multiple Lambdas or layers) → `src/library-layer/library_layer/`
- **Lambda-specific code** → `src/lambda-functions/lambda_functions/<lambda_name>/`
- **CLI tool** (`main.py`) → stays at project root

## Current State

```
steampulse/
  __init__.py
  analyzer.py       # shared — used by analysis Lambdas
  api.py            # API Lambda specific
  chat.py           # API Lambda specific (V2)
  fetcher.py        # shared — HTTP utilities
  rate_limiter.py   # API Lambda specific
  reporter.py       # shared — report formatting
  steam_source.py   # shared — used by crawlers + API
  storage.py        # shared — DB/memory abstraction
  main.py           # CLI tool — NOT a Lambda
  templates/
    index.html      # API Lambda specific
    report.html.j2  # API Lambda specific
```

## Target State

```
src/
  library-layer/
    library_layer/
      __init__.py (empty, needed for PythonLayerVersion packaging)
      analyzer.py       ← from steampulse/analyzer.py
      fetcher.py        ← from steampulse/fetcher.py
      reporter.py       ← from steampulse/reporter.py
      steam_source.py   ← from steampulse/steam_source.py
      storage.py        ← from steampulse/storage.py
    pyproject.toml      (already exists — no changes needed)

  lambda-functions/
    lambda_functions/
      app_crawler/
        handler.py      (already exists)
      review_crawler/
        handler.py      (already exists)
      api/              ← NEW Lambda handler directory
        handler.py      ← from steampulse/api.py (rename app → handler, see below)
        chat.py         ← from steampulse/chat.py
        rate_limiter.py ← from steampulse/rate_limiter.py
        templates/      ← from steampulse/templates/

main.py               ← from steampulse/main.py (move to project root)
```

## Migration Steps

### 1. Move shared modules into `src/library-layer/library_layer/`

Move these files (do NOT delete originals yet — update imports first):
- `steampulse/analyzer.py` → `src/library-layer/library_layer/analyzer.py`
- `steampulse/fetcher.py` → `src/library-layer/library_layer/fetcher.py`
- `steampulse/reporter.py` → `src/library-layer/library_layer/reporter.py`
- `steampulse/steam_source.py` → `src/library-layer/library_layer/steam_source.py`
- `steampulse/storage.py` → `src/library-layer/library_layer/storage.py`

All relative imports (`from .storage import ...`) become absolute (`from library_layer.storage import ...`).

### 2. Create `src/lambda-functions/lambda_functions/api/` Lambda

Move API-specific files:
- `steampulse/api.py` → `src/lambda-functions/lambda_functions/api/handler.py`
- `steampulse/chat.py` → `src/lambda-functions/lambda_functions/api/chat.py`
- `steampulse/rate_limiter.py` → `src/lambda-functions/lambda_functions/api/rate_limiter.py`
- `steampulse/templates/` → `src/lambda-functions/lambda_functions/api/templates/`

Update imports in `handler.py` (was `api.py`):
```python
# BEFORE:
from .analyzer import analyze_reviews
from .rate_limiter import consume, get_client_ip, is_rate_limited
from .steam_source import DirectSteamSource, SteamAPIError
from .storage import BaseStorage, get_storage

# AFTER:
from library_layer.analyzer import analyze_reviews
from library_layer.steam_source import DirectSteamSource, SteamAPIError
from library_layer.storage import BaseStorage, get_storage
from .rate_limiter import consume, get_client_ip, is_rate_limited
```

Update imports in `chat.py`:
```python
# BEFORE:
from .storage import BaseStorage
# AFTER:
from library_layer.storage import BaseStorage
```

### 3. Move CLI tool

Move `steampulse/main.py` → `main.py` at project root.
Update imports:
```python
# BEFORE:
from steampulse.steam_source import ...
from steampulse.analyzer import ...
# AFTER:
from library_layer.steam_source import ...
from library_layer.analyzer import ...
```

### 4. Update crawler handlers

In `src/lambda-functions/lambda_functions/app_crawler/handler.py` and `review_crawler/handler.py`:
```python
# BEFORE:
from steampulse.steam_source import DirectSteamSource, SteamAPIError
# AFTER:
from library_layer.steam_source import DirectSteamSource, SteamAPIError
```

### 5. Update `infra/stacks/app_stack.py`

The API Lambda handler reference needs to point to the new location:
```python
# BEFORE:
handler="api.app",   # or whatever it currently says
# AFTER:
handler="lambda_functions.api.handler.handler",
code=lambda_.Code.from_asset("src/lambda-functions"),
```

Also add `layers=[library_layer]` to the API Lambda function — it needs the shared deps.
This requires passing `library_layer` from `application_stage.py` into `AppStack`.

### 6. Delete `steampulse/`

Once all imports are updated and tests pass, delete:
- `steampulse/` directory entirely (including `__pycache__/`)

### 7. Update `pyproject.toml`

The root `pyproject.toml` has `packages = [{include = "steampulse"}]`. Remove it since
`steampulse` no longer exists at the root. The project entry point is now `main.py`.

## Acceptance Criteria

- [ ] `src/library-layer/library_layer/` contains: `analyzer.py`, `fetcher.py`, `reporter.py`, `steam_source.py`, `storage.py`
- [ ] `src/lambda-functions/lambda_functions/api/` contains: `handler.py`, `chat.py`, `rate_limiter.py`, `templates/`
- [ ] `main.py` exists at project root
- [ ] Root `steampulse/` directory is deleted
- [ ] No file anywhere imports `from steampulse.` or `from .` referencing old steampulse modules
- [ ] All shared module imports use `from library_layer.X import ...`
- [ ] `infra/stacks/app_stack.py` API Lambda uses `code=from_asset("src/lambda-functions")` and `layers=[library_layer]`
- [ ] `poetry run cdk synth` completes with no errors
- [ ] `poetry run python main.py --help` works (CLI still functional)
- [ ] Run `git diff --stat` and show all changed/created/deleted files

## Do NOT Change

- `src/lambda-functions/lambda_functions/app_crawler/handler.py` business logic
- `src/lambda-functions/lambda_functions/review_crawler/handler.py` business logic
- Any CDK stack other than `app_stack.py` and `application_stage.py`
- `src/library-layer/pyproject.toml`
- Tests (update imports only if they break)
