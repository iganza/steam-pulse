# Smoke test suite: pytest + httpx against live environments

## Context

We currently have a shell script (`scripts/smoketest.sh`) that curls API endpoints
and checks status codes + basic JSON shape. It works but is brittle (string parsing,
no parallelism, limited assertions, can't share fixtures or parametrize).

Replace it with a proper pytest + httpx smoke test suite that runs against any live
environment. This is NOT a unit test or integration test — it hits the real deployed
API over HTTP to verify post-deploy correctness.

## What to do

### 1. Create `tests/smoke/` directory

- `conftest.py` — shared fixtures
- `test_trend_endpoints.py` — all `/api/analytics/trends/*` endpoints
- `test_builder_lens.py` — `/api/analytics/trend-query` + `/api/analytics/metrics`
- `test_game_endpoints.py` — game detail endpoints (`/api/games`, `/api/games/{appid}/*`)
- `test_catalog_endpoints.py` — genres, tags, analytics, developers, publishers
- `test_new_releases.py` — `/api/new-releases/*`
- `test_reports.py` — `/api/reports/*`

### 2. Fixtures (`conftest.py`)

**`base_url`** — read from `SMOKETEST_BASE_URL` env var. Default to prod CloudFront URL.
Skip the entire suite if the env var is set to empty string (opt-out).

**`api`** — a shared `httpx.Client` with `base_url` set, reasonable timeout (10s),
and no redirects. Create once per session (`scope="session"`).

**`well_known_appid`** — a popular game appid known to exist and have a report
(e.g. 440 = Team Fortress 2). Used by game detail tests. Define as a fixture so
it's easy to change.

### 3. Test patterns

Each test should:
- Hit one endpoint with specific params
- Assert HTTP status code
- Assert response JSON has expected top-level keys
- Assert non-empty data where applicable (e.g. `periods` list is not empty)
- For data consistency: assert relationships between fields (e.g. velocity buckets
  sum to total, avg_price_incl_free <= avg_paid_price)

Use `pytest.mark.parametrize` for:
- `game_type` across `["game", "dlc", "all"]` where supported
- `granularity` across `["month", "year"]` for a representative endpoint
- Invalid inputs that should return 400

### 4. Test categories to cover

**Trend endpoints** (port from `smoketest.sh`):
- Each of the 9 trend endpoints returns 200 with periods
- `game_type` dimension: game/dlc/all all return 200
- Invalid game_type returns 400
- Genre filter narrows results
- Tag filter narrows results
- Genre + tag combined returns 400
- Velocity buckets sum to total
- avg_price_incl_free differs from avg_paid_price (free games pull it down)

**Builder lens**:
- Single metric returns periods with that metric key
- Multi metric returns all requested keys
- `type` param flows through
- Unknown metric returns 400
- Empty metrics returns 400
- `/api/analytics/metrics` returns the metric catalog

**Game detail endpoints** (use well_known_appid):
- `/api/games?limit=5` returns games list
- `/api/games/{appid}/report` returns report_json + game metadata
- `/api/games/{appid}/review-stats` returns timeline data
- `/api/games/{appid}/benchmarks` returns benchmark data
- `/api/games/{appid}/audience-overlap` returns 200
- `/api/games/{appid}/playtime-sentiment` returns 200
- `/api/games/{appid}/early-access-impact` returns 200
- `/api/games/{appid}/review-velocity` returns 200
- `/api/games/{appid}/top-reviews` returns 200
- Non-existent appid (e.g. 999999999) returns 404 or empty

**Catalog endpoints**:
- `/api/genres` returns non-empty list
- `/api/tags/top` returns non-empty list
- `/api/tags/grouped` returns 200
- `/api/analytics/price-positioning?genre=action` returns distribution
- `/api/analytics/release-timing?genre=action` returns monthly data
- `/api/analytics/platform-gaps?genre=action` returns platform data
- `/api/tags/{slug}/trend` returns yearly data (use a known tag like "roguelike")
- `/api/developers/{slug}/analytics` returns portfolio (use a known dev)
- `/api/publishers/{slug}/analytics` returns portfolio (use a known pub)

**New releases**:
- `/api/new-releases/released` returns games
- `/api/new-releases/upcoming` returns 200
- `/api/new-releases/added` returns 200

**Reports**:
- `/api/reports?limit=5` returns report list
- `/api/reports/coming-soon` returns 200

### 5. Running

```bash
# Against prod (default)
poetry run pytest tests/smoke/ -v

# Against staging
SMOKETEST_BASE_URL=https://staging.example.com poetry run pytest tests/smoke/ -v

# Against local
SMOKETEST_BASE_URL=http://localhost:8000 poetry run pytest tests/smoke/ -v

# Just trend tests
poetry run pytest tests/smoke/test_trend_endpoints.py -v
```

### 6. pytest configuration

Add a `smoke` marker to `pyproject.toml` so smoke tests can be included/excluded:

```toml
[tool.pytest.ini_options]
markers = ["smoke: live API smoke tests (require network)"]
```

Mark all smoke tests with `@pytest.mark.smoke`. Exclude from default `pytest` runs
by adding `--ignore=tests/smoke` to the default args (or use `-m "not smoke"`), so
`poetry run pytest` doesn't accidentally hit prod. Running smoke tests should be
an explicit opt-in.

### 7. Delete `scripts/smoketest.sh`

Once the pytest suite passes against prod, delete the shell script.

## Verification

1. `SMOKETEST_BASE_URL=https://d1mamturmn55fm.cloudfront.net poetry run pytest tests/smoke/ -v`
2. All tests pass against prod
3. `poetry run pytest` (default) does NOT run smoke tests
4. Delete `scripts/smoketest.sh`
