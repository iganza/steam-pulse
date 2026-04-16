# EA-awareness in the three-phase analyzer

## Context

The three-phase analyzer (`src/library-layer/library_layer/analyzer.py`) currently
processes **all** reviews together — EA-era and post-release are chunked, merged, and
synthesised without phase awareness. Each review row in our `reviews` table carries
`written_during_early_access` (populated from Steam's API at crawl time), but the
analyzer doesn't use it.

Once `split-ea-post-release-reviews.md` lands, the per-game UI will display
post-release review counts / sentiment as the primary headline for post-EA games. The
LLM-generated narrative, however, will still be synthesised from EA-dominated reviews.
For a game like "Project Scrapper" (9 EA, 0 post-release), the headline will read "0
post-release reviews" while the report body describes EA-era playtesters — a
messaging mismatch visible at a glance.

This prompt makes the analyzer phase-aware so the narrative aligns with the
phase-split data.

Related: `sentiment_trend` (`analyzer_models.py`, computed in Python in
`analyzer.py::_compute_sentiment_trend`) is also not phase-aware today — it compares
the latest-N-reviews window to the prior window regardless of whether those windows
straddle the EA→release boundary. For an EA-transition game, that produces a
meaningless delta. Fold that fix into this prompt.

## Scope

Two concrete changes, both scoped to `analyzer.py` and `analyzer_models.py` plus the
report-shaped fields the frontend reads:

1. **Phase-segmented narrative** for games where both EA and post-release reviews
   exist in significant numbers.
2. **Phase-aware `sentiment_trend`** — brackets the window comparison on the
   EA→release boundary rather than blindly comparing N vs N chronological windows.

**Out of scope**: re-architecting chunk/merge to run twice in parallel (once per
phase). The chunk/merge phases stay as-is — every chunk and merged summary carries
phase metadata, and only the synthesis phase branches on it.

## Approach

### 1. Tag chunks with phase

In `analyzer.py::run_chunk_phase`, when building per-chunk review text, pass the
`written_during_early_access` flag through. Each `RichChunkSummary` gains a new field:

```python
# analyzer_models.py
class RichChunkSummary(BaseModel):
    ...
    phase_mix: Literal["ea_only", "post_release_only", "mixed"]
    ea_count: int
    post_release_count: int
```

Computed in Python from the source review rows — not LLM-guessed.

For stratified chunking, stratify by phase in addition to the existing stratification
axis. Simplest: split all reviews into `ea_reviews` and `post_release_reviews` first,
then apply the current stratified-chunker to each separately. Chunks end up
`phase_mix="ea_only"` or `"post_release_only"` with rare edge cases where batch
boundaries cross — label those `"mixed"`.

`chunk_summaries` schema: add `phase_mix TEXT NOT NULL`, `ea_count INTEGER`,
`post_release_count INTEGER`. Migration + `schema.py` mirror. Cache key
`(appid, chunk_hash, prompt_version)` still determines idempotency — reruns pick up
the existing rows.

### 2. Merge phase propagates counts

The merge phase already combines chunk summaries hierarchically. Each `MergedSummary`
gets the same fields:

```python
class MergedSummary(BaseModel):
    ...
    ea_count: int
    post_release_count: int
    phase_mix: Literal["ea_only", "post_release_only", "mixed"]
```

Aggregation is a straight sum of child counts; `phase_mix` is derived
(`ea_count > 0 and post_release_count > 0 → "mixed"`, else the non-zero phase).

### 3. Synthesis branches on phase

`GameReport` gains two optional nested objects in `analyzer_models.py`:

```python
class PhaseReception(BaseModel):
    """Narrative reception for a single phase (EA or post-release)."""
    sample_size: int
    one_liner: str  # max 25 words
    design_strengths: list[str]
    gameplay_friction: list[str]
    technical_issues: list[str]
    # NOT refund_signals/audience_profile/etc — those are cross-phase

class GameReport(BaseModel):
    ...
    # Legacy cross-phase narrative (remains for games with no EA or minimal split):
    one_liner: str
    design_strengths: list[str]
    gameplay_friction: list[str]
    technical_issues: list[str]
    # New — populated only when both phases have sample_size >= 50:
    ea_era_reception: PhaseReception | None = None
    post_release_reception: PhaseReception | None = None
```

Synthesis rule (computed in Python before the LLM call, not prompt-guessed):

| MergedSummary state | Report fields populated |
|---|---|
| `phase_mix=ea_only` or `post_release_count < 50` | Cross-phase fields only (current behaviour) |
| `phase_mix=post_release_only` or `ea_count < 50` | Cross-phase fields only |
| Both phases ≥ 50 reviews | Cross-phase fields (game-wide) **AND** both `*_reception` fields populated via two separate synthesis calls |

The two-phase case runs the synthesis call **twice** — once over only
post-release-derived merged summaries, once over only EA-derived merged summaries.
Because chunks were labelled `ea_only` / `post_release_only` at step 1, selecting the
right subset is a filter on the merge tree. The overall report narrative (cross-phase
one_liner, design_strengths, etc.) is generated from the full merged tree as today.

Threshold of 50 per phase is chosen to match the existing
`sentiment_trend_reliable` threshold. Config: add
`ANALYSIS_PHASE_SPLIT_MIN_SAMPLES: int = 50` to `SteamPulseConfig` (single source per
CLAUDE.md "no defaults in signatures" rule). Thread through `AnalyzerSettings`.

`SYNTHESIS_MAX_TOKENS`: the two extra synthesis calls (when triggered) add cost. For
most games this branch doesn't fire. Add a log field so cost is visible:
`logger.info("synthesis_complete", extra={"calls": 1|3, "appid": ...})`.

### 4. Phase-aware `sentiment_trend`

Currently: `_compute_sentiment_trend` compares positive% across the most-recent 500
reviews vs the prior 500 reviews, chronologically.

New behaviour:
- If the game is pure EA or pure post-release → existing behaviour.
- If the game has crossed the EA→release boundary AND both sides have ≥ 50 reviews →
  the "before" window = last-N EA reviews, the "after" window = first-N
  post-release reviews (ordered by `posted_at`). This directly measures "did
  sentiment shift at launch" instead of a rolling comparison.
- Keep `sentiment_trend_sample_size` and `sentiment_trend_reliable` as before, but
  the `sentiment_trend_note` must state the window basis ("EA-era vs post-release"
  when that branch fires).

`ea_era_reception` and `post_release_reception` objects DO NOT carry a trend — trend
is inherently cross-phase, so it stays on the top-level `GameReport`.

### 5. Frontend hookup

- `frontend/lib/types.ts` — add the two new nested optional objects to `GameReport`.
- Game detail page (`frontend/app/games/[appid]/[slug]/page.tsx`): when either
  reception object is present, render it under a small "Early Access reception" /
  "Post-release reception" subhead beneath the cross-phase narrative.
- No other frontend components need changes — the section rendering loop already
  handles optional fields.

## Files to modify / create

- `src/library-layer/library_layer/models/analyzer_models.py` — `PhaseReception`,
  extend `RichChunkSummary` / `MergedSummary` / `GameReport`
- `src/library-layer/library_layer/analyzer.py` — phase-aware chunk stratification,
  phase-aware synthesis branching, phase-aware `_compute_sentiment_trend`
- `src/library-layer/library_layer/config.py` — `ANALYSIS_PHASE_SPLIT_MIN_SAMPLES`
- `src/library-layer/library_layer/repositories/chunk_summary_repo.py` — new columns
- `src/library-layer/library_layer/repositories/merged_summary_repo.py` — new columns
- `src/library-layer/library_layer/repositories/report_repo.py` — new columns (store
  the two optional reception blobs)
- Migration `00NN_phase_aware_analysis.sql` — adds columns to
  `chunk_summaries` / `merged_summaries` / `reports`
- `scripts/dev/run_phase.py` — surface `phase_mix` counts in phase output (debug)
- `frontend/lib/types.ts` — `PhaseReception` type
- `frontend/app/games/[appid]/[slug]/page.tsx` — render the optional sections
- Tests: `tests/services/test_analyzer_three_phase.py` (phase-mix cases),
  `tests/models/test_analyzer_models.py` (schema),
  `tests/handlers/test_prepare_phase.py`, frontend Playwright update.

## Verification

- Local run on an EA-transition game with sufficient post-release reviews:
  ```
  poetry run python scripts/dev/run_phase.py --appid <post_ea_appid> --phase chunk
  poetry run python scripts/dev/run_phase.py --appid <post_ea_appid> --phase merge
  poetry run python scripts/dev/run_phase.py --appid <post_ea_appid> --phase synthesis
  ```
  Inspect `reports.report_json` — both `ea_era_reception` and
  `post_release_reception` present; `sentiment_trend_note` mentions the phase
  boundary.
- Local run on a pure-EA or pure-post-release game: only cross-phase fields
  populated. No extra LLM calls made.
- Cost check: log line `"synthesis_complete"` shows `calls=1` for single-phase,
  `calls=3` for phase-split games.
- Smoke test: after deploy, hit `/api/games/<post_ea_appid>/report` — assert the new
  optional fields are present or null consistently with the rules.
- Frontend E2E: `frontend/tests/game-report.spec.ts` case for a phase-split game
  asserts both reception subheads render.

## Dependencies

- `split-ea-post-release-reviews.md` must ship first — the
  `has_early_access_reviews` + post-release denormalised columns are used by the
  synthesis branching and by the Python sentiment-trend computation. Also, without
  that prompt, the frontend "0 post-release reviews" mismatch doesn't exist yet and
  this work is premature.
