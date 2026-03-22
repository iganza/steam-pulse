# SteamPulse Test Coverage Prompt — Ready to Go

## What This Investigation Found

The SteamPulse codebase has **3 new data-driven insights API endpoints** but **NO tests** for them.

### New Endpoints (Need Tests)
1. **GET `/api/games/{appid}/review-stats`** — sentiment timeline + playtime distribution + review velocity
2. **GET `/api/games/{appid}/benchmarks`** — percentile rankings vs. cohort
3. **Enhanced GET `/api/games/{appid}/report`** — now includes genres/tags

### New Repository Methods
- `ReviewRepository.find_review_stats(appid)` 
- `GameRepository.find_benchmarks(appid, genre, year, price, is_free)`
- `GameRepository.list_games()` enhanced with sentiment/price_tier filters

---

## How to Use This Investigation

1. **Read INVESTIGATION_SUMMARY.md** (8.5 KB, ~5 min read)
   - Quick overview of all endpoints
   - Test gaps identified
   - Test patterns to follow

2. **Reference steampulse_complete.txt** (25 KB) when writing tests
   - Complete SQL for each method
   - Expected JSON response schemas
   - Edge cases to cover
   - Fixture setup details

3. **Copy test patterns from existing tests:**
   - **API tests:** `tests/test_api.py` (mock-based pattern)
   - **Repo tests:** `tests/repositories/test_game_repo.py` (real DB pattern)
   - **Fixtures:** `tests/conftest.py` (core infrastructure)

---

## Test Cases to Generate (~35-40 tests)

### Unit Tests (Repository Layer)

**ReviewRepository.find_review_stats() [6-8 tests]**
- Happy path: Multiple weeks with varying positive/negative ratios
- Playtime buckets: All 6 buckets present and correctly calculated
- Review velocity: Correct calculation of reviews_per_day and last_30_days
- Edge case: No reviews → empty timeline/buckets, velocity = 0
- Edge case: NULL posted_at → excluded from timeline
- Percentage calculations → all values 0-100

**GameRepository.find_benchmarks() [7-10 tests]**
- Happy path: Game with cohort → percentiles 0.0-1.0
- No genre metadata → returns all NULLs
- Cohort too small → cohort_size = 0, ranks = NULL
- Price fuzzy match → ±50-200% range
- Genre/year/price all filter correctly
- PERCENT_RANK correctness (best vs. worst games)
- Ties in rankings (same sentiment_score)

**GameRepository.list_games() filters [5-7 tests]**
- sentiment="positive" filters on score ≥0.65
- sentiment="mixed" filters on 0.45 ≤ score < 0.65
- sentiment="negative" filters on score < 0.45
- price_tier="free" filters is_free=TRUE
- price_tier combos work (under_10, 10_to_20, over_20)
- Combined filters (genre + sentiment + year)
- Sorting still works with filters

### Integration Tests (API Layer)

**GET /api/games/{appid}/review-stats [4-5 tests]**
- Happy path: Returns proper JSON structure
- Empty game: No reviews → empty timeline/buckets
- Response validation: weeks are ISO dates, percentages are 0-100
- Boundary conditions: Exactly 1 review, exactly 1 week
- Large dataset: 1000+ reviews spanning months

**GET /api/games/{appid}/benchmarks [4-5 tests]**
- Happy path: Percentiles and cohort_size returned
- No cohort: Returns 404 or cohort_size=0, ranks=null
- Percentile validation: All values 0.0-1.0
- Rank interpretation: Can explain if game is top/bottom
- Missing metadata: Graceful null return

**Enhanced GET /api/games/{appid}/report [3-4 tests]**
- Genres array present and correctly populated
- Tags array present, sorted by votes DESC
- Empty genres/tags: Return [] not null
- 404 when game not found
- Report status (available vs. not_available) still works

**GET /api/games with filters [3-4 tests]**
- sentiment filters independent
- price_tier filters independent
- Combined filters (AND logic)
- Pagination works with filters
- Sorting options still work

---

## Key Files for Reference

| File | Purpose | Lines |
|------|---------|-------|
| `src/lambda-functions/lambda_functions/api/handler.py` | All 11 endpoints | 469 |
| `src/library-layer/library_layer/repositories/review_repo.py` | find_review_stats + CRUD | 144 |
| `src/library-layer/library_layer/repositories/game_repo.py` | find_benchmarks + list_games | 338 |
| `tests/conftest.py` | Core fixtures (db_conn, repos) | 172 |
| `tests/test_api.py` | API test pattern (mock-based) | 146 |
| `tests/repositories/test_game_repo.py` | Repo test pattern (real DB) | 109 |
| `tests/repositories/test_review_repo.py` | Example CRUD tests | 108 |

---

## Test Data Factories Needed

```python
# For review_stats tests
def _seed_game(game_repo, appid=440):
    """Create a game with all required fields"""
    game_repo.upsert({
        "appid": appid,
        "name": "...",
        # ... 20+ fields
    })

def _make_reviews(appid=440, count=3, spread_weeks=None):
    """Create reviews across time/playtime"""
    # If spread_weeks=4: spread over 4 weeks
    # Returns list of review dicts

# For benchmarks tests
def _seed_cohort(game_repo, tag_repo, genre="Action", year=2022, count=10):
    """Seed a cohort of games for ranking"""
    # Creates games with varying positive_pct, review_count
    # All in same genre, year, price tier
```

---

## Prompt Template for Claude Code

```
Using the SteamPulse codebase investigation report, generate comprehensive
unit and integration tests for the 3 new data-driven insights endpoints:

1. ReviewRepository.find_review_stats(appid: int)
   - Test patterns from: tests/repositories/test_review_repo.py
   - Use real DB via db_conn fixture
   - Include data factories similar to _make_reviews()

2. GameRepository.find_benchmarks(...) and list_games(..., sentiment, price_tier)
   - Test patterns from: tests/repositories/test_game_repo.py
   - Use real DB via db_conn fixture
   - Create _seed_cohort() factory for benchmarks tests

3. API endpoints for all above
   - Test patterns from: tests/test_api.py
   - Use reset_api_state fixture for mocked repos
   - Use TestClient for FastAPI simulation

REQUIREMENTS:
- Follow existing pytest patterns (conftest.py fixtures)
- Include edge cases and error handling
- Type hints in Python 3.10+ style
- Docstrings for each test
- Expected output: 35-40 tests, ~700-900 lines

REFERENCE:
- For SQL logic: see steampulse_complete.txt (Section 2)
- For response schemas: see INVESTIGATION_SUMMARY.md
- For test patterns: see existing tests in repositories/ and test_api.py
```

---

## How to Run Tests After Generation

```bash
# All tests
pytest tests/

# Just the new tests
pytest tests/repositories/test_review_repo.py::test_find_review_stats_*
pytest tests/repositories/test_game_repo.py::test_find_benchmarks_*
pytest tests/test_api.py::test_review_stats_*

# With coverage
pytest --cov=library_layer tests/
```

---

## Files Saved in Project

- ✅ `INVESTIGATION_SUMMARY.md` — Quick reference (~5 min read)
- ✅ `steampulse_complete.txt` — Comprehensive reference (~700 lines)
- ✅ `TEST_PROMPT_READY.md` — This file

All located in: `/Users/iganza/dev/git/saas/steam-pulse/`

---

✅ **Investigation complete. Ready to generate tests with Claude Code.**
