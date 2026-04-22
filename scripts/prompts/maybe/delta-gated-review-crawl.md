
> **Status: possibly-do-later.** The immediate "stop the bleeding" step
> is just removing the scheduled `RefreshReviewsRule` from
> `infra/stacks/compute_stack.py` — no replacement needed while the
> RDB wedge (141 games, operator-triggered review refresh) is the only
> analysis workload. Revisit this prompt when product decisions put
> review-derived freshness back on the table for non-wedge games, or
> when expanding to a second genre wedge.

## Goal

Replace the blanket scheduled review-refresh (cost: ~17M review-row
writes, RDS `t4g.small` CPU credit exhaustion, ~$35-$125/mo upgrade
pressure) with a demand-driven dispatch: during metadata refresh,
compare new vs old `review_count_english` and only crawl reviews for
games that actually grew. Keeps `t4g.small` viable indefinitely at
current wedge scope and beyond.

## Problem

Today's architecture has two independent hourly schedulers — metadata
and reviews — both walking the catalog by tier. The review scheduler
re-fetches ~20k games every few days regardless of whether the games
gained any reviews, generating millions of row writes for data nothing
reads.

But the metadata scheduler **already asks Steam the question we need**:
Steam's metadata response includes `total_positive` + `total_negative`
(English review counts) on every refresh. We write those to the `games`
row today. The delta between old and new is free to compute and is the
exact signal for "should we re-crawl reviews?"

The plumbing is 80% there already:

- `RefreshMetaRule` in `infra/stacks/compute_stack.py:853` fires
  hourly, tiered by `review_count` via `find_due_meta`
  (`src/library-layer/library_layer/repositories/catalog_repo.py:79-147`).
- `steam_source.py:346-382` returns `total_positive` / `total_negative`
  / `total_reviews`; `crawl_service.py:314` computes the English
  count as positive + negative.
- `crawl_service._ingest_app_data` at line 262 loads the
  pre-upsert row for comparison purposes — and already uses the
  old/new review count for milestone SNS events at lines 514-526.
  Delta-for-review-crawl is the same pattern, one block over.
- `CatalogService.enqueue_refresh_reviews(appids=[...])` can be
  called from anywhere (no scheduler coupling).

Missing: (a) the actual delta check + dispatch call inside the
metadata ingest, (b) deletion of the now-redundant `RefreshReviewsRule`
scheduler, (c) a thundering-herd mitigation for enable-time.

## Changes

### 1. Delete `RefreshReviewsRule`

`infra/stacks/compute_stack.py:872-889` — remove the EventBridge rule
entirely. Also remove any matching assertion in
`tests/infra/test_compute_stack.py`.

Keep the `refresh_reviews` action handler and `find_due_reviews` repo
method intact as operator-triggered fallbacks (e.g., wedge backfill
via `sp.py`).

### 2. Add delta-gated dispatch inside metadata ingest

`src/library-layer/library_layer/services/crawl_service.py`,
`_ingest_app_data` — add, adjacent to the existing milestone block
(lines 514-526):

```python
old_english = (existing.review_count_english if existing else 0) or 0
new_english = (total_positive or 0) + (total_negative or 0)
delta = new_english - old_english

if delta >= threshold_for_tier(review_count):
    # Single-appid review crawl. Early-stop in the ingest handler
    # ensures we only fetch pages covering the delta, not full history.
    self._catalog_service.enqueue_refresh_reviews(appids=[appid])
```

Per-tier delta thresholds (initial values — tune with observation):

| Tier (by `review_count`) | Threshold |
|--------------------------|-----------|
| S: ≥10,000               | 10        |
| A: ≥1,000                | 25        |
| B: ≥50                   | 50        |
| C: <50                   | — (never) |

Tier buckets should match `find_due_meta` so the tier definition lives
in one place. Move thresholds to `library_layer/config.py` so they're
tunable without a redeploy.

Alternative design — single relative threshold
(`delta / max(old_english, 1) >= 0.02`, i.e. 2% growth). Simpler,
self-scaling. Downside: small Tier-B games trip on +2 reviews which
is noisy. Start with absolute per-tier thresholds.

### 3. Thundering-herd mitigation (enable-time)

If we just flip this on cold, every game's first metadata pass
observes a giant delta accumulated over the paused-scheduler window
and dispatches a review crawl for basically every active game at once
— recreating the incident this change is meant to prevent.

Pick one of the mitigations:

**A. Baseline seed** (preferred — fully deterministic).
Before enabling, run a one-shot `scripts/seed_review_english_baseline.py`
that UPDATEs `games.review_count_english` to Steam's
current-reported value for every Tier S/A/B game, *without*
dispatching review crawls. Then enable. First post-enable metadata
refresh compares Steam's next snapshot vs. the seeded baseline, so
only genuine post-enable growth trips the threshold.

**B. Enable-time grace window** (cheaper, slightly fuzzy).
Guard the dispatch with `AND (review_crawled_at IS NULL OR
review_crawled_at > <enable_time>)` for the first 72h. Relies on
the existing tiered metadata cadence smoothing out the first-pass
burst, but during peak hours Tier-S games all cycle at once and can
still herd.

Prefer A.

### 4. Wedge-game seeding (separate, one-off, first)

For the 141 RDB wedge games, reviews *are* about to be consumed by
the analysis pipeline. Before enabling delta-gating, run
`sp.py refresh-reviews` manually for the wedge list (uses the existing
`refresh_reviews` action handler). Confirm the queue drains cleanly
under current `t4g.small` + `batch_size=40` + `max_concurrency=12`
Lambda settings. Then enable delta-gating for everyone else.

### 5. Tests

- Handler / service tests for the two branches:
  `delta ≥ threshold → enqueue_refresh_reviews called`
  `delta < threshold → no dispatch`
- Per-tier threshold dispatch tests (Tier S 10-review cutoff, etc.).
- Ensure the existing metadata-ingest integration test still passes
  (only an added side effect, not a behavior change on the metadata
  write itself).

## Load estimate (steady-state)

Review-crawl dispatches per hour under delta-gating + tiered metadata:

- Tier S (~500 games, daily metadata, ~80% active growth, threshold 10): ~17/hr
- Tier A (~5k games, weekly metadata, ~30% with delta ≥25): ~9/hr
- Tier B (~15k games, monthly metadata, ~10% with delta ≥50): ~2/hr
- **Total: ~28 review-crawl dispatches/hour ≈ 650/day**

Each dispatch expands to ~1-2 ingest messages thanks to early-stop
(`ingest_handler.py:261-265` halts when batch min-timestamp predates
`reviews_completed_at`). Average ~300 reviews/dispatch once steady
state. **~200k review-row writes/day ≈ 2-3 writes/sec sustained.**

`t4g.small` at baseline CPU (even with 0 credits) handles 2-3
writes/sec sitting on its hands. CPU credits rebuild during quiet
periods and stay healthy.

## Files to modify

- `infra/stacks/compute_stack.py` — delete `RefreshReviewsRule`.
- `tests/infra/test_compute_stack.py` — remove matching assertion.
- `src/library-layer/library_layer/services/crawl_service.py` — delta
  + dispatch in `_ingest_app_data`.
- `src/library-layer/library_layer/config.py` — per-tier thresholds as
  tunables.
- `scripts/seed_review_english_baseline.py` (new, one-shot, delete
  after run).
- Handler/service tests.

## Out of scope

- **RDS upgrade** — parked in `scripts/prompts/upgrade-rds-instance-class.md`.
  Not needed for steady-state delta-gated load.
- **Commit-boundary refactor** — separate
  (`scripts/prompts/commit-boundary-ownership.md`).
- **Tag crawl** — orthogonal, separately broken upstream.
- **Deleting existing `reviews` rows** — storage is cheap, keep.

## Verification

1. **Local**:
   ```
   poetry run pytest tests/infra/ tests/handlers/ tests/services/
   ```

2. **Staging**:
   - Deploy the delete + delta-gated change to staging.
   - Run the baseline seed script against staging DB.
   - Wait one metadata refresh cycle; confirm review crawls dispatch
     only for games with Steam-reported growth.
   - Confirm staging RDS handles the load without credit drain.

3. **Production**:
   - Seed baseline first (manual step).
   - Run `sp.py refresh-reviews` for 141 wedge games; wait for drain.
   - Deploy the delta-gated change.
   - Monitor `spoke_results_queue` depth (should stay <200 and flatten)
     and RDS `CPUCreditBalance` (should stay well positive, trend up
     during off-hours).
