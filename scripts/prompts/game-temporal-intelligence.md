# Game Temporal Intelligence — Backend Support

## Background

Knowing *when* a game was added to Steam's catalog and *when* it released unlocks
a rich layer of objective signal that the LLM currently lacks. This prompt adds
that signal to the backend: stored fields, computed properties, and LLM context
injection.

---

## Information points this unlocks

### From `release_date` alone
- **Game age** — days/months/years since release; raw number is useful LLM context
- **Release age bucket** — `new` (<30d), `recent` (30–180d), `established` (180d–2yr),
  `legacy` (>2yr); used in prompts and API filters
- **Release year/quarter** — trend analysis, genre benchmarking by cohort
- **Lifetime review velocity** — `review_count / days_since_release` = reviews/day
  since launch; distinguishes a "slow burner" from a "flash in the pan"
- **Review acceleration** — is review rate growing, stable, or dying?
  Compare last-30-day rate vs lifetime rate.
- **Dead game signal** — `days_since_release > 365` AND `reviews_last_90d < 10`

### From `coming_soon` + `release_date`
- **Announced but unreleased** — game is in catalog but not yet out; skip analysis
- **Days until release** — useful for upcoming game pages

### From `written_during_early_access` reviews
- **Early Access fraction** — % of reviews written before official release
- **EA sentiment delta** — did sentiment improve or worsen post-EA?
  (`positive_pct` of EA reviews vs post-release reviews)
- **EA duration proxy** — earliest review `posted_at` to `release_date` =
  approximate EA window (imprecise but directionally correct)
- **EA exit effect** — spike or drop in review velocity around release_date?

### Cross-cutting derived signals (useful for LLM context)
- **Review density** — `review_count / game_age_days`; high density on old game
  = sustained community; high density on new game = viral launch
- **Honeymoon effect** — unusually high positive rate in first 30 days that
  normalises later (common in hyped launches)
- **Comeback signal** — review velocity was dying then spiked = patch/content update
  brought players back
- **Evergreen indicator** — still getting meaningful reviews 2+ years after release
- **Launch trajectory** — "slow build" vs "big launch, trails off" vs "steady"

---

## What to build

### 1. New columns on `games` table (migration)

Add to `migrations/` as a new numbered migration:

```sql
ALTER TABLE games ADD COLUMN IF NOT EXISTS review_velocity_lifetime NUMERIC(10,2);
ALTER TABLE games ADD COLUMN IF NOT EXISTS ea_review_fraction NUMERIC(5,2);
ALTER TABLE games ADD COLUMN IF NOT EXISTS ea_sentiment_delta NUMERIC(5,1);
ALTER TABLE games ADD COLUMN IF NOT EXISTS last_velocity_computed_at TIMESTAMPTZ;
```

`review_velocity_lifetime` = total English reviews / days since release (computed,
cached here so it can be sorted/filtered without a join). Recomputed whenever
reviews are ingested.

`ea_review_fraction` = fraction of reviews written during early access (0.0–1.0).
`ea_sentiment_delta` = (post-EA positive_pct) - (EA positive_pct). Positive = game
improved after leaving EA. Null if game had no EA.

### 2. New dataclass: `GameTemporalContext`

Create `src/library-layer/library_layer/models/temporal.py`:

```python
@dataclass(frozen=True)
class GameTemporalContext:
    appid: int
    release_date: date | None
    days_since_release: int | None        # None if coming_soon or no release_date
    release_age_bucket: str | None        # "new"|"recent"|"established"|"legacy"
    is_coming_soon: bool
    is_early_access: bool                 # has genre_id=70 currently
    ea_fraction: float | None            # fraction of reviews written during EA
    ea_sentiment_delta: float | None     # post-EA positive_pct minus EA positive_pct
    review_velocity_lifetime: float | None  # reviews/day since release
    review_velocity_last_30d: float      # reviews in last 30 days
    velocity_trend: str                  # "accelerating"|"stable"|"decelerating"|"dead"
    is_evergreen: bool                   # >2yr old AND still getting reviews (>5/mo avg)
    launch_trajectory: str              # "viral"|"slow_build"|"steady"|"declining"|"dead"
```

`release_age_bucket` rules:
- `"new"` — days_since_release < 30
- `"recent"` — 30 ≤ days < 180
- `"established"` — 180 ≤ days < 730
- `"legacy"` — days ≥ 730

`launch_trajectory` rules (in order of precedence):
- `"viral"` — velocity_lifetime > 50/day AND release_age_bucket in ("new","recent")
- `"slow_build"` — velocity_last_30d > velocity_lifetime * 1.5 AND age > 180d
- `"declining"` — velocity_last_30d < velocity_lifetime * 0.3 AND age > 90d
- `"dead"` — velocity_last_30d < 1 AND days_since_release > 365
- `"steady"` — default

`velocity_trend` rules:
- Use the existing `find_review_velocity()` result's `summary.trend` field
  (`"accelerating"` / `"stable"` / `"decelerating"`)
- Add `"dead"` case: `last_30_days == 0 AND days_since_release > 180`

`is_evergreen`:
- `days_since_release > 730` AND `review_velocity_last_30d > 5`

### 3. New method: `GameRepository.get_temporal_context(appid)`

Add to `src/library-layer/library_layer/repositories/game_repo.py`:

```python
def get_temporal_context(self, appid: int) -> GameTemporalContext | None:
```

Single SQL query joining `games`, `game_genres` (to check genre_id=70 for EA),
and a subquery for review counts. Compute all derived fields in Python (not SQL)
for testability. Return `None` if game not found.

Key SQL: use `CURRENT_DATE - release_date` for days_since_release (integer).
For `ea_fraction` and `ea_sentiment_delta`, query `reviews` table:
```sql
SELECT
    COUNT(*) FILTER (WHERE written_during_early_access) AS ea_count,
    COUNT(*) FILTER (WHERE NOT written_during_early_access) AS post_count,
    ROUND(AVG(CASE WHEN written_during_early_access AND voted_up THEN 100.0 ELSE
              CASE WHEN written_during_early_access THEN 0.0 END END), 1) AS ea_pct,
    ROUND(AVG(CASE WHEN NOT written_during_early_access AND voted_up THEN 100.0 ELSE
              CASE WHEN NOT written_during_early_access THEN 0.0 END END), 1) AS post_pct
FROM reviews WHERE appid = %s
```

### 4. New method: `GameRepository.update_velocity_cache(appid, velocity, ea_fraction, ea_sentiment_delta)`

After review ingest completes, call this to cache the computed values.
Called from `CrawlService.ingest_spoke_reviews()` after the upsert.

### 5. Inject temporal context into LLM analysis

In `src/library-layer/library_layer/analyzer.py`, add temporal context to the
Pass 2 (Sonnet synthesis) prompt. Add a new `temporal_context` parameter to
`analyze_reviews()`:

```python
def analyze_reviews(
    self,
    game_name: str,
    appid: int,
    reviews: list[dict],
    temporal: GameTemporalContext | None = None,
) -> dict:
```

In the Sonnet synthesis prompt, inject a `<game_context>` block before the review
signals:

```
<game_context>
Game: {game_name} (appid: {appid})
Released: {release_date} ({days_since_release} days ago — {release_age_bucket})
Review velocity: {review_velocity_lifetime:.1f} reviews/day lifetime, {review_velocity_last_30d:.1f} last 30 days ({velocity_trend})
Launch trajectory: {launch_trajectory}
Early Access: {"Yes — {ea_fraction:.0%} of reviews from EA period, sentiment delta: {ea_sentiment_delta:+.0f}pp post-EA" if is_early_access else "No"}
Evergreen: {"Yes" if is_evergreen else "No"}
</game_context>
```

Only include the block if `temporal is not None`. The LLM should use this to
calibrate its analysis — e.g. a "new" game's friction points may be bugs that will
be patched; a "legacy" game's complaints are structural; a "slow_build" game has a
growing community that discovered it late.

### 6. Wire temporal context into `CrawlService.trigger_analysis()`

In `src/library-layer/library_layer/services/crawl_service.py`, before calling
`analyze_reviews()`, fetch `GameRepository.get_temporal_context(appid)` and pass
it through.

### 7. Expose temporal fields in API response

In `src/lambda-functions/lambda_functions/api/handler.py`, the `/api/validate-key`
endpoint returns the full report. Add a `temporal` key to the response:

```json
{
  "report": { ... },
  "temporal": {
    "days_since_release": 487,
    "release_age_bucket": "established",
    "review_velocity_lifetime": 12.3,
    "review_velocity_last_30d": 8.1,
    "velocity_trend": "decelerating",
    "launch_trajectory": "declining",
    "is_early_access": false,
    "ea_fraction": null,
    "ea_sentiment_delta": null,
    "is_evergreen": false
  }
}
```

The `/api/preview` endpoint does NOT need temporal data (it's a teaser only).

---

## Constraints

- All new methods follow the Repository → Service → Handler layer boundary
- No business logic in repositories — `GameTemporalContext` fields are computed
  in Python after the SQL fetch, not in SQL
- Type hints required on all parameters and return types (Python 3.12)
- `GameTemporalContext` is a frozen dataclass — immutable
- No new Lambda functions — this is pure backend enrichment
- All tests must pass: `poetry run pytest -v`
- Add unit tests for all `release_age_bucket`, `launch_trajectory`, and
  `velocity_trend` classification logic — these are pure functions, easy to test
- New migration file: `migrations/0007_game_velocity_cache.sql`
  (number may need adjusting depending on current highest migration number)

---

## Files to create / modify

| File | Action |
|------|--------|
| `migrations/0007_game_velocity_cache.sql` | Create — new columns |
| `src/library-layer/library_layer/models/temporal.py` | Create — GameTemporalContext dataclass |
| `src/library-layer/library_layer/repositories/game_repo.py` | Add `get_temporal_context()`, `update_velocity_cache()` |
| `src/library-layer/library_layer/services/crawl_service.py` | Call `update_velocity_cache()` after review ingest |
| `src/library-layer/library_layer/analyzer.py` | Add `temporal` param, inject `<game_context>` block |
| `src/library-layer/library_layer/services/crawl_service.py` | Fetch and pass temporal context to `trigger_analysis()` |
| `src/lambda-functions/lambda_functions/api/handler.py` | Add `temporal` key to full report response |
| `tests/` | Unit tests for classification logic |
