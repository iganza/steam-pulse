# SteamPulse Data-Driven Insights — Investigation Summary

## Quick Overview

**3 new endpoints added:**
1. `GET /api/games/{appid}/review-stats` — Timeline + playtime distribution + velocity
2. `GET /api/games/{appid}/benchmarks` — Percentile rankings vs. cohort
3. Enhanced `GET /api/games/{appid}/report` — Now includes genres/tags

**Status:** Implementation complete, but **NO TESTS exist yet** for these endpoints.

---

## 1. All 11 API Endpoints

### Existing (8)
- `GET /health` — Health check
- `POST /api/preview` — Trigger/fetch analysis (user-facing)
- `POST /api/validate-key` — License validation (legacy, always grants access now)
- `GET /api/status/{job_id}` — Poll async job
- `POST /api/analyze` — Admin-only trigger with force flag
- `GET /api/games` — Browse catalog with facets
- `GET /api/genres` — Genre list with counts
- `GET /api/tags/top` — Top tags with counts
- `POST /api/chat` — Pro feature: AI chat

### New (3) ⭐
- `GET /api/games/{appid}/review-stats`
- `GET /api/games/{appid}/benchmarks`
- Enhanced `GET /api/games/{appid}/report`

### Enhanced Endpoints
- `GET /api/games` — NEW filters: `sentiment` (positive|mixed|negative), `price_tier` (free|under_10|10_to_20|over_20)

---

## 2. New Repository Methods

### ReviewRepository
```python
find_review_stats(appid: int) -> dict
```
**SQL:** Two GROUP BY queries
- **Timeline:** `DATE_TRUNC('week', posted_at)` → weeks with total, positive, pct_positive
- **Playtime Buckets:** CASE statement → 6 buckets (0h, <2h, 2-10h, 10-50h, 50-200h, 200h+)
- **Velocity:** reviews_per_day, reviews_last_30_days (calculated in Python)

**Response:**
```json
{
  "timeline": [{"week": "2025-01-20", "total": 150, "positive": 120, "pct_positive": 80}],
  "playtime_buckets": [{"bucket": "0h", "reviews": 50, "pct_positive": 75}],
  "review_velocity": {"reviews_per_day": 2.3, "reviews_last_30_days": 45}
}
```

### GameRepository
```python
find_benchmarks(appid, genre, year, price, is_free) -> dict
```
**SQL:** CTE with PERCENT_RANK() window functions
- **Cohort:** Same genre + release year + price tier (±50-200% fuzzy match)
- **Ranking:** PERCENT_RANK() on positive_pct and review_count
- **Requirements:** All cohort games need review_count > 50

**Response:**
```json
{
  "sentiment_rank": 0.75,
  "popularity_rank": 0.85,
  "cohort_size": 145
}
```

```python
list_games(..., sentiment, price_tier, ...) -> dict
```
**New filters:**
- `sentiment` → Filters on `report_json->>'sentiment_score'` (≥0.65=positive, 0.45-0.64=mixed, <0.45=negative)
- `price_tier` → Filters on `price_usd` and `is_free`

### TagRepository (Already exists, used by report endpoint)
```python
find_genres_for_game(appid) -> list[dict]    # Returns genres for a game
find_tags_for_game(appid) -> list[dict]      # Returns user tags for a game
```

---

## 3. Test Files & Fixtures

**Location:** `/Users/iganza/dev/git/saas/steam-pulse/tests/`

### Core Infrastructure (conftest.py)
- **Session fixture:** `db_conn` — Real PostgreSQL, auto-creates schema, auto-truncates
- **Autouse:** `clean_tables` — Smart truncation (only if test uses db_conn)
- **Repository fixtures:** `game_repo`, `review_repo`, `report_repo`, `tag_repo`, `job_repo`
- **AWS mocks:** `sqs_client`, `mock_queues`, `sfn_client` (via moto)
- **Steam API fixtures:** `steam_appdetails_440`, `steam_reviews_440` (JSON files)

### Test Files
| File | Tests | Missing |
|------|-------|---------|
| `test_api.py` | 5 basic API tests | ❌ review-stats, benchmarks, enhanced report |
| `repositories/test_game_repo.py` | 8 CRUD tests | ❌ find_benchmarks, list_games filters |
| `repositories/test_review_repo.py` | 5 CRUD tests | ❌ find_review_stats |
| `repositories/test_tag_repo.py` | 5 tests | ✓ (already covers find_genres/find_tags) |
| `repositories/test_report_repo.py` | CRUD tests | - |
| `repositories/test_catalog_repo.py` | - | - |
| `repositories/test_job_repo.py` | - | - |

---

## 4. Test Patterns & Mocking

### API Testing Pattern (test_api.py)
```python
# In-memory repo mocks injected at module level
@pytest.fixture(autouse=True)
def reset_api_state():
    import lambda_functions.api.handler as api_module
    api_module._report_repo = _MemReportRepo()  # In-memory store
    api_module._game_repo = _MemGameRepo()
    api_module._job_repo = _MemJobRepo()

@pytest.fixture
def client():
    from lambda_functions.api.handler import app
    return TestClient(app)

# Use like:
def test_endpoint(client):
    resp = client.get("/api/games")
    assert resp.status_code == 200
```

### Repository Testing Pattern (test_game_repo.py, test_review_repo.py)
```python
# Data factory
def _game_data(appid: int = 440) -> dict:
    return {"appid": appid, "name": "...", ...all_fields...}

def _make_reviews(appid: int = 440, count: int = 3) -> list[dict]:
    return [{"appid": appid, "steam_review_id": f"rev-{i}", ...}]

# Test with real DB
def test_something(game_repo: GameRepository):
    game_repo.upsert(_game_data())
    game = game_repo.find_by_appid(440)
    assert game is not None
```

### Database Cleanup
```python
# Before each test, truncate all tables (smart: only if test uses db_conn)
@pytest.fixture(autouse=True)
def clean_tables(request):
    if "db_conn" not in request.fixturenames:
        yield
        return
    conn = request.getfixturevalue("db_conn")
    with conn.cursor() as cur:
        cur.execute("""
            TRUNCATE games, reviews, tags, game_tags, genres, game_genres,
                     game_categories, reports, app_catalog, rate_limits,
                     analysis_jobs, game_relations, index_insights
            RESTART IDENTITY CASCADE
        """)
    conn.commit()
    yield
```

---

## 5. Critical Testing Gaps ⚠️

### Missing Unit Tests

#### ReviewRepository.find_review_stats()
- [ ] Happy path: Multiple weeks + playtime buckets
- [ ] Edge case: No reviews
- [ ] Edge case: NULL posted_at values
- [ ] Velocity calculation correctness
- [ ] Percentage calculations (0-100)

#### GameRepository.find_benchmarks()
- [ ] Happy path: Game in cohort with peers
- [ ] Edge case: Game not in cohort (return NULLs)
- [ ] Edge case: Cohort has < 2 games
- [ ] Percentile ranking correctness (0.0-1.0)
- [ ] Price tier fuzzy matching (±50-200%)

#### GameRepository.list_games() with filters
- [ ] sentiment="positive" (score ≥0.65)
- [ ] sentiment="mixed" (score 0.45-0.64)
- [ ] sentiment="negative" (score <0.45)
- [ ] price_tier="free", "under_10", "10_to_20", "over_20"
- [ ] Combined filters (genre + sentiment + year)

### Missing Integration Tests (API)

#### GET /api/games/{appid}/review-stats
- [ ] Happy path with timeline + buckets
- [ ] Empty game (no reviews)
- [ ] Response JSON structure validation
- [ ] Percentage ranges (0-100)
- [ ] Date format (ISO YYYY-MM-DD)

#### GET /api/games/{appid}/benchmarks
- [ ] Happy path with percentiles
- [ ] No cohort scenario
- [ ] Missing metadata scenario
- [ ] Percentile range validation (0.0-1.0)

#### Enhanced GET /api/games/{appid}/report
- [ ] genres array present
- [ ] tags array present and sorted by votes
- [ ] Empty genres/tags arrays (not null)
- [ ] 404 when game not found
- [ ] not_available status without report

#### GET /api/games with filters
- [ ] sentiment filters work independently
- [ ] price_tier filters work independently
- [ ] Combined filters (intersection logic)
- [ ] Sorting still works with filters
- [ ] Pagination works with filters

---

## 6. New Files & Infrastructure

**New SQL Table:** `index_insights` (defined in schema.py, currently unused)
- Designed for pre-computed insight caching
- Can store pre-computed timeline, benchmark cohorts, etc.

**No new service files yet** — all logic in repositories

**Schema Tables Used:**
- `reviews` (posted_at, voted_up, playtime_hours, appid)
- `games` (positive_pct, review_count, release_date, price_usd, is_free)
- `genres` / `game_genres` (cohort filtering by genre)

---

## 7. Ready for Claude Code Prompt

You now have everything needed to write an effective test coverage prompt:

1. **Context:** This entire document
2. **Unit tests to generate:** ~20 tests (6-8 per new method)
3. **Integration tests to generate:** ~15 tests (3-5 per endpoint)
4. **Follow patterns:** Use fixtures from conftest.py, data factories, real DB
5. **Expected output:** ~35-40 tests, ~700-900 lines of code

**Key instruction for Claude:**
> "Use the existing test patterns in test_api.py (mock-based) and test_game_repo.py (real DB). Create data factories like _game_data() for test data. For API tests, use reset_api_state fixture. For repo tests, use db_conn fixture. Include edge cases, error handling, and comprehensive assertions."

