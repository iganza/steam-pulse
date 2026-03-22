---
name: steampulse-architecture
description: SteamPulse backend architecture patterns — repository/service/handler layers, DRY rules, LLM pipeline, and what lives where. Use this when writing or modifying any Python backend code in src/.
---

## Layer Boundaries (mandatory)

SteamPulse uses a strict three-layer architecture. **Breaking layer boundaries creates technical debt that is hard to undo.**

```
Handler  (lambda_functions/*/handler.py)
  └── Service  (library_layer/services/)
        └── Repository  (library_layer/repositories/)
              └── Utils  (library_layer/utils/)
```

### Repository (`library_layer/repositories/`)

- **Only layer that writes SQL.** No SQL anywhere else — ever.
- One class per domain entity. Current repositories:
  - `GameRepository` — games table + game_tags + game_genres
  - `ReviewRepository` — reviews table
  - `ReportRepository` — reports table (upsert on re-analysis)
  - `CatalogRepository` — app_catalog table
  - `JobRepository` — analysis job tracking
- Methods return typed domain models (dataclasses), not raw dicts or psycopg2 rows.
- No business logic, no HTTP calls, no LLM calls. Pure I/O.
- Constructor receives a psycopg2 connection. Connection management is the caller's responsibility.

```python
class GameRepository:
    def __init__(self, conn: connection) -> None:
        self._conn = conn

    def get_by_appid(self, appid: int) -> Game | None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT * FROM games WHERE appid = %s", (appid,))
            row = cur.fetchone()
        return row_to_game(row) if row else None
```

### Service (`library_layer/services/`)

- **Business logic only.** Coordinates repositories, calls Steam API, calls Bedrock. No raw SQL.
- If you need data, call a repository method. If you find yourself writing `cur.execute(...)` in a service, stop and add a repository method instead.
- Constructor receives repositories and any external clients via dependency injection.
- Current services: `CrawlService`, `CatalogService`, `AnalysisService`

```python
class CrawlService:
    def __init__(
        self,
        game_repo: GameRepository,
        review_repo: ReviewRepository,
        steam: SteamDataSource,
        sfn_client: Any | None = None,
        sfn_arn: str | None = None,
    ) -> None:
        ...
```

### Handler (`lambda_functions/*/handler.py`)

- **Thin dispatcher only.** Parse Lambda event → call service method → return response.
- No SQL, no business logic, no HTTP calls. If handler logic is growing, extract to a service.
- Initialise DB connections and external clients at **module level** (outside the handler function) for warm container reuse.

```python
# Module-level init — runs once on cold start, reused on warm invocations
_conn = _get_db_connection()
_repos = _build_repositories(_conn)
_services = _build_services(_repos)

def handler(event: dict, context: Any) -> dict:
    body = parse_event(event)
    return _services.crawl.crawl_app(body.appid)
```

### Utils (`library_layer/utils/`)

- **DRY.** Any logic used by more than one repository or service lives here.
- Current utilities:
  - `utils/text.py` — `slugify()`, HTML stripping
  - `utils/aws.py` — `send_sqs_batch()`, SQS helpers
  - `utils/db.py` — `row_to_model()`, connection helpers
  - `utils/scores.py` — `compute_sentiment_score()`, `compute_hidden_gem_score()`
- Import hierarchy: handlers → services → repositories → utils. No circular imports.
- Never duplicate a utility. If you're copying a function between two files, it belongs in utils.

## No ORM

Raw psycopg2 only. No SQLAlchemy, no Peewee, no any ORM. Reasons:
- Schema is simple and stable
- Single-purpose Lambda functions don't benefit from ORM abstractions
- Direct SQL gives full visibility into what queries run

## Python Code Style

- **Type hints on everything** — all parameters and return types including `-> None`
- `str | None` not `Optional[str]` — never import `Optional`
- `match` statements for multi-branch dispatch, not long `if/elif` chains
- `dataclasses.dataclass` or `pydantic.BaseModel` for domain objects — never plain `dict`
- `async def` for FastAPI routes and HTTP calls; plain `def` for repository methods (psycopg2 is synchronous and blocks the event loop — wrapping it in async gives no benefit)
- `httpx.AsyncClient` for all outbound HTTP — create at module level, reuse across invocations
- `asyncio.TaskGroup` (not `asyncio.gather`) when parallelizing genuinely async work

## LLM Two-Pass Pipeline

**Pass 1 (Haiku — cheap):** Each 50-review chunk → extract signal types:
`design_praise`, `gameplay_friction`, `wishlist_items`, `dropout_moments`, `competitor_refs`, `notable_quotes`, `batch_stats`

**Pass 2 (Sonnet — synthesis):** All chunk summaries for one game → structured report JSON.

`sentiment_score` and `hidden_gem_score` are **always computed in Python** before calling Sonnet. Never ask the LLM to compute scores.

**Two execution paths — same prompts, different delivery:**

| Path | When | Mechanism | Notes |
|---|---|---|---|
| Real-time | On-demand single game | `boto3 bedrock_runtime.converse()` | Prompt caching works here |
| Batch | Bulk seed / scheduled | Bedrock Batch Inference (S3 JSONL) | No prompt caching in batch |

Always use the **Converse API** (`bedrock_runtime.converse()`) for real-time calls — it is model-agnostic. Swap model ID via env var, zero code changes.

```python
bedrock = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)

resp = bedrock.converse(
    modelId=HAIKU_MODEL,
    system=[{"text": system_prompt}],
    messages=[{"role": "user", "content": [{"text": user_content}]}],
    inferenceConfig={"maxTokens": 1024, "temperature": 0.3},
)
text = resp["output"]["message"]["content"][0]["text"]
```

For prompt caching on the real-time path, add `"cachePoint": {"type": "default"}` to the system array. Do NOT include cache_control in batch JSONL records.

## Report Section Anti-Duplication Rule

Each section answers a different question. The same root cause can appear in multiple sections only if each describes a different aspect:
- `gameplay_friction` = the design flaw ("matchmaking has no skill separation")
- `churn_triggers` = WHEN it causes dropout ("new players hit bots in their first 10 minutes")
- `dev_priorities` = the ranked fix with ROI ("deploy bot detection — #1 new-player churn driver")
- `player_wishlist` = net-new features only (not fixes to broken things)

If the same sentence or framing appears in two sections — that is duplication. Remove it from the section whose definition fits least.

## Directory Reference

```
src/
  library-layer/library_layer/
    repositories/      # SQL I/O only
    services/          # Business logic only
    utils/             # Shared helpers (DRY)
    analyzer.py        # Two-pass LLM pipeline
    steam_source.py    # SteamDataSource abstraction
    models.py          # Domain dataclasses
  lambda-functions/lambda_functions/
    app_crawler/handler.py      # SQS trigger → CrawlService
    review_crawler/handler.py   # SQS trigger → CrawlService
    analysis/handler.py         # Step Functions task → AnalysisService
    api/handler.py              # FastAPI app → all services
tests/
  unit/        # pytest + moto, no real AWS
  integration/ # pytest + real local Postgres (docker-compose)
```

## What NOT to Build

- No user accounts or login
- No database migrations framework — raw SQL schema init in repositories
- No ORM of any kind
- No business logic in repositories, no SQL in services
- No payment integration — `/api/validate-key` is intentionally stubbed to always grant access
