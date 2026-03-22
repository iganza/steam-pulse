# SteamPulse — Repository/Service Pattern Refactor + Full Test Suite

## Context

SteamPulse is an AI-powered Steam game intelligence platform. The backend is Python 3.12, FastAPI + Lambda, PostgreSQL on RDS. Dependency management is Poetry.

The codebase currently has SQL scattered directly inside Lambda handler modules (`app_crawl.py`, `review_crawl.py`, `catalog_refresh.py`) and a legacy `storage.py` that mixes schema DDL with ad-hoc query methods. There are no clean layer boundaries.

**Goal:** Refactor to a strict repository → service → handler architecture. Add a full unit + integration test suite using pytest, psycopg2 against a real (in-process) PostgreSQL, and moto for AWS service mocks.

---

## Current Structure

```
src/
├── lambda-functions/lambda_functions/
│   ├── crawler/
│   │   ├── handler.py          # Unified Lambda dispatcher
│   │   ├── events.py           # Pydantic event models
│   │   ├── app_crawl.py        # Metadata crawl — SQL inline
│   │   ├── review_crawl.py     # Review crawl — SQL inline
│   │   ├── catalog_refresh.py  # Catalog refresh — SQL inline
│   │   └── _db.py              # DB connection helper
│   ├── api/
│   │   ├── handler.py          # FastAPI app
│   │   └── chat.py
│   └── analysis/
│       ├── handler.py
│       └── events.py
└── library-layer/library_layer/
    ├── storage.py              # Legacy: schema DDL + mixed queries
    ├── steam_source.py         # Steam API HTTP client
    ├── config.py               # Pydantic settings
    ├── analyzer.py             # LLM two-pass analysis
    └── reporter.py
tests/
├── conftest.py
├── test_app_crawler.py
├── test_review_crawler.py
├── test_api.py
└── fixtures/
    ├── steam_appdetails_440.json
    └── steam_reviews_440.json
```

---

## Target Architecture

### Layer Rules (enforce strictly)

1. **Repositories** — pure SQL I/O only. No business logic. Accept a psycopg2 connection. Return typed Pydantic models or None. Never call AWS, never call Steam.
2. **Services** — business logic only. Orchestrate repositories + external clients (Steam API, SQS, Step Functions). No SQL strings. No direct psycopg2 usage.
3. **Handlers** — dispatch only. Validate event (already Pydantic), call one service method, return result. Zero SQL, zero business logic.

### New File Layout

```
src/library-layer/library_layer/
├── models/
│   ├── __init__.py
│   ├── game.py           # Game, GameSummary Pydantic models
│   ├── review.py         # Review Pydantic model
│   ├── catalog.py        # CatalogEntry, CatalogStatus Pydantic models
│   ├── report.py         # Report Pydantic model
│   └── tag.py            # Tag, Genre, Category Pydantic models
├── repositories/
│   ├── __init__.py
│   ├── base.py           # BaseRepository(conn) with _execute / _fetchone / _fetchall helpers
│   ├── game_repo.py      # GameRepository
│   ├── review_repo.py    # ReviewRepository
│   ├── catalog_repo.py   # CatalogRepository
│   ├── report_repo.py    # ReportRepository
│   └── tag_repo.py       # TagRepository (tags + genres + categories)
├── services/
│   ├── __init__.py
│   ├── crawl_service.py      # CrawlService: orchestrates Steam API + repos + SQS
│   ├── analysis_service.py   # AnalysisService: LLM calls + report persistence
│   └── catalog_service.py    # CatalogService: GetAppList + upsert + enqueue
├── utils/
│   ├── __init__.py
│   └── slugify.py        # _slugify() helper (currently duplicated across modules)
├── schema.py             # All CREATE TABLE DDL (moved from storage.py, pure strings)
├── steam_source.py       # Unchanged
├── config.py             # Unchanged
├── analyzer.py           # Unchanged (consumed by AnalysisService)
└── reporter.py           # Unchanged
```

The old `storage.py` is deleted after migration. The `InMemoryStorage` and `PostgresStorage` classes are replaced by the repository layer.

---

## DRY Principle — Shared Utilities

**Before writing any repository or service method, check whether the logic already exists elsewhere or will be needed in more than one place. If so, extract it into `library_layer/utils/` and import from there.**

Common candidates that must NOT be duplicated:

- **`slugify(text: str, suffix: str | int | None = None) -> str`** — slug generation is currently copy-pasted across `app_crawl.py` and other modules. Extract once into `utils/slugify.py`.
- **Review delta thresholds** — the tiered `_should_enqueue_reviews()` logic belongs in a shared utility or on `CrawlService` only — never duplicated in both the service and `sp.py`.
- **SQS batch sending** — chunking a list into batches of 10 and calling `sqs.send_message_batch()` is a pattern used in both catalog refresh and app crawl. Extract a `send_sqs_batch(client, queue_url, messages)` helper into `utils/sqs.py`.
- **psycopg2 row → model conversion** — if multiple repos share the same `RealDictRow → Pydantic model` construction pattern, put a generic `row_to_model(row, model_class)` helper in `utils/db.py`.
- **Timestamp normalisation** — Unix int → `datetime` with UTC timezone appears in review parsing. Extract into `utils/time.py` if used in more than one place.

The rule: **if you write the same logic twice, stop and extract it**. Repositories and services may only import from `library_layer.utils`, `library_layer.models`, or each other (services may import repos; repos must not import services).

---

## Models

Define Pydantic models (not dataclasses) for all DB entities. Use `model_config = ConfigDict(from_attributes=True)` so they can be constructed from psycopg2 `RealDictRow`.

### game.py
```python
class Game(BaseModel):
    appid: int
    name: str
    slug: str
    type: str | None = None
    developer: str | None = None
    publisher: str | None = None
    developers: list[str] = []
    publishers: list[str] = []
    website: str | None = None
    release_date: str | None = None
    coming_soon: bool = False
    price_usd: Decimal | None = None
    is_free: bool = False
    short_desc: str | None = None
    detailed_description: str | None = None
    about_the_game: str | None = None
    review_count: int = 0
    total_positive: int = 0
    total_negative: int = 0
    positive_pct: Decimal | None = None
    review_score_desc: str | None = None
    header_image: str | None = None
    background_image: str | None = None
    required_age: int = 0
    platforms: dict = {}
    supported_languages: str | None = None
    achievements_total: int = 0
    metacritic_score: int | None = None
    crawled_at: datetime | None = None
    data_source: str = "steam_direct"
```

### review.py
```python
class Review(BaseModel):
    id: int | None = None
    appid: int
    steam_review_id: str
    voted_up: bool
    playtime_hours: int = 0
    body: str
    posted_at: datetime
    crawled_at: datetime | None = None
```

### catalog.py
```python
class CatalogEntry(BaseModel):
    appid: int
    name: str
    meta_status: str = "pending"
    meta_crawled_at: datetime | None = None
    review_count: int | None = None
    review_status: str = "pending"
    review_crawled_at: datetime | None = None
    discovered_at: datetime | None = None
```

### report.py
```python
class Report(BaseModel):
    appid: int
    report_json: dict
    reviews_analyzed: int = 0
    analysis_version: str | None = None
    is_public: bool = False
    seo_title: str | None = None
    seo_description: str | None = None
    last_analyzed: datetime | None = None
    created_at: datetime | None = None
```

---

## Repositories

### BaseRepository (base.py)
```python
class BaseRepository:
    def __init__(self, conn: psycopg2.connection) -> None:
        self.conn = conn

    def _execute(self, sql: str, params: tuple = ()) -> psycopg2.cursor: ...
    def _fetchone(self, sql: str, params: tuple = ()) -> RealDictRow | None: ...
    def _fetchall(self, sql: str, params: tuple = ()) -> list[RealDictRow]: ...
```

### GameRepository (game_repo.py)
Methods:
- `upsert(game_data: dict) -> None` — INSERT ... ON CONFLICT (appid) DO UPDATE
- `find_by_appid(appid: int) -> Game | None`
- `find_by_slug(slug: str) -> Game | None`
- `find_eligible_for_reviews(min_reviews: int = 500) -> list[Game]`
- `update_review_stats(appid: int, total_positive: int, total_negative: int, review_count: int, review_score_desc: str) -> None`

### ReviewRepository (review_repo.py)
Methods:
- `bulk_upsert(reviews: list[dict]) -> int` — INSERT ... ON CONFLICT (steam_review_id) DO UPDATE, returns rows inserted
- `count_by_appid(appid: int) -> int`
- `find_by_appid(appid: int, limit: int = 100, offset: int = 0) -> list[Review]`
- `latest_posted_at(appid: int) -> datetime | None`

### CatalogRepository (catalog_repo.py)
Methods:
- `bulk_upsert(entries: list[dict]) -> int` — INSERT ... ON CONFLICT (appid) DO NOTHING, returns new rows
- `find_by_appid(appid: int) -> CatalogEntry | None`
- `find_pending_meta(limit: int | None = None) -> list[CatalogEntry]`
- `find_pending_reviews(limit: int | None = None) -> list[CatalogEntry]`
- `set_meta_status(appid: int, status: str, review_count: int | None = None, review_status: str | None = None) -> None`
- `set_review_status(appid: int, status: str) -> None`
- `status_summary() -> dict` — counts per meta_status + review_status

### ReportRepository (report_repo.py)
Methods:
- `upsert(report: dict) -> None`
- `find_by_appid(appid: int) -> Report | None`
- `find_public(limit: int = 50, offset: int = 0) -> list[Report]`

### TagRepository (tag_repo.py)
Methods:
- `upsert_tags(items: list[dict]) -> None` — tags + game_tags
- `upsert_genres(appid: int, genres: list[dict]) -> None` — genres + game_genres
- `upsert_categories(appid: int, categories: list[dict]) -> None` — game_categories
- `find_tags_for_game(appid: int) -> list[dict]`
- `find_genres_for_game(appid: int) -> list[dict]`

---

## Services

### CrawlService (crawl_service.py)
```python
class CrawlService:
    def __init__(
        self,
        game_repo: GameRepository,
        review_repo: ReviewRepository,
        catalog_repo: CatalogRepository,
        tag_repo: TagRepository,
        steam: DirectSteamSource,
        sqs_client,           # boto3 SQS client
        review_queue_url: str,
    ) -> None: ...

    async def crawl_app(self, appid: int, dry_run: bool = False) -> bool:
        """Fetch app details + review summary from Steam → upsert to DB → maybe enqueue review crawl."""

    async def crawl_reviews(self, appid: int, dry_run: bool = False, max_reviews: int | None = None) -> int:
        """Fetch all reviews from Steam → bulk upsert → trigger Step Functions."""

    def _should_enqueue_reviews(self, review_count: int, stored_count: int) -> bool:
        """Apply tiered delta thresholds."""
```

All SQL that currently lives in `app_crawl.py` and `review_crawl.py` moves into the repos. All business logic (threshold calculation, slug generation, Step Functions trigger) moves into CrawlService.

### CatalogService (catalog_service.py)
```python
class CatalogService:
    def __init__(
        self,
        catalog_repo: CatalogRepository,
        steam: httpx.Client,
        sqs_client,
        app_crawl_queue_url: str,
        steam_api_key: str | None = None,
    ) -> None: ...

    def refresh(self) -> dict:
        """Fetch GetAppList → bulk upsert → enqueue pending."""

    def enqueue_pending(self) -> int:
        """Send all pending catalog entries to app-crawl-queue."""

    def status(self) -> dict:
        """Return counts per status from catalog_repo.status_summary()."""
```

### AnalysisService (analysis_service.py)
```python
class AnalysisService:
    def __init__(
        self,
        report_repo: ReportRepository,
        review_repo: ReviewRepository,
        game_repo: GameRepository,
        analyzer,   # existing Analyzer from library_layer.analyzer
    ) -> None: ...

    async def analyze(self, appid: int) -> Report:
        """Load reviews from DB → run LLM analysis → upsert report → return Report."""
```

---

## Handler Updates

After refactor, each Lambda handler becomes thin:

### crawler/handler.py
```python
# Build repos + service once per cold start (module-level after DB conn init)
# On each invocation:
# 1. Validate event with existing Pydantic models
# 2. Call service.crawl_app() / service.crawl_reviews() / catalog_service.refresh()
# 3. Return result dict
```

The handler must NOT instantiate repos/services inside the hot path — build them once at module level after `get_conn()`.

---

## schema.py

Move ALL `CREATE TABLE` DDL from `storage.py` into `schema.py` as a module-level tuple of SQL strings:

```python
TABLES: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS games (...)""",
    """CREATE TABLE IF NOT EXISTS reviews (...)""",
    # ... all 13 tables
)

def create_all(conn) -> None:
    """Execute all DDL statements. Idempotent."""
    with conn.cursor() as cur:
        for ddl in TABLES:
            cur.execute(ddl)
    conn.commit()
```

`PostgresStorage` in `storage.py` currently calls DDL at init — replace with `schema.create_all(conn)` in `_db.py` or the handler cold-start path.

---

## Tests

### Testing Philosophy

- **Unit tests** — test each repository method in isolation against a real psycopg2 connection to a test database (not mocked SQL). Use pytest fixtures to create/tear down tables.
- **Service tests** — test service methods with real repos (real DB) + mocked AWS clients (moto) + mocked Steam HTTP (pytest-httpx).
- **Handler tests** — test the Lambda handler end-to-end: inject a crafted event dict, mock AWS + Steam, assert DB state after.
- **No mocking of repositories in service tests** — the boundary to mock is external I/O (AWS, HTTP), not internal repo calls. This gives confidence the wiring is correct.

### Test Database Setup

Use a real PostgreSQL connection for all DB tests. Do NOT use SQLite or in-memory fakes for the DB layer — psycopg2-specific features (JSONB, ON CONFLICT, RETURNING) must be tested against real Postgres.

Options (in order of preference):
1. `pytest-postgresql` — spins up a real Postgres process per test session
2. Docker Compose `postgres:16` service pre-started before `pytest`
3. `DATABASE_URL` env var pointing to a local Postgres instance

Use `pytest-postgresql` if available. Otherwise read `DATABASE_URL` from env, skip DB tests if not set.

### conftest.py (replace existing)

```python
import pytest
import psycopg2
import psycopg2.extras
from library_layer.schema import create_all
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.catalog_repo import CatalogRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.tag_repo import TagRepository

# --- Database fixtures ---

@pytest.fixture(scope="session")
def db_conn():
    """Single connection for the whole test session. Tables created once."""
    import os
    url = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/steampulse_test")
    conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    create_all(conn)
    yield conn
    conn.close()

@pytest.fixture(autouse=True)
def clean_tables(db_conn):
    """Truncate all tables before each test. Faster than recreating."""
    with db_conn.cursor() as cur:
        cur.execute("""
            TRUNCATE games, reviews, tags, game_tags, genres, game_genres,
                     game_categories, reports, app_catalog, rate_limits,
                     analysis_jobs, game_relations, index_insights
            RESTART IDENTITY CASCADE
        """)
    db_conn.commit()
    yield

# --- Repository fixtures ---

@pytest.fixture
def game_repo(db_conn): return GameRepository(db_conn)

@pytest.fixture
def review_repo(db_conn): return ReviewRepository(db_conn)

@pytest.fixture
def catalog_repo(db_conn): return CatalogRepository(db_conn)

@pytest.fixture
def report_repo(db_conn): return ReportRepository(db_conn)

@pytest.fixture
def tag_repo(db_conn): return TagRepository(db_conn)

# --- AWS mocks ---

@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")

@pytest.fixture
def sqs_client(aws_credentials):
    from moto import mock_aws
    with mock_aws():
        import boto3
        client = boto3.client("sqs", region_name="us-west-2")
        yield client

@pytest.fixture
def mock_queues(sqs_client):
    app_q = sqs_client.create_queue(QueueName="app-crawl-queue")["QueueUrl"]
    review_q = sqs_client.create_queue(QueueName="review-crawl-queue")["QueueUrl"]
    return {"app": app_q, "review": review_q}

@pytest.fixture
def sfn_client(aws_credentials):
    from moto import mock_aws
    with mock_aws():
        import boto3
        client = boto3.client("stepfunctions", region_name="us-west-2")
        yield client

# --- Steam HTTP fixtures (loaded from fixtures/) ---

@pytest.fixture
def steam_appdetails_440():
    import json, pathlib
    return json.loads((pathlib.Path(__file__).parent / "fixtures/steam_appdetails_440.json").read_text())

@pytest.fixture
def steam_reviews_440():
    import json, pathlib
    return json.loads((pathlib.Path(__file__).parent / "fixtures/steam_reviews_440.json").read_text())

# --- Lambda context ---

class MockLambdaContext:
    function_name = "test-function"
    memory_limit_in_mb = 128
    invoked_function_arn = "arn:aws:lambda:us-west-2:123456789012:function:test"
    aws_request_id = "test-request-id"
    def get_remaining_time_in_millis(self): return 30000

@pytest.fixture
def lambda_context():
    return MockLambdaContext()
```

### Test Files to Create

#### tests/repositories/test_game_repo.py
Test every GameRepository method:
- `test_upsert_inserts_new_game` — insert and retrieve, assert all fields round-trip
- `test_upsert_updates_existing_game` — upsert same appid twice with different data, assert updated values
- `test_find_by_appid_returns_none_for_missing` — missing appid returns None
- `test_find_by_slug` — slug lookup works
- `test_find_eligible_for_reviews` — only games with review_count >= 500 returned
- `test_update_review_stats` — updates only the review stat columns, leaves rest untouched

#### tests/repositories/test_review_repo.py
- `test_bulk_upsert_inserts_reviews` — insert batch, assert count_by_appid
- `test_bulk_upsert_is_idempotent` — upsert same reviews twice, no duplicates
- `test_find_by_appid_paginates` — offset/limit respected
- `test_latest_posted_at` — returns max timestamp from inserted reviews

#### tests/repositories/test_catalog_repo.py
- `test_bulk_upsert_skips_existing` — ON CONFLICT DO NOTHING, returns only new row count
- `test_set_meta_status` — status transitions + review_count write
- `test_set_review_status` — status update
- `test_find_pending_meta` — returns only pending entries
- `test_status_summary` — counts are accurate after mixed inserts

#### tests/repositories/test_report_repo.py
- `test_upsert_and_find` — insert report, find by appid, assert report_json round-trip
- `test_find_public` — only is_public=True reports returned

#### tests/repositories/test_tag_repo.py
- `test_upsert_genres` — genres + game_genres populated correctly
- `test_upsert_categories` — game_categories populated correctly
- `test_upsert_tags` — tags + game_tags populated correctly

#### tests/utils/test_slugify.py
- `test_basic_slug` — "Team Fortress 2" → "team-fortress-2-440"
- `test_slug_with_special_chars` — unicode, punctuation stripped correctly
- `test_slug_empty_name` — fallback to "app-{appid}"
- `test_slug_uniqueness` — same name + different appid → different slug

#### tests/services/test_crawl_service.py
Use `pytest_httpx` to mock Steam HTTP responses. Use real repos + real DB. Use moto for SQS.

- `test_crawl_app_stores_game` — mock appdetails + review summary HTTP, call crawl_app(440), assert game_repo.find_by_appid(440) is not None with correct fields
- `test_crawl_app_enqueues_review_crawl_when_eligible` — game with 1000 reviews → SQS message on review queue
- `test_crawl_app_does_not_enqueue_ineligible` — game with 50 reviews → no SQS message
- `test_crawl_app_skips_non_game` — appdetails returns type="dlc" → catalog marked skipped, no game row
- `test_crawl_app_handles_steam_error` — appdetails returns 500 → raises or returns False gracefully
- `test_crawl_reviews_stores_reviews` — mock paginated reviews HTTP, call crawl_reviews(440), assert review_repo.count_by_appid(440) > 0
- `test_crawl_reviews_deduplicates` — same reviews crawled twice → no duplicate rows
- `test_should_enqueue_reviews_thresholds` — parametrize all 5 tiers, assert correct True/False

#### tests/services/test_catalog_service.py
- `test_refresh_inserts_new_apps` — mock GetAppList HTTP, call refresh(), assert catalog_repo has new rows
- `test_refresh_skips_existing` — existing appid not duplicated
- `test_enqueue_pending` — pending entries → SQS messages sent
- `test_status_returns_counts` — insert mix of statuses, call status(), assert counts correct

#### tests/handlers/test_crawler_handler.py
End-to-end handler tests (replace existing test_app_crawler.py, test_review_crawler.py):
- `test_handler_sqs_app_crawl` — inject SQS event with appid 440, mock Steam HTTP, assert game in DB
- `test_handler_sqs_review_crawl` — inject SQS event, mock reviews HTTP, assert reviews in DB
- `test_handler_catalog_refresh` — inject EventBridge event, mock GetAppList, assert catalog rows
- `test_handler_direct_crawl_apps` — inject direct action event, mock Steam, assert DB state
- `test_handler_batch_processes_multiple` — SQS batch of 3 appids, all stored

---

## Migration Steps

Perform in this order to avoid breaking the working crawler:

1. Create `schema.py` — move DDL from `storage.py`, verify `create_all()` runs cleanly
2. Create `utils/` — extract `slugify`, `send_sqs_batch`, and any other shared helpers; write tests first
3. Create `models/` — all Pydantic models
4. Create `repositories/` — one by one, each with its tests passing before moving on
5. Create `services/` — one by one, each with its tests passing
6. Update `crawler/handler.py` — instantiate repos + services at module level, thin dispatch
7. Update `api/handler.py` — replace any storage.py calls with repos
8. Update `scripts/sp.py` — replace inline SQL with repo/service calls
9. Delete `storage.py` — only after all callers migrated

At each step, run `poetry run pytest` before proceeding. Never leave tests broken.

---

## Constraints

- Do NOT introduce SQLAlchemy or any ORM. Raw psycopg2 SQL only.
- Do NOT change the PostgreSQL schema (table names, column names, types). The live DB has data.
- Do NOT change `steam_source.py`, `config.py`, `analyzer.py`, `reporter.py` — they are out of scope.
- Do NOT change CDK infra or Lambda packaging.
- Do NOT change Pydantic event models in `events.py`.
- Keep `_db.py` for connection management — it can call `schema.create_all()` on first connect.
- All new code must pass `ruff check` and `mypy --strict` (match existing config in pyproject.toml).
- Poetry dependency group for test deps already has: `pytest`, `pytest-asyncio`, `pytest-httpx`, `moto[sqs,stepfunctions,secretsmanager]`. Add `pytest-postgresql` if needed.

---

## Definition of Done

- [ ] All 13 SQL tables accessible only through repository methods
- [ ] Zero SQL strings outside `repositories/` and `schema.py`
- [ ] Zero business logic inside repository methods
- [ ] All Lambda handlers under 30 lines each (dispatch + return only)
- [ ] No logic duplicated across modules — shared helpers live in `library_layer/utils/`
- [ ] `storage.py` deleted
- [ ] `poetry run pytest` passes with ≥ 80% coverage on repositories, services, and utils
- [ ] `poetry run ruff check src/ tests/` passes
- [ ] `poetry run mypy src/library-layer/ src/lambda-functions/` passes
