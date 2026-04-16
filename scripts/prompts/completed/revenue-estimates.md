# Revenue Estimates (Boxleiter v1)

Add Boxleiter-ratio-based owner and gross revenue estimates to every analyzed game as a **Pro-only** signal. One of two primary Compare-lens conversion triggers (the other being Promise Gap).

## Background

Indie dev users want to know "how much did this game make?" The public answer is the Boxleiter / VG Insights ratio: review count is a strong linear proxy for unit sales, with a multiplier that varies by genre, age, and price tier. VG Insights and Gamalytic already run full revenue dashboards on this methodology — our edge is **bundling the estimate inline with the qualitative report**, not out-dashboarding them.

See `20260331091542-projects_steam_pulse_game_analysis_talks.org` for the strategic framing (sections on "review velocity as sales proxy" and Pro feature list).

Nothing exists today: no estimate columns, no helper service, no API surface. This prompt delivers the full slice.

## Key Decision — Denormalize on `games`, not `index_insights`

Put `estimated_owners` and `estimated_revenue_usd` directly on the `games` row. Rationale:

- We want to **sort, filter, and aggregate by revenue** in `/api/games`, price-positioning analytics, Compare lens, and eventual Market Map. That's trivial as columns, painful as `index_insights` JSON lookups.
- `index_insights` is for *aggregate* pre-computations (genre-level distributions, etc.). Per-game scalars belong on the row.
- Matview-friendly: existing analytics matviews can join/include revenue without schema gymnastics.

Method is versioned via a `revenue_estimate_method` text column (e.g. `"boxleiter_v1"`) so we can bump the algorithm and backfill without schema churn.

## Methodology

**Boxleiter ratio:** `estimated_owners = review_count × multiplier`, where multiplier is genre-, age-, and price-adjusted. `estimated_revenue_usd = estimated_owners × price_usd`. This is **gross revenue pre-Steam-cut** — a ceiling, not what the dev took home. Every user-facing surface must say so.

**Base multipliers** (genre → multiplier). These are v1 rough cuts sourced from public Boxleiter/VG Insights writeups and the original Boxleiter GDC talk; cite the sources in a comment at the top of the constant:

| Genre bucket              | Multiplier |
|---------------------------|------------|
| Mainstream / high-profile | 20         |
| Indie (default)           | 30         |
| Strategy / simulation     | 50         |
| Niche (VN, hardcore sim)  | 70         |

**Adjustments:**

- **Age decay:** for games older than 3 years, dampen the multiplier ~15% (older games accumulate reviews slowly relative to sales, so the raw ratio overshoots).
- **Price tier:** sub-$5 games review at higher rates per sale — shave ~20% off the multiplier. Free-to-play → no estimate.
- **Review floor:** if `review_count < 50`, return `None` with `reason="insufficient_reviews"`. Don't publish noise.
- **Excluded types:** DLC, demos, tools, music — return `None` with a `reason`.

**Confidence caveat:** treat every number as ±50%. Surface this prominently on the frontend.

## Codebase Orientation

Existing pieces to reuse:

- `src/library-layer/library_layer/models/game.py` — `Game` pydantic model. Extend with optional fields (defaults to None for backwards compat per CLAUDE.md rule on events/models).
- `src/library-layer/library_layer/schema.py` — human-readable schema reference, must be kept in sync with migrations.
- `src/library-layer/library_layer/services/analysis_service.py` — already runs once per analyzed game; piggyback here rather than creating a new Lambda.
- `src/library-layer/library_layer/repositories/game_repo.py` — add an `update_revenue_estimate` method following existing update patterns.
- `src/lambda-functions/migrations/` — current highest migration is `0025`; new file is `0026`.

## Implementation

### 1. Migration — `src/lambda-functions/migrations/0026_add_revenue_estimates.sql`

```sql
-- depends: 0025_add_trend_matview_indexes

ALTER TABLE games ADD COLUMN IF NOT EXISTS estimated_owners BIGINT;
ALTER TABLE games ADD COLUMN IF NOT EXISTS estimated_revenue_usd NUMERIC(14,2);
ALTER TABLE games ADD COLUMN IF NOT EXISTS revenue_estimate_method TEXT;
ALTER TABLE games ADD COLUMN IF NOT EXISTS revenue_estimate_computed_at TIMESTAMPTZ;
```

Index only if we ship revenue sorting in `/api/games` v1:

```sql
-- transactional: false
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_games_estimated_revenue
    ON games(estimated_revenue_usd DESC NULLS LAST);
```

Update `schema.py` to mirror the new columns in the `games` CREATE TABLE block.

### 2. Service — `src/library-layer/library_layer/services/revenue_estimator.py`

Pure-Python, no SQL, no LLM. Pydantic result model:

```python
class RevenueEstimate(BaseModel):
    estimated_owners: int | None = None
    estimated_revenue_usd: Decimal | None = None
    method: str = "boxleiter_v1"
    reason: str | None = None  # populated when estimate is None
```

Single public function:

```python
def compute_estimate(
    game: Game,
    genres: list[dict],
    tags: list[dict],
) -> RevenueEstimate: ...
```

Genres and tags are passed in (not derived from `Game`) because the `Game`
model doesn't denormalize them. Callers must fetch them via
`TagRepository.find_genres_for_game(appid)` and `find_tags_for_game(appid)`
(or the `find_*_for_appids` bulk helpers in hot loops).

Contains the `GENRE_MULTIPLIERS` constant with a source-citation comment, the age/price/floor adjustments, and excluded-type guards. Extend `models/game.py` with:

```python
estimated_owners: int | None = None
estimated_revenue_usd: Decimal | None = None
revenue_estimate_method: str | None = None
revenue_estimate_computed_at: datetime | None = None
```

### 3. Repository — `GameRepository.update_revenue_estimate`

```python
def update_revenue_estimate(
    self,
    appid: int,
    owners: int | None,
    revenue_usd: Decimal | None,
    method: str | None,
) -> None:
```

Single `UPDATE games SET ... WHERE appid = %s` with `revenue_estimate_computed_at = NOW()`. Match the style of existing update methods in `game_repo.py`. When both `owners` and `revenue_usd` are None (free-to-play, excluded type, insufficient reviews), the repo must coerce `method` to NULL so downstream clients can treat NULL as "no estimate available".

### 4. Wire into analysis

`AnalysisService` takes a `TagRepository` as a required constructor dependency
(it doesn't have one today — add it). At the end of the analyze path (after the
`GameReport` is persisted, alongside the `last_analyzed` update), fetch
genres/tags and call the estimator:

```python
genres = self._tag_repo.find_genres_for_game(appid)
tags = self._tag_repo.find_tags_for_game(appid)
estimate = compute_estimate(game, genres, tags)
self._game_repo.update_revenue_estimate(
    appid=game.appid,
    owners=estimate.estimated_owners,
    revenue_usd=estimate.estimated_revenue_usd,
    method=estimate.method,
)
```

The real production analyze path is `lambda_functions/batch_analysis/process_results.py`,
not the deprecated real-time `AnalysisService`. In `process_results`, collect the
successful appids during the per-record loop and run a single bulk revenue-estimate
pass *after* the loop using `TagRepository.find_genres_for_appids` /
`find_tags_for_appids` to avoid N+1 lookups across large batches. Use the
lightweight `GameRepository.find_for_revenue_estimate(appid)` (no `app_catalog`
LEFT JOIN) in that hot loop.

No new Lambda, no new Step Functions state, no new queue. Every game analyzed from today onward gets an estimate. Method bumps are handled by a one-off backfill script (follow-up).

### 5. API surface

All additive, no new endpoints:

- `GET /api/games/{appid}/report` — include `estimated_owners`, `estimated_revenue_usd`, `revenue_estimate_method` in the response when non-null.
- `GET /api/games` — include the two estimate fields in list items; add optional `sort=revenue_desc` query param.
- `GET /api/analytics/price-positioning` — add per-price-bucket revenue quartiles alongside existing sentiment metrics.

**Backend returns unconditionally**. Pro-gating is frontend-only per CLAUDE.md architectural decision #3.

### 6. Frontend surfaces (gating deferred to `pro-gating.md`)

Describe the shape here; the actual `usePro()` blur/lock wrapper is delivered by prompt #10.

- **Game report page** — new "Market Reach" card: estimated owners, estimated gross revenue (USD), method badge, `±50% confidence` caveat in small print.
- **Compare lens** — new row in the side-by-side metrics table.
- **Market Map lens** (Phase 2B) — revenue distribution histogram; out of scope for this prompt, list as future consumer.

Every surface MUST display the confidence caveat and the word "gross" alongside the revenue number.

## Free vs Pro

| Surface                       | Free              | Pro              |
|-------------------------------|-------------------|------------------|
| Game report "Market Reach"    | Blurred + CTA     | Full numbers     |
| `/api/games` list revenue col | Blurred + CTA     | Full numbers     |
| Compare lens revenue row      | Locked (Compare is already Pro-only) | Full numbers |
| Price-positioning quartiles   | Blurred + CTA     | Full numbers     |

## Testing

- `tests/services/test_revenue_estimator.py` (new) — table-driven unit tests:
  - Known inputs → expected multiplier (per genre)
  - Free-to-play → None with reason
  - DLC / demo / tool → None with reason
  - `review_count < 50` → None with `insufficient_reviews`
  - Missing price → None with reason
  - Old game → decayed multiplier
  - Sub-$5 → shaved multiplier
- `tests/repositories/test_game_repo.py` — extend for `update_revenue_estimate`, run against `steampulse_test` DB.
- `tests/handlers/` — extend report handler test: fields present when non-null, omitted cleanly when null.

## Non-Goals (v1)

- No net revenue (Steam cut, refunds, regional pricing) — gross only.
- No confidence intervals in the response payload — a single "±50%" caveat in UI copy.
- No historical revenue time series.
- No new Lambda, SFN state, or background job.
- No per-region or per-currency estimates.
- No re-analysis of already-analyzed games as part of this prompt (follow-up).

## Follow-ups

- One-off backfill script (`scripts/backfill_revenue_estimates.py`) for existing analyzed games — runs `compute_estimate` over all rows where `revenue_estimate_method IS NULL` or doesn't match current version.
- Refine `GENRE_MULTIPLIERS` once we have user feedback and can spot-check against public revenue disclosures (Hades, Stardew Valley, Vampire Survivors interviews).
- Eventual move to a small regression model trained on the known-revenue anchor set — bump method to `boxleiter_v2`.
- Market Map lens revenue distribution viz (Phase 2B consumer).
