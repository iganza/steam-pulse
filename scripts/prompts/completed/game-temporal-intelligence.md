# Game Temporal Intelligence — Backend Support

## Background

Knowing *when* a game released unlocks a rich layer of objective signal that the
LLM currently lacks. This feature adds that signal: a lightweight velocity cache
on the `games` table, a computed `GameTemporalContext` dataclass assembled from
**existing** repository methods, and injection into the Pass 2 Sonnet synthesis
prompt.

---

## Information points this unlocks

### From `release_date` alone
- **Game age** — days since release; raw number is useful LLM context
- **Release age bucket** — `new` (<30d), `recent` (30–180d), `established` (180d–2yr),
  `legacy` (>2yr); used in prompts and API responses
- **Lifetime review velocity** — `review_count / days_since_release` = reviews/day
  since launch; distinguishes a "slow burner" from a "flash in the pan"
- **Review acceleration** — is review rate growing, stable, or dying?
  Compare last-30-day rate vs lifetime rate.

### From `coming_soon` + `release_date`
- **Announced but unreleased** — game is in catalog but not yet out; skip analysis

### From `written_during_early_access` reviews
- **Early Access fraction** — % of reviews written before official release
- **EA sentiment delta** — did sentiment improve or worsen post-EA?

### Cross-cutting derived signals (useful for LLM context)
- **Evergreen indicator** — still getting meaningful reviews 2+ years after release
- **Launch trajectory** — "viral" vs "slow build" vs "declining" vs "steady" vs "dead"
- **Velocity trend** — extends existing `find_review_velocity().summary.trend` with a "dead" case

---

## What already exists (reuse — do NOT rebuild)

These repository methods already compute the data this feature needs. Call them;
do not duplicate their SQL.

| Method | File | Returns |
|--------|------|---------|
| `ReviewRepository.find_review_velocity(appid)` | `review_repo.py:325` | `monthly[]`, `summary.avg_monthly`, `summary.last_30_days`, `summary.last_3_months_avg`, `summary.peak_month`, `summary.trend` |
| `ReviewRepository.find_early_access_impact(appid)` | `review_repo.py:259` | `has_ea_reviews`, `early_access.{total, pct_positive}`, `post_launch.{total, pct_positive}`, `impact_delta`, `verdict` |
| `ReviewRepository.find_review_stats(appid)` | `review_repo.py:89` | `review_velocity.reviews_per_day`, `review_velocity.reviews_last_30_days` |

**DB fields already present:** `games.release_date` (DATE), `games.coming_soon` (BOOLEAN),
`reviews.written_during_early_access` (BOOLEAN), `reviews.posted_at` (TIMESTAMPTZ).

**Indexes already present:** `idx_reviews_appid_ea` (appid, written_during_early_access, voted_up),
`idx_reviews_appid_posted` (appid, posted_at).

---

## What to build

### 1. Migration: `0009_game_velocity_cache.sql`

File: `src/lambda-functions/migrations/0009_game_velocity_cache.sql`

Only two columns — for sort/filter in list queries. EA metrics do not need caching
because `find_early_access_impact()` already computes them on the fly and they are
never used for sorting or filtering.

```sql
-- depends: 0008_drop_review_cursor_cols

ALTER TABLE games ADD COLUMN IF NOT EXISTS review_velocity_lifetime NUMERIC(10,2);
ALTER TABLE games ADD COLUMN IF NOT EXISTS last_velocity_computed_at TIMESTAMPTZ;
```

Both nullable (implicit NULL default) — safe for backwards compatibility.

Also update `schema.py`: add the two columns to the `games` CREATE TABLE block
(after `data_source`), per CLAUDE.md migration rules.

### 2. New dataclass + pure classification functions: `models/temporal.py`

Create `src/library-layer/library_layer/models/temporal.py`:

```python
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class GameTemporalContext:
    appid: int
    release_date: date | None
    days_since_release: int | None        # None if coming_soon or no release_date
    release_age_bucket: str | None        # "new"|"recent"|"established"|"legacy"
    is_coming_soon: bool
    has_early_access: bool                # from find_early_access_impact().has_ea_reviews
    ea_fraction: float | None             # ea_total / (ea_total + post_total)
    ea_sentiment_delta: float | None      # from find_early_access_impact().impact_delta
    review_velocity_lifetime: float | None  # reviews/day since release
    review_velocity_last_30d: int         # from find_review_velocity().summary.last_30_days
    velocity_trend: str                   # "accelerating"|"stable"|"decelerating"|"dead"
    is_evergreen: bool                    # >2yr old AND still getting reviews
    launch_trajectory: str                # "viral"|"slow_build"|"steady"|"declining"|"dead"
```

Module-level **pure functions** (not methods) in the same file — easily testable
without a database:

#### `classify_age_bucket(days: int | None) -> str | None`

```
None  → None
< 30  → "new"
< 180 → "recent"
< 730 → "established"
≥ 730 → "legacy"
```

#### `classify_velocity_trend(existing_trend: str, last_30d: int, days_since_release: int | None) -> str`

- If `last_30d == 0` AND `days_since_release is not None` AND `days_since_release > 180` → `"dead"`
- Otherwise return `existing_trend` as-is (`"accelerating"` / `"stable"` / `"decelerating"`)

The `existing_trend` comes from `find_review_velocity().summary.trend` — reuse it,
don't recompute.

#### `classify_trajectory(velocity_lifetime: float | None, last_30d: int, days_since_release: int | None) -> str`

Precedence order:
1. `"viral"` — `velocity_lifetime is not None` AND `velocity_lifetime > 50` AND `days_since_release is not None` AND `days_since_release < 180`
2. `"slow_build"` — `velocity_lifetime is not None` AND `velocity_lifetime > 0` AND `last_30d > velocity_lifetime * 30 * 1.5` AND `days_since_release is not None` AND `days_since_release > 180`
3. `"declining"` — `velocity_lifetime is not None` AND `velocity_lifetime > 0` AND `last_30d < velocity_lifetime * 30 * 0.3` AND `days_since_release is not None` AND `days_since_release > 90`
4. `"dead"` — `last_30d < 1` AND `days_since_release is not None` AND `days_since_release > 365`
5. `"steady"` — default

Note: `velocity_lifetime` is reviews/day, so multiply by 30 when comparing to
`last_30d` (which is a count over 30 days).

#### `check_evergreen(days_since_release: int | None, last_30d: int) -> bool`

`days_since_release is not None` AND `days_since_release > 730` AND `last_30d > 5`

#### `build_temporal_context(game, velocity_data: dict, ea_data: dict) -> GameTemporalContext`

Assembler function. Takes:
- `game` — `Game` model (has `release_date`, `coming_soon`, `review_count_english`)
- `velocity_data` — return value of `find_review_velocity(appid)`
- `ea_data` — return value of `find_early_access_impact(appid)`

Computes `days_since_release` from `game.release_date` and `date.today()`.
Calls the four classification functions above. Assembles and returns the frozen
dataclass. No I/O, no SQL.

For `ea_fraction`: if `ea_data["has_ea_reviews"]` is True, compute
`ea_data["early_access"]["total"] / (ea_data["early_access"]["total"] + ea_data["post_launch"]["total"])`.
Otherwise `None`.

For `ea_sentiment_delta`: use `ea_data["impact_delta"]` directly. `None` if
`ea_data["has_ea_reviews"]` is False.

For `review_velocity_lifetime`: if `days_since_release` and `days_since_release > 0`
and `game.review_count_english`, compute `game.review_count_english / days_since_release`.
Otherwise `None`.

**Why this is NOT a repository method:** Computing age buckets, trajectory, and
evergreen status is business logic. Repositories are pure SQL I/O. The assembler
function takes already-fetched data from existing repo methods — no new SQL needed.

### 3. New method: `GameRepository.update_velocity_cache()`

Add to `src/library-layer/library_layer/repositories/game_repo.py`:

```python
def update_velocity_cache(self, appid: int, velocity_lifetime: float) -> None:
    with self.conn.cursor() as cur:
        cur.execute(
            """UPDATE games
               SET review_velocity_lifetime = %s,
                   last_velocity_computed_at = NOW()
               WHERE appid = %s""",
            (velocity_lifetime, appid),
        )
    self.conn.commit()
```

Pure SQL, no business logic. Only caches the velocity for list-page sort/filter.

### 4. Inject temporal context into LLM analysis

In `src/library-layer/library_layer/analyzer.py`, add an optional `temporal`
parameter that threads through to the synthesis prompt.

**`analyze_reviews()` signature change:**

```python
def analyze_reviews(
    reviews: list[dict],
    game_name: str,
    appid: int | None = None,
    temporal: GameTemporalContext | None = None,
) -> dict:
```

Thread `temporal` through `_synthesize()` → `_build_synthesis_user_message()`.

**Extend the existing `<game_context>` block** (currently at line ~261 in
`_build_synthesis_user_message()`). When `temporal is not None`, append temporal
lines after the existing pre-computed fields:

```
<game_context>
  Game: {game_name}
  Total reviews analyzed: {total_reviews}
  Pre-computed sentiment_score: {sentiment_score} ({overall_sentiment})
  Pre-computed hidden_gem_score: {hidden_gem_score}
  Pre-computed sentiment_trend: {sentiment_trend} ({sentiment_trend_note})
  Released: {temporal.release_date} ({temporal.days_since_release} days ago, {temporal.release_age_bucket})
  Review velocity: {temporal.review_velocity_lifetime:.1f} reviews/day lifetime, {temporal.review_velocity_last_30d} last 30 days ({temporal.velocity_trend})
  Launch trajectory: {temporal.launch_trajectory}
  Early Access: {"Yes — {ea_fraction:.0%} of reviews from EA period, sentiment delta: {ea_sentiment_delta:+.1f}pp" if temporal.has_early_access else "No"}
  Evergreen: {"Yes" if temporal.is_evergreen else "No"}
</game_context>
```

Only add the temporal lines when `temporal is not None`. The existing
pre-computed fields always render.

The LLM should use this to calibrate its analysis — e.g. a "new" game's friction
points may be bugs that will be patched; a "legacy" game's complaints are
structural; a "slow_build" game has a growing community that discovered it late.

### 5. Wire temporal context in the analysis handler

File: `src/lambda-functions/lambda_functions/analysis/handler.py`

This is the **primary integration point**. The handler already has `_review_repo`
and `_game_repo` at module level and loads the game + reviews before calling
`analyze_reviews()`.

Insert between review loading and `analyze_reviews()`:

```python
# Build temporal context from existing repo data
velocity_data = _review_repo.find_review_velocity(req.appid)
ea_data = _review_repo.find_early_access_impact(req.appid)
temporal = build_temporal_context(game, velocity_data, ea_data)
```

Pass `temporal=temporal` to `analyze_reviews()`.

After `_report_repo.upsert(result)`, update the velocity cache:

```python
if temporal.review_velocity_lifetime is not None:
    _game_repo.update_velocity_cache(req.appid, temporal.review_velocity_lifetime)
```

**Why here and not in `CrawlService`:**
- `CrawlService._trigger_analysis()` only starts Step Functions with
  `{"appid": int, "game_name": str}`. Adding temporal context to SFN input would
  require CDK state machine changes and couple crawl-time data to analysis-time needs.
- `CrawlService.ingest_spoke_reviews()` is documented as a pure DB write — no events,
  no analysis trigger. Adding side effects there violates its contract.
- The analysis handler is where all repos are available and where analysis actually runs.
  Fetching temporal data here means it is always fresh at analysis time.

### 6. Expose temporal data in API response

File: `src/lambda-functions/lambda_functions/api/handler.py`

In the `get_game_report()` endpoint (`GET /api/games/{appid}/report`), after loading
the game and report, build temporal context and include it in the response:

```python
from dataclasses import asdict
from library_layer.models.temporal import build_temporal_context

# Inside get_game_report(), when report exists:
velocity_data = _review_repo.find_review_velocity(appid)
ea_data = _review_repo.find_early_access_impact(appid)
temporal = build_temporal_context(game, velocity_data, ea_data) if game else None
temporal_dict = asdict(temporal) if temporal else None

return {"status": "available", "report": report, "game": game_meta, "temporal": temporal_dict}
```

Response shape:

```json
{
  "status": "available",
  "report": { "..." },
  "game": { "..." },
  "temporal": {
    "appid": 440,
    "release_date": "2007-10-10",
    "days_since_release": 6743,
    "release_age_bucket": "legacy",
    "is_coming_soon": false,
    "has_early_access": false,
    "ea_fraction": null,
    "ea_sentiment_delta": null,
    "review_velocity_lifetime": 1.8,
    "review_velocity_last_30d": 42,
    "velocity_trend": "stable",
    "is_evergreen": true,
    "launch_trajectory": "steady"
  }
}
```

The `/api/preview` endpoint does NOT need temporal data (teaser only).
The `/api/validate-key` endpoint is a stubbed payment endpoint — not the report endpoint.

### 7. Tests

Create `tests/models/test_temporal.py` — pure function tests, no database needed.

**`classify_age_bucket`** — parametrize with boundary values:
- `None` → `None`
- `0` → `"new"`, `29` → `"new"`, `30` → `"recent"`, `179` → `"recent"`
- `180` → `"established"`, `729` → `"established"`, `730` → `"legacy"`, `3000` → `"legacy"`

**`classify_velocity_trend`** — parametrize:
- `("accelerating", 0, 200)` → `"dead"` (zero reviews, old game)
- `("decelerating", 0, 100)` → `"decelerating"` (zero reviews but <180d)
- `("accelerating", 5, 100)` → `"accelerating"` (has reviews, pass through)
- `("stable", 10, None)` → `"stable"` (no release date, pass through)

**`classify_trajectory`** — parametrize:
- Viral: `velocity_lifetime=60, last_30d=1800, days=90` → `"viral"`
- Slow build: `velocity_lifetime=2.0, last_30d=120, days=400` → `"slow_build"`
- Declining: `velocity_lifetime=5.0, last_30d=10, days=200` → `"declining"`
- Dead: `velocity_lifetime=0.5, last_30d=0, days=500` → `"dead"`
- Steady: `velocity_lifetime=3.0, last_30d=80, days=300` → `"steady"`

**`check_evergreen`**:
- `(731, 6)` → `True`, `(729, 10)` → `False`, `(800, 4)` → `False`, `(None, 10)` → `False`

**`build_temporal_context`** — integration test with mock `Game` object, mock
`velocity_data` dict, mock `ea_data` dict. Verify the assembled dataclass has
correct derived fields.

Add to `tests/repositories/test_game_repo.py`:
- Test `update_velocity_cache()` — seed a game, call update, verify the cached
  columns are set.

---

## Constraints

- All new code follows Repository -> Service -> Handler layer boundary
- No business logic in repositories — classification lives in `models/temporal.py`
- No new SQL for EA or velocity data — reuse existing `ReviewRepository` methods
- Type hints required on all parameters and return types (Python 3.12)
- `GameTemporalContext` is a frozen dataclass — immutable
- No new Lambda functions — pure backend enrichment
- All tests must pass: `poetry run pytest -v`
- `schema.py` must be updated alongside the migration

---

## Files to create / modify

| File | Action |
|------|--------|
| `src/lambda-functions/migrations/0009_game_velocity_cache.sql` | Create — 2 ALTER TABLE statements |
| `src/library-layer/library_layer/schema.py` | Update — add 2 columns to games block |
| `src/library-layer/library_layer/models/temporal.py` | Create — dataclass + 5 pure functions |
| `src/library-layer/library_layer/repositories/game_repo.py` | Add `update_velocity_cache()` |
| `src/library-layer/library_layer/analyzer.py` | Add `temporal` param, extend `<game_context>` |
| `src/lambda-functions/lambda_functions/analysis/handler.py` | Fetch temporal context, pass to analyzer, update cache |
| `src/lambda-functions/lambda_functions/api/handler.py` | Add `temporal` key to `/api/games/{appid}/report` |
| `tests/models/test_temporal.py` | Create — parametrized pure function tests |
| `tests/repositories/test_game_repo.py` | Add `update_velocity_cache()` test |
