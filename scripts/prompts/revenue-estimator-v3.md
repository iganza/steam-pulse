# Revenue Estimator v3 — small-game floor, scaled confidence, display honesty

## Problem

Revenue estimates look absurd for small games because the Boxleiter ratio is
calibrated on hits. Two real problems surfaced while auditing individual
report pages:

1. **No calibration data below ~10k reviews.** The v2 validation set (see
   `scripts/prompts/completed/revenue-estimator-v2.md`) bottoms out at
   Victoria 3 / 16k reviews. Nightmare Frontier (appid 3310950) has 203
   all-language reviews, and the current algorithm renders ~6,948 owners /
   ~$205K — defensible arithmetic against a 30x base, but the base itself
   doesn't apply at that scale. Every public estimator (SteamSpy, SteamDB,
   VG Insights) over-estimates small indie games; SteamSpy's own FAQ warns
   the estimate is unreliable below ~10,000 units sold.

2. **Display disconnect drives the "that's crazy!" reaction.** The Reviews
   tile in `QuickStats.tsx` shows `review_count_english` (93 for Nightmare
   Frontier, 4,186 for Cossacks 3). The estimator uses the all-language
   `review_count` (203 and 15,794 respectively). Users doing mental math
   see "93 reviews → 9,900 owners" and it looks ridiculous, when the
   actual ratio is 203 → 9,900 (≈48x, in range of research).

A third, secondary problem from the previous v2 ship: `METHOD_VERSION` was
kept as `"boxleiter_v1"` across two algorithm rewrites, so the backfill's
`--only-stale` filter (`revenue_estimate_method IS DISTINCT FROM
METHOD_VERSION`) has been a silent no-op. Stale rows from the pre-2026-04-10
50x-multiplier era are still in the DB.

## Research summary (2025–2026)

Consensus on the review-to-sales multiplier for **established** games:

| Source | Multiplier | Calibration floor |
|---|---|---|
| VG Insights | ~30x recent | 10k+ reviews |
| GameDiscoverCo NB (Carless, 2025) | ~63x avg, 20–60x by tier | 237 dev-reported actuals |
| steam-revenue-calculator | 30x / 50x / 70x | Flat |
| Jake Birkett (2018) | 80x | Pre-review-prompt era |
| SteamSpy (self-documented) | ~33x (3% review rate) | Unreliable below ~10k units |

Key additional findings:
- Early Access games have **lower** review rates than released games
  (empirical Steam EA study) — pushes the multiplier *up*, not down.
- SteamDB/SteamSpy **overestimate small indie games by ~150%**
  (developer-reported accuracy on smaller catalogs).
- Our v2 estimate for Cossacks 3 (667K owners) is ~27% *under* SteamDB's
  914K estimate — the mature-game algorithm is already conservative.

**Conclusion:** the 30x base is fine. The algorithm breaks at the low end
because there's no ground truth below ~1k reviews, not because the
multiplier is wrong.

## Goals

1. Stop rendering estimates below a defensible sample-size floor.
2. Widen the confidence band for games in the "small sample" zone so the
   ±50% label isn't a lie.
3. Fix the display disconnect so the review count users see matches the
   review count the estimator used.
4. Bump `METHOD_VERSION` so the stale filter finally catches old rows.
5. Keep the algorithm shape — do **not** retune the base multiplier or
   any of the five signal factors. That's a separate exercise and needs
   ground-truth data we don't have.

## Decision — threshold and tier shape

**Review floor: 500 all-language reviews.** Below this, return
`reason="insufficient_reviews"` and render the empty state.
- 10,000 was considered and rejected — it would suppress estimates for
  ~90% of the catalog.
- 1,000 (SteamSpy's self-documented threshold) is defensible but kills
  most indie EA games, including much of the roguelike-deckbuilder wedge.
- 500 matches the current algorithm's own `_review_count_factor`
  tier boundary, keeps coverage for the wedge, and removes the worst
  offenders (sub-300-review games).

**Confidence tiers** (by all-language review count):

| Reviews | Band | Label in UI |
|---|---|---|
| < 500 | (no estimate) | "Not enough reviews yet (N/500)" |
| 500–4,999 | **±100%** | "Small-sample estimate" |
| 5,000–49,999 | ±60% | (no extra label) |
| ≥ 50,000 | ±40% | (no extra label) |

No changes to `_review_count_factor` or any other signal function —
risk of re-miscalibration outweighs the benefit without new data.

## Files to change

### 1. `src/library-layer/library_layer/services/revenue_estimator.py`
- Change `_REVIEW_FLOOR = 50` → `_REVIEW_FLOOR = 500`.
- Change `METHOD_VERSION = "boxleiter_v1"` → `METHOD_VERSION = "boxleiter_v2"`.
- No other changes. Signal factors, base multiplier, and exclusion logic
  stay as-is.

### 2. `tests/services/test_revenue_estimator.py`
- Update the `insufficient_reviews` test to use 499 (currently 49).
- Update any fixture that used 50–499 reviews to use ≥500 OR move it to
  the `insufficient_reviews` branch.
- Update `METHOD_VERSION` assertions if any are literal-string.

### 3. `frontend/components/game/MarketReach.tsx`
- Replace `const CONFIDENCE = 0.5;` with a tier function:
  ```ts
  function confidenceFor(reviewCount: number): number {
    if (reviewCount >= 50_000) return 0.4;
    if (reviewCount >= 5_000) return 0.6;
    return 1.0; // 500–4,999 small-sample zone
  }
  ```
- Pass `reviewCount` into `<Stat />` and use `confidenceFor(reviewCount)`
  instead of the flat `CONFIDENCE` constant.
- Add a small "Small-sample" pill (styled like `ConfidencePill`) when
  `reviewCount < 5_000`. Place it next to the existing ±N% pill.
- The ±N% pill already renders a percentage — update the component to
  render `±${confidence * 100}%` dynamically instead of the hardcoded
  "±50%" string.

### 4. `frontend/components/game/QuickStats.tsx`
- Reviews tile primary value stays as English (unchanged — that's what
  users expect to see), BUT add a secondary line when
  `review_count_english !== review_count`:
  `"• NNN total (all languages)"` in the same small-text style as the
  existing "N analyzed" suffix.
- Rationale: the English count is the user-meaningful number; the
  all-language count is the algorithm input. Surfacing both closes the
  mental-math gap without breaking the familiar "Reviews: 4,186" display.

### 5. `frontend/components/game/MarketReach.tsx` — basis line
- Add one line under the two Stat tiles (above the method/methodology
  row): `"Based on {reviewCount.toLocaleString()} reviews (all languages)"`
  when `review_count_english !== review_count`. This is the second half
  of the display fix: the estimator basis is explicit in the same card
  as the estimate. Only shows when the counts diverge.
- The caller (`GameReportClient.tsx`) already passes `reviewCount` into
  `<MarketReach />` — confirm it's the all-language `review_count`, not
  `review_count_english`. If it's the English count, switch it.

### 6. Empty state copy
- `emptyStateCopy` in `MarketReach.tsx` already handles
  `insufficient_reviews` with `"Not enough reviews yet to estimate
  (${reviewCount}/50)"`. Update the hardcoded `/50` to `/500`.

## Backfill

After merging:

```bash
bash scripts/dev/db-tunnel.sh  # separate terminal, for staging/prod
DATABASE_URL=... poetry run python scripts/backfill_revenue_estimates.py --dry-run
# inspect the outcome breakdown, then:
DATABASE_URL=... poetry run python scripts/backfill_revenue_estimates.py
```

Because `METHOD_VERSION` is bumping to `"boxleiter_v2"`, the default
`--only-stale` mode will now catch every row in the DB (all of them have
`revenue_estimate_method = "boxleiter_v1"` from prior runs). No need for
`--all`.

Expected outcome breakdown shift vs. current state:
- `_computed` count drops — games in the 50–499 reviews range flip to
  `insufficient_reviews`.
- `insufficient_reviews` count rises correspondingly.
- Every remaining `_computed` row gets a fresh estimate under v2 math
  (most differ from stored values because stored values are from the
  pre-2026-04-10 50x era).

Then refresh matviews so the API and list surfaces pick up new values:

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_genre_games;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_tag_games;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_price_positioning;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_discovery_feeds;
```

(`mv_discovery_feeds` was added in migration 0047/0048 and also carries
`estimated_owners` / `estimated_revenue_usd` columns.)

## Explicitly out of scope

- **Re-tuning signal factors or the 30x base.** Needs ground-truth data
  against Steam API developer reports, which we don't have. Cossacks 3
  being 27% under SteamDB is within the ±50% band — not a tuning signal.
- **Early-Access special case.** Research is mixed (EA reviews less per
  owner, but EA buyers also skew enthusiast). No defensible adjustment
  direction without ground truth.
- **Switching the estimator input to English-only reviews.** Would
  require full recalibration; the multipliers in the research literature
  are all against total reviews.
- **Widening coverage** via Gamalytic/VG Insights API fetches to fill
  the sub-500 gap with external estimates. Separate initiative.

## Acceptance

- Nightmare Frontier (203 all-lang reviews) renders the empty state:
  "Not enough reviews yet to estimate (203/500)".
- Cossacks 3 (15,794 all-lang reviews) renders a fresh estimate with the
  ±60% band and no small-sample pill.
- A game with 501 all-lang reviews renders with ±100% band and the
  "Small-sample" pill.
- `revenue_estimate_method = 'boxleiter_v2'` for every row in `games`
  after backfill.
- Reviews tile on Cossacks 3 shows "4,186 en • 15,794 total".
- Market Reach card on Cossacks 3 shows "Based on 15,794 reviews
  (all languages)".
