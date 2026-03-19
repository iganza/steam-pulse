# SteamPulse — Complete the Repository/Service Cleanup

## Context

A previous refactor introduced a clean repository/service layer in `library_layer/`. The services and repositories are correctly implemented. However, three old crawler modules (`app_crawl.py`, `review_crawl.py`, `catalog_refresh.py`) were never deleted — they are now **dead code** that duplicates the repository logic. The Lambda `crawler/handler.py` has already been updated to call services and no longer imports these files.

Additionally, `api/handler.py` still contains raw SQL inline rather than using repositories, and `scripts/sp.py` mixes raw psycopg2 calls with service usage.

**Goal:** Remove all dead code, wire `api/handler.py` to repositories, and clean up `sp.py`.

---

## Current State

### ✅ Already Done (do NOT change)

- `src/library-layer/library_layer/repositories/` — all repos implemented and correct
- `src/library-layer/library_layer/services/crawl_service.py` — correct, uses repos
- `src/library-layer/library_layer/services/catalog_service.py` — correct, uses repos
- `src/library-layer/library_layer/services/analysis_service.py` — correct, uses repos
- `src/library-layer/library_layer/utils/` — slugify, sqs, time helpers
- `src/lambda-functions/lambda_functions/crawler/handler.py` — already calls services, no raw SQL
- `src/library-layer/library_layer/schema.py` — DDL lives here

### ❌ Needs Fixing

| File | Problem |
|------|---------|
| `crawler/app_crawl.py` | Dead code — handler no longer imports it; contains duplicate SQL |
| `crawler/review_crawl.py` | Dead code — handler no longer imports it; contains duplicate SQL |
| `crawler/catalog_refresh.py` | Dead code — handler no longer imports it; contains duplicate SQL |
| `api/handler.py` | 5 raw SQL blocks inline; needs `job_repo.py` + use existing repos |
| `scripts/sp.py` | Mixed raw psycopg2 + service calls; should use repos/services consistently |

---

## Task 1: Delete Dead Crawler Modules

Verify the crawler `handler.py` does NOT import from `app_crawl`, `review_crawl`, or `catalog_refresh` (it does not — already confirmed). Then delete:

- `src/lambda-functions/lambda_functions/crawler/app_crawl.py`
- `src/lambda-functions/lambda_functions/crawler/review_crawl.py`
- `src/lambda-functions/lambda_functions/crawler/catalog_refresh.py`

Also update any `__init__.py` in the crawler package that might re-export these.

---

## Task 2: Create JobRepository

The `api/handler.py` currently has raw SQL for the `analysis_jobs` table. Create:

**`src/library-layer/library_layer/repositories/job_repo.py`**

```python
class JobRepository(BaseRepository):
    def find(self, job_id: str) -> dict | None:
        """SELECT job_id, status, appid FROM analysis_jobs WHERE job_id = %s"""

    def upsert(self, job_id: str, status: str, appid: int) -> None:
        """INSERT INTO analysis_jobs ... ON CONFLICT (job_id) DO UPDATE SET status, appid, updated_at"""
```

Also add `JobRepository` to `repositories/__init__.py`.

---

## Task 3: Add Missing Methods to Existing Repositories

`api/handler.py` needs these queries that don't exist in repos yet. Add them to the appropriate repository:

**`GameRepository`** — add to `game_repo.py`:
```python
def ensure_stub(self, appid: int, name: str | None = None) -> None:
    """INSERT INTO games (appid, name, slug) ... ON CONFLICT DO UPDATE name only — already exists, check first"""

def list_games(
    self,
    genre: str | None = None,
    tag: str | None = None,
    min_reviews: int | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Parameterised query with optional WHERE clauses for genre/tag/search/min_reviews filters.
    Returns appid, name, slug, developer, header_image, review_count, positive_pct, review_score_desc.
    ORDER BY review_count DESC."""

def list_genres(self) -> list[dict]:
    """SELECT gn.id, gn.name, gn.slug, COUNT(gg.appid) AS game_count
       FROM genres gn LEFT JOIN game_genres gg ON gn.id=gg.genre_id
       GROUP BY gn.id, gn.name, gn.slug ORDER BY game_count DESC"""

def list_tags(self, limit: int = 100) -> list[dict]:
    """SELECT t.id, t.name, t.slug, COUNT(gt.appid) AS game_count
       FROM tags t LEFT JOIN game_tags gt ON t.id=gt.tag_id
       GROUP BY t.id, t.name, t.slug ORDER BY game_count DESC LIMIT %s"""
```

Note: `ensure_stub` may already exist on `GameRepository` — check before adding.

---

## Task 4: Refactor api/handler.py

The API handler has these raw SQL functions that need to be replaced with repo calls:

### `_upsert_report(appid, report)` (lines ~58–78)
Replace the inline SQL with:
```python
report_repo.upsert(result)  # ReportRepository already has this
game_repo.ensure_stub(appid)  # GameRepository new method above
```

### `_get_job(job_id)` (lines ~81–93)
Replace with:
```python
job_repo.find(job_id)
```

### `_set_job(job_id, status, appid)` (lines ~95–110)
Replace with:
```python
job_repo.upsert(job_id, status, appid)
```

### `list_games(...)` (lines ~457–510)
Replace dynamic SQL construction with:
```python
game_repo.list_games(genre=genre, tag=tag, min_reviews=min_reviews, search=search, limit=limit, offset=offset)
```

### `list_genres()` (lines ~512–530) and `list_tags()` (lines ~530+)
Replace with:
```python
game_repo.list_genres()
game_repo.list_tags(limit=100)
```

### Wiring the repos in handler.py

At module level (after DB connection), build repos once:

```python
_db_conn = _get_db_conn()  # existing function
if _db_conn:
    _game_repo = GameRepository(_db_conn)
    _report_repo = ReportRepository(_db_conn)
    _job_repo = JobRepository(_db_conn)
else:
    _game_repo = _report_repo = _job_repo = None
```

Pass them into the functions that need them (or close over the module-level variables).

Do NOT change the FastAPI route signatures, response models, or any business logic — only swap out the SQL for repo method calls.

---

## Task 5: Refactor scripts/sp.py

`sp.py` currently opens its own psycopg2 connection and runs raw SQL. Replace with repo/service calls.

### Replace `cmd_catalog_status()` raw SQL
Currently queries `app_catalog` and `reports` with raw SQL. Replace with:
```python
catalog_service.status()  # already returns the counts dict
# for report count: report_repo.count_public() — add this method to ReportRepository if missing
```

Add to `ReportRepository`:
```python
def count_all(self) -> int:
    """SELECT COUNT(*) FROM reports"""
```

### Replace `cmd_game_info(appid)` raw SQL
Currently: `SELECT * FROM games` + `SELECT meta_status, review_status FROM app_catalog`
Replace with:
```python
game = game_repo.find_by_appid(appid)
catalog = catalog_repo.find_by_appid(appid)
```

### Replace `_find_pending_meta()`, `_find_eligible_reviews()`, `_find_ready_for_analysis()` raw SQL
These query `app_catalog` and `reports`. Replace with:
```python
catalog_repo.find_pending_meta(limit=limit)
catalog_repo.find_pending_reviews(limit=limit)
# for ready-for-analysis: games with reviews but no report
```

Add to `CatalogRepository` if missing:
```python
def find_pending_reviews(self, limit: int | None = None) -> list[CatalogEntry]:
    """SELECT from app_catalog WHERE review_status = 'pending'"""
```

### Wiring in sp.py

Build a single shared connection + repos at the top of the file (after imports):

```python
def _get_repos():
    conn = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    from library_layer.repositories.game_repo import GameRepository
    from library_layer.repositories.catalog_repo import CatalogRepository
    from library_layer.repositories.report_repo import ReportRepository
    return conn, GameRepository(conn), CatalogRepository(conn), ReportRepository(conn)
```

The crawl and analysis commands already delegate to services via Lambda invocations or local async calls — those don't need changing.

---

## Task 6: Update Tests

After the deletions and new `job_repo.py`:

1. Delete or replace `tests/test_app_crawler.py` and `tests/test_review_crawler.py` — these tested the old deleted modules. They should be replaced by `tests/handlers/test_crawler_handler.py` (if not already present) that tests the handler via service mocks.

2. Add `tests/repositories/test_job_repo.py`:
   - `test_upsert_and_find` — insert a job, find by id, assert fields
   - `test_upsert_updates_status` — upsert twice, second call updates status
   - `test_find_missing_returns_none`

3. Verify `poetry run pytest` passes after all changes.

---

## Constraints

- Do NOT change repository SQL logic — only add new methods where specified
- Do NOT change any CDK infra or Lambda packaging configs
- Do NOT change Pydantic event models in `events.py`
- Do NOT change route signatures or response shapes in `api/handler.py`
- Do NOT refactor `api/chat.py` — LLM-generated SQL is intentional there
- All new code must pass `ruff check` and `mypy --strict`
- Run `poetry run pytest` after each task before proceeding to the next

---

## Definition of Done

- [ ] `app_crawl.py`, `review_crawl.py`, `catalog_refresh.py` deleted
- [ ] `job_repo.py` created and exported from `repositories/__init__.py`
- [ ] `api/handler.py` has zero raw SQL — all DB access through repos
- [ ] `scripts/sp.py` has zero raw psycopg2 cursor calls — all through repos
- [ ] `poetry run pytest` passes
- [ ] `poetry run ruff check src/ tests/ scripts/` passes
