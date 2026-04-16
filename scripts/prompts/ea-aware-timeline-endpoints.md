# EA-aware sentiment/playtime/velocity timeline endpoints

## Context

These three per-game endpoints aggregate rows from the `reviews` table without
filtering by EA phase:

- `GET /api/games/{appid}/review-stats` — weekly sentiment timeline + playtime
  buckets + velocity (`ReviewRepository.find_review_stats`,
  `src/library-layer/library_layer/repositories/review_repo.py`)
- `GET /api/games/{appid}/review-velocity` — monthly review volume trend
  (`ReviewRepository.find_review_velocity`)
- `GET /api/games/{appid}/playtime-sentiment` — fine-grained playtime × sentiment
  + churn wall (`ReviewRepository.find_playtime_sentiment`)

For a game that has transitioned from EA to full release, the timeline spans the
EA→release boundary with no visual or data marker. A spike in negative reviews at
launch is indistinguishable from organic post-release sentiment; a playtime
distribution mixes EA-era playtesters (different audience) with post-release buyers.

Once `split-ea-post-release-reviews.md` reframes the headline around post-release
counts, these timeline charts become the visible mismatch — the hero number says "0
post-release reviews" while the timeline shows a full history with no indication that
the history is entirely EA.

## Scope

Two concrete changes per endpoint:

1. **Optional `?phase=` query parameter** — `all` (default, current behaviour), `ea`,
   `post_release`. Repositories accept a phase filter that pushes the predicate into
   the SQL `WHERE` clause.
2. **Release-boundary marker** — every response that returns a timeline also returns
   `release_date` (ISO-8601 date) and `has_early_access_reviews` at the top level.
   Frontend renders a vertical line at `release_date` on timeline charts when
   `has_early_access_reviews = TRUE`.

The phase filter is a thin parameterisation; no new matview is needed because
`reviews` already has a partial index on `(appid, written_during_early_access)` (per
`analytics-engine-backend.md`, used by `find_early_access_impact`). These per-game
endpoints are small-scoped by `appid` — the existing index is sufficient.

## Approach

### 1. Repository layer

Pattern for each of `find_review_stats`, `find_review_velocity`,
`find_playtime_sentiment`:

```python
from typing import Literal
ReviewPhase = Literal["all", "ea", "post_release"]

def find_review_stats(self, appid: int, *, phase: ReviewPhase) -> dict:
    phase_sql = {
        "all": "",
        "ea": " AND written_during_early_access = TRUE",
        "post_release": " AND written_during_early_access = FALSE",
    }[phase]
    # Splice into the existing WHERE clauses that filter by appid.
    ...
```

**Do not** reach for dynamic SQL composition helpers — the predicate is one of three
static strings. No SQL injection risk (the param is a `Literal`). Keep the other
existing WHERE clauses (e.g. `posted_at >= g.release_date` in `find_review_stats`)
unchanged.

### 2. API layer

In `src/lambda-functions/lambda_functions/api/handler.py`:

```python
@app.get("/api/games/{appid}/review-stats")
async def review_stats(appid: int, phase: ReviewPhase = "all") -> JSONResponse:
    game = _game_repo.find_by_appid(appid)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    stats = _review_repo.find_review_stats(appid, phase=phase)
    body = {
        **stats,
        "release_date": game.release_date.isoformat() if game.release_date else None,
        "has_early_access_reviews": game.has_early_access_reviews,
        "phase": phase,
    }
    return JSONResponse(body, headers=CACHE_HEADERS)
```

Same shape for the other two endpoints. `CACHE_HEADERS`: phase-split responses can
stay at the existing cache duration (phase selection is stable given the data).

### 3. Frontend

- `frontend/lib/types.ts` — extend the three response types with `phase`,
  `release_date`, `has_early_access_reviews`.
- Components that render these charts (search `frontend/components` for
  `review-stats` / `review-velocity` / `playtime-sentiment` / `TopReviews`,
  `EarlyAccessImpact`, `SentimentTimeline`, `PlaytimeSentiment`):
  - Add a phase toggle (`[All | Early Access | Post-release]`) — visible only when
    `has_early_access_reviews = TRUE` on the initial response. For pure-post-release
    and pre-EA games the toggle is hidden (single-phase).
  - Render a vertical reference line at `release_date` when
    `has_early_access_reviews = TRUE` and the current phase is `all`. Most charting
    primitives already support a reference-line layer.
  - Default phase is `all` (Steam-like). Selection is a local state, not a URL query
    param — keeps shareable URLs stable.

### 4. Tests

- `tests/repositories/test_review_repo.py` — one existing test per method; add a
  parametrised case that seeds EA + post-release reviews and asserts each phase
  filter returns the right subset.
- `tests/smoke/test_game_endpoints.py` — one new parametrised smoke test per
  endpoint:
  ```python
  @pytest.mark.parametrize("phase", ["all", "ea", "post_release"])
  def test_review_stats_phase(appid_with_ea_history, phase): ...
  ```
  Assertions only need to verify shape + `phase` echo + presence of `release_date` /
  `has_early_access_reviews` — not sentiment equality across phases (that belongs in
  the repository test).
- Frontend Playwright: one spec that loads a post-EA game's detail page, toggles the
  phase selector, asserts the timeline re-fetches, asserts the boundary line is
  present in `all` mode.

## Files to modify

- `src/library-layer/library_layer/repositories/review_repo.py` — three methods
  gain `phase: ReviewPhase` keyword
- `src/lambda-functions/lambda_functions/api/handler.py` — three endpoints accept
  `phase` + surface `release_date` / `has_early_access_reviews`
- `frontend/lib/types.ts`
- Timeline components under `frontend/components/analytics/` /
  `frontend/components/game/` — phase toggle + boundary line
- `tests/repositories/test_review_repo.py`
- `tests/smoke/test_game_endpoints.py`
- One Playwright spec

## Out of scope

- Multi-appid aggregates. This prompt covers per-game timelines only; genre/tag
  aggregates are in `phase-aware-genre-tag-aggregates.md`.
- Analyzer narrative changes. Narrative phase-awareness is in `analyzer-ea-awareness.md`.

## Verification

- `poetry run pytest tests/repositories/test_review_repo.py -k phase -v`
- `SMOKETEST_BASE_URL=https://staging.steampulse.io poetry run pytest tests/smoke/test_game_endpoints.py -v`
- Manually hit a post-EA game on staging with
  `?phase=post_release` — confirm response contains only post-release-derived rows.
- Frontend: load a post-EA game detail, toggle phase, visually confirm timeline
  filters; in `all` mode confirm the boundary line appears at `release_date`.

## Dependencies

- `split-ea-post-release-reviews.md` must ship first (adds
  `has_early_access_reviews` to the `Game` response — this prompt relies on that
  flag to gate the phase toggle).
