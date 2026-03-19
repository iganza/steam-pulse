# Task: Fix Crawler Lambda Packaging (Phase 3 completion)

Read `CLAUDE.md` and `steam_analyzer_prompt.md` fully before starting.

## Context

Both Lambda functions in `infra/stacks/crawler_stack.py` use a placeholder stub
(`lambda_.Code.from_inline(_PLACEHOLDER)`) instead of real code. The actual crawler
code lives in `crawler/` (`app_crawler.py`, `review_crawler.py`) but is never packaged
or deployed. This task reorganises the project into a clean `src/` layout and wires
everything up properly using two Lambda Layers and new stacks.

## Target Directory Structure

```
src/
  library-layer/              # Subproject: shared Python deps + steampulse framework
    pyproject.toml            # Standalone Poetry project with httpx, psycopg2-binary, boto3, anthropic
    library_layer/            # Package directory (can be empty __init__.py)
    steampulse/               # Symlink → ../../steampulse/ (bundled into the layer)

  lambda-layer/               # Subproject: thin shared Lambda utilities (no heavy deps)
    pyproject.toml            # Standalone Poetry project — minimal or no deps
    lambda_layer/             # Package with shared Lambda handler utilities

  lambda-functions/           # All Lambda handler code
    lambda_functions/
      app_crawler/            # App crawler Lambda
        __init__.py
        handler.py            # moved + refactored from crawler/app_crawler.py
      review_crawler/         # Review crawler Lambda
        __init__.py
        handler.py            # moved + refactored from crawler/review_crawler.py
```

In CDK, all Lambdas use:
```python
code=lambda_.Code.from_asset("src/lambda-functions"),
handler="lambda_functions.app_crawler.handler",   # or review_crawler.handler
layers=[library_layer],
```

This way `src/lambda-functions` is the single asset directory for all Lambdas — clean
and consistent. The heavy deps and `steampulse` framework come from the layer.

## What to Build

### 1. Create `src/library-layer/` subproject

Create `src/library-layer/pyproject.toml` as a standalone Poetry project:

```toml
[tool.poetry]
name = "library-layer"
version = "0.1.0"
description = "Shared Lambda layer: runtime deps + steampulse framework"
packages = [{ include = "library_layer" }, { include = "steampulse" }]

[tool.poetry.dependencies]
python = "^3.12"
httpx = ">=0.27.0"
psycopg2-binary = ">=2.9.9"
boto3 = ">=1.34.0"
anthropic = ">=0.40.0"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

Create `src/library-layer/library_layer/__init__.py` (empty is fine).

The `steampulse/` package must be accessible from this subproject so CDK can bundle it
into the layer. Either symlink or copy `../../steampulse` into `src/library-layer/steampulse/`.
A symlink is preferred: `ln -s ../../steampulse src/library-layer/steampulse`.

### 2. Create `src/lambda-layer/` subproject

Create `src/lambda-layer/pyproject.toml`:

```toml
[tool.poetry]
name = "lambda-layer"
version = "0.1.0"
description = "Thin Lambda handler utilities"
packages = [{ include = "lambda_layer" }]

[tool.poetry.dependencies]
python = "^3.12"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

Create `src/lambda-layer/lambda_layer/__init__.py` (empty is fine for now).

### 3. Create `infra/stacks/common_stack.py`

The `CommonStack` publishes the `library_layer` as a versioned Lambda Layer that all
other stacks reference. It must be deployed before any stack that uses the layer.

```python
"""CommonStack — shared Lambda layers published once, referenced by all stacks."""
import aws_cdk as cdk
import aws_cdk.aws_lambda as lambda_
from aws_cdk.aws_lambda_python_alpha import PythonLayerVersion
from constructs import Construct


class CommonStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        self.library_layer = PythonLayerVersion(
            self,
            "LibraryLayer",
            entry="src/library-layer",   # path relative to project root (where cdk.json is)
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="Shared deps (httpx, psycopg2, boto3, anthropic) + steampulse framework",
        )
```

### 5. Wire `CommonStack` into the pipeline stages

In `infra/application_stage.py`, add `CommonStack` as the first stack in each stage.
Pass `common_stack.library_layer` to `LambdaStack` (and eventually other stacks):

```python
from infra.stacks.common_stack import CommonStack
from infra.stacks.sqs_stack import SqsStack
from infra.stacks.lambda_stack import LambdaStack

class ApplicationStage(cdk.Stage):
    def __init__(self, ...):
        ...
        common_stack = CommonStack(self, "Common", ...)

        sqs_stack = SqsStack(self, "Sqs", ...)

        lambda_stack = LambdaStack(
            self, "Lambda",
            ...,
            library_layer=common_stack.library_layer,
            app_queue=sqs_stack.app_crawl_queue,
            review_queue=sqs_stack.review_crawl_queue,
        )
        lambda_stack.add_dependency(common_stack)
        lambda_stack.add_dependency(sqs_stack)
```

### 5b. Delete `crawler_stack.py`

`crawler_stack.py` is fully replaced by `sqs_stack.py` + `lambda_stack.py`.
Delete it and remove all references to `CrawlerStack` from `application_stage.py`.

### 4. Create `infra/stacks/sqs_stack.py`

Move all SQS queues and DLQs out of `crawler_stack.py` into `SqsStack`:

- `app_crawl_dlq`, `app_crawl_queue`
- `review_crawl_dlq`, `review_crawl_queue`

Expose all four as public attributes so `LambdaStack` can reference them.

### 5. Create `infra/stacks/lambda_stack.py`

All Lambda function definitions AND EventBridge rules live in `infra/stacks/lambda_stack.py`.
EventBridge sits here because it directly triggers the Lambdas — they're tightly coupled.
`LambdaStack` accepts `library_layer`, `app_queue`, `review_queue`, `vpc`, `db_secret`,
and `sfn_arn` as constructor params.

Move the Lambda `Function` definitions and event source mappings out of `crawler_stack.py`
into `LambdaStack`. Keep SQS queues, DLQs, and EventBridge rules in `crawler_stack.py`.

`CrawlerStack` must expose `app_queue`, `review_queue` as public attributes so
`application_stage.py` can pass them to `LambdaStack`.

**This is the core fix** — the Lambda definitions in `LambdaStack` must use real code:

```python
# BEFORE (remove — was in crawler_stack.py):
code=lambda_.Code.from_inline(_PLACEHOLDER),

# AFTER — both AppCrawler and ReviewCrawler in lambda_stack.py:
code=lambda_.Code.from_asset("crawler"),
layers=[library_layer],
```

Remove the `_PLACEHOLDER` constant entirely from `crawler_stack.py`.

### 5. Migrate Crawler Handlers to `src/lambda-functions/`

Move and refactor the crawler handler code:

- `crawler/app_crawler.py` → `src/lambda-functions/lambda_functions/app_crawler/handler.py`
- `crawler/review_crawler.py` → `src/lambda-functions/lambda_functions/review_crawler/handler.py`

When migrating, remove these fragile lines — the layer puts `steampulse` at
`/opt/python/` automatically, no path manipulation needed:

```python
# REMOVE from both handlers:
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
```

Ensure the handler entry point function is named `handler` in each file.

### 6. Add Missing Environment Variable

`app_crawler/handler.py` needs to enqueue appids to the review queue. Add to its environment in `lambda_stack.py`:

```python
"REVIEW_CRAWL_QUEUE_URL": self.review_queue.queue_url,
```

And grant send permissions:
```python
self.review_queue.grant_send_messages(role)
```

Verify `src/lambda-functions/lambda_functions/app_crawler/handler.py` reads
`REVIEW_CRAWL_QUEUE_URL` from `os.environ` and uses it — add the SQS send call if missing.

## Acceptance Criteria

- [ ] `src/library-layer/pyproject.toml` exists with correct deps
- [ ] `src/lambda-layer/pyproject.toml` exists
- [ ] `src/library-layer/steampulse` symlink (or copy) resolves correctly
- [ ] `infra/stacks/common_stack.py` exists and defines `LibraryLayer`
- [ ] `infra/stacks/sqs_stack.py` exists with all queues + DLQs
- [ ] `infra/application_stage.py` instantiates CommonStack → SqsStack → LambdaStack in order
- [ ] `infra/stacks/lambda_stack.py` exists with AppCrawler, ReviewCrawler, and EventBridge rules
- [ ] `infra/stacks/crawler_stack.py` is deleted
- [ ] `src/lambda-functions/lambda_functions/app_crawler/handler.py` exists (migrated from `crawler/`)
- [ ] `src/lambda-functions/lambda_functions/review_crawler/handler.py` exists (migrated from `crawler/`)
- [ ] No `sys.path.insert` in either handler
- [ ] Both Lambda CDK definitions use `code=lambda_.Code.from_asset("src/lambda-functions")` and correct `handler=` path
- [ ] `REVIEW_CRAWL_QUEUE_URL` is set on `AppCrawler` and `review_queue.grant_send_messages(role)` is called
- [ ] `cd infra && poetry run cdk synth` completes with no errors
- [ ] Run `git diff --stat` and show all changed/created files

## Files to Create

- `src/library-layer/pyproject.toml`
- `src/library-layer/library_layer/__init__.py`
- `src/library-layer/steampulse` (symlink → `../../steampulse`)
- `src/lambda-layer/pyproject.toml`
- `src/lambda-layer/lambda_layer/__init__.py`
- `src/lambda-functions/lambda_functions/__init__.py`
- `src/lambda-functions/lambda_functions/app_crawler/__init__.py`
- `src/lambda-functions/lambda_functions/app_crawler/handler.py` (migrated from `crawler/app_crawler.py`)
- `src/lambda-functions/lambda_functions/review_crawler/__init__.py`
- `src/lambda-functions/lambda_functions/review_crawler/handler.py` (migrated from `crawler/review_crawler.py`)
- `infra/stacks/common_stack.py`
- `infra/stacks/sqs_stack.py`
- `infra/stacks/lambda_stack.py`

## Files to Modify

- `infra/application_stage.py` — replace CrawlerStack with CommonStack + SqsStack + LambdaStack

## Files to Delete

- `infra/stacks/crawler_stack.py` — fully replaced by sqs_stack.py + lambda_stack.py
- `crawler/app_crawler.py` — migrated to `src/lambda-functions/lambda_functions/app_crawler/handler.py`
- `crawler/review_crawler.py` — migrated to `src/lambda-functions/lambda_functions/review_crawler/handler.py`
- `crawler/__init__.py` — no longer needed

## Do NOT Change

- Any other stack files (`app_stack.py`, `data_stack.py`, `frontend_stack.py`, etc.)
- Root `pyproject.toml` (the subprojects are independent)
- Crawler business logic
- `steampulse/` source files
