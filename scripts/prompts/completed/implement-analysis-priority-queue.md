# Implement Analysis Candidate List

## Background

SteamPulse has ~28,700 games eligible for analysis (type=game, not
coming_soon, 200+ reviews) and only 10 have reports. We need a simple,
ordered list of games to feed into the batch fan-out orchestrator for
the initial bulk analysis run.

Smart prioritization (user voting, staleness tiers, change detection)
is a follow-up. This prompt produces the **initial backfill list** and
the infrastructure to serve it.

### Numbers

```
10k+ reviews:   1,883 games
1k-10k:         6,627 games
200-1k:       ~17,000 games
```

### Why 200 minimum

The chunk phase stratifies 50-review chunks. A game with 50 reviews
produces one chunk — no cross-validation, no merge phase synthesis
across reviewer segments. At 200 reviews you get 4 chunks, enough for
the merge phase to find real patterns. Below 200 the analysis quality
is too thin to be useful, and the 47k games in the 10-100 range would
dominate the backlog for marginal value.

---

## Goal

Create a materialized view that produces an ordered list of games
needing analysis. The dispatch mechanism reads this view and feeds
appid batches into the fan-out orchestrator. Dispatch is manual only
(CLI) — no EventBridge schedule until we have paying users to justify
the token spend.

**Ordering strategy: review count DESC.**

The most-reviewed games go first because:

1. **Highest traffic.** These are the games users will search for.
   Analyzing Counter-Strike before a 2026 game with 15 reviews means
   the site has useful content for the pages that get the most visits.
2. **Best analysis quality.** More reviews = richer data for the LLM.
   A game with 50,000 reviews produces a far better report than one
   with 12.
3. **Simplest to reason about.** No weights, no tiers, no scoring
   formula. Just `ORDER BY review_count DESC`.

This means the 1,883 games with 10k+ reviews go first (~day 1-2),
then the 6,627 with 1k-10k (~days 3-5), then 20k with 100-1k, and
finally the long tail.

---

## Architecture

```
mv_analysis_candidates (matview)
  │
  │  ordered list of appids needing analysis
  ▼
dispatch_batch Lambda (EventBridge schedule OR manual)
  │
  │  {"appids": [top N from matview]}
  ▼
Fan-Out Orchestrator (from implement-batch-fan-out-layer.md)
  │
  │  DistributedMap, MaxConcurrency=20
  ▼
Per-Game State Machine (existing)
```

---

## Files to Create

### `migrations/0037_analysis_candidates.sql`

```sql
-- depends: 0036_merged_summaries

DROP MATERIALIZED VIEW IF EXISTS mv_analysis_candidates;

CREATE MATERIALIZED VIEW mv_analysis_candidates AS
SELECT
    g.appid,
    g.name AS game_name,
    g.slug,
    g.developer,
    g.header_image,
    g.review_count,
    g.positive_pct,
    g.review_score_desc,
    g.release_date,
    g.estimated_revenue_usd
FROM games g
LEFT JOIN reports r ON r.appid = g.appid
WHERE g.type = 'game'
  AND g.coming_soon = FALSE
  AND g.review_count >= 200
  AND r.appid IS NULL;

CREATE UNIQUE INDEX mv_analysis_candidates_pk
    ON mv_analysis_candidates(appid);
CREATE INDEX mv_analysis_candidates_review_count_idx
    ON mv_analysis_candidates(review_count DESC);
```

**Implementation notes (deviations from original design):**

- **No `pipeline_version` filter.** The original design hardcoded the
  pipeline version string in the matview DDL, requiring a new migration
  on every prompt change. For the initial backfill nearly every game is
  unanalyzed, so `r.appid IS NULL` covers the use case. Version-based
  re-analysis is a follow-up concern.
- **No report columns** (`last_analyzed`, `report_pipeline_version`,
  `reviews_analyzed`, `never_analyzed`). These are unnecessary — every
  row in the matview is by definition unanalyzed (`r.appid IS NULL`).
- **Added `slug` and `developer`** to support the future catalog
  discovery page UI (game card links need slug, cards show developer).
- **`header_image`** not `header_image_url` — matches the actual
  column name in the `games` table.
- **No `ORDER BY` in matview DDL.** Postgres does not guarantee row
  order from a matview regardless. A btree index on `(review_count DESC)`
  makes the dispatch query's `ORDER BY ... LIMIT` fast instead.

### `lambda_functions/batch_analysis/dispatch_batch.py`

Lambda that reads from the matview and starts the fan-out orchestrator.
Invoked by EventBridge on a schedule, or manually via the CLI.

```python
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    """Read top-priority candidates and start a fan-out execution.

    Input (all optional):
        {
            "batch_size": 100,     # override default from config
            "dry_run": true        # return candidates without starting
        }

    Steps:
        1. SELECT appid FROM mv_analysis_candidates
           ORDER BY review_count DESC LIMIT batch_size
        2. If dry_run, return the list.
        3. Start the fan-out orchestrator with {"appids": [...]}.
        4. Return execution ARN + game count.
    """
```

The query is trivial — the matview is already ordered by review_count
DESC. Just `SELECT appid ... LIMIT N`.

**Deduplication:** If the orchestrator is already running with some of
these appids, that's fine. The per-game state machine's chunk cache
makes redundant analysis a no-op (cache hit on chunk_hash → skip).
No need for a lock table or in-flight tracking.

### `tests/handlers/test_dispatch_batch.py`

- Mock the matview query and `sfn.start_execution`.
- Test: returns top N appids ordered by review_count.
- Test: dry_run returns candidates without starting execution.
- Test: empty matview → no execution started, clean return.
- Test: batch_size override works.

---

## Files to Modify

### `schema.py`

Add the `mv_analysis_candidates` DDL to `MATERIALIZED_VIEWS` and the
drop-before-rebuild list in `create_matviews()`.

### `matview_repo.py`

Add `"mv_analysis_candidates"` to `MATVIEW_NAMES`. This means the
matview refreshes:
- After each report is upserted (via `ReportReadyEvent` → matview
  refresh handler). The just-analyzed game drops out of the candidate
  list.
- Every 6 hours via EventBridge fallback.

As games get analyzed, the matview shrinks. The dispatch Lambda always
reads the current top-N, so it naturally progresses through the backlog.

### `batch_analysis_stack.py`

Add:
1. **`dispatch_batch` Lambda** — same VPC, `batch_lambda_role` (needs
   DB access to read the matview + `states:StartExecution` on the
   orchestrator). Short timeout (30s).
No EventBridge schedule — dispatch is manual via CLI only.

```python
dispatch_fn = _make_batch_fn(
    "DispatchBatchFn",
    "lambda_functions/batch_analysis/dispatch_batch.py",
    "dispatch-batch",
)

# Grant permission to start the orchestrator
orchestrator.grant_start_execution(dispatch_fn)
```

### `config.py`

Add:
```python
BATCH_DISPATCH_SIZE: int = 100           # games per orchestrator execution
ANALYSIS_MIN_REVIEW_COUNT: int = 200     # minimum reviews for analysis eligibility
```

### `scripts/sp.py`

Add a `dispatch` subcommand:

```bash
# Dispatch next batch from the candidate list
poetry run python scripts/sp.py dispatch --env staging

# Dry run — show what would be dispatched
poetry run python scripts/sp.py dispatch --env staging --dry-run

# Override batch size
poetry run python scripts/sp.py dispatch --env staging --batch-size 50
```

This calls the dispatch Lambda (or reads the matview directly and
starts the orchestrator — either approach works for a CLI tool).

---

## How Backfill Progresses

```
Run 1:  poetry run python scripts/sp.py dispatch --env staging
        → dispatches top 100 from matview → orchestrator runs them
        → ~100 reports created
        → matview refresh drops those 100 games from the list

Run 2:  same command → next 100 games (now starting 1k-10k tier)
        ...repeat as needed
```

Each manual dispatch processes 100 games (configurable via
`--batch-size`). Run it as often as budget allows. The 1,883
most-reviewed games finish in ~19 dispatches.

---

## Future Enhancements (separate prompts)

These are deliberately out of scope. Noted here so the current design
doesn't preclude them:

- **Staleness-based re-analysis** — games accumulate new reviews over
  time. Extend the matview WHERE clause to include games whose
  `review_count` has grown significantly since `reviews_analyzed`.
- **User voting** — `analysis_requests` table, API endpoints, UI
  queue page. Votes boost priority above pure review_count ordering.
- **Tiered priority** — version-stale games (Tier 0), user-requested
  (Tier 1), change-driven refresh (Tier 2), routine refresh (Tier 3),
  backfill (Tier 4). Batch composition rules prevent starvation.
- **Pipeline version as a function** — avoid hardcoding in the matview
  DDL by using a Postgres function `current_pipeline_version()` that
  the matview references.
- **Cost budgeting** — cap daily/weekly token spend.

---

## Acceptance Criteria

1. `mv_analysis_candidates` contains all eligible games (200+ reviews)
   without current reports, ordered by `review_count DESC`.

2. After a game is analyzed and its report upserted, the next matview
   refresh drops it from the candidate list.

3. `dispatch_batch` Lambda reads top N candidates, starts the fan-out
   orchestrator, and returns the execution ARN.

4. `dispatch_batch` with `dry_run=true` returns the candidate list
   without starting an execution.

5. `poetry run python scripts/sp.py dispatch --env staging --dry-run`
   shows the next batch of candidates.

6. No EventBridge rules or scheduled triggers are created.

7. Per-game state machine, PreparePhase, CollectPhase, CheckBatchStatus
   — all unchanged.

8. All existing 485+ tests pass. Ruff clean.
