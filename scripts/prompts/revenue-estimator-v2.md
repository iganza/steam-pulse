# Revenue Estimator — Multi-Signal Boxleiter

## Problem

`boxleiter_v1` uses a flat genre-bucket multiplier (15x indie, 25x strategy, 35x niche)
that systematically underestimates most games by 2-4x. The "mainstream" bucket (10x) is
defined but never wired up. There is no review-count scaling, no review-score adjustment,
and the age decay is a binary cliff at 3 years.

Cross-referencing our estimates against external sources reveals the gap:

| Game | Reviews | Price | Our v1 | steam-revenue-calculator | VG Insights range | Known actuals |
|---|---|---|---|---|---|---|
| Elden Ring | 785k | $60 | ~$600M | $2.26B | — | 28M+ copies confirmed |
| BG3 | 677k | $48 | ~$487M | $1.56B | $657M (2023 Steam) | $260M profit all platforms |
| Terraria | 1.1M | $10 | ~$146M | $548M | — | 33M PC copies confirmed |
| Black Myth | 848k | $60 | ~$764M | $2.44B | $852M (2 weeks) | ~$800M-1B lifetime Steam |
| Stardew Valley | 574k | $15 | ~$73M | — | — | 30M+ all platforms |

Our 15x default is far too low. The research consensus for the base multiplier is:

- **steam-revenue-calculator.com**: flat ~48x for all games
- **SteamRev**: flat 35x ("~3% of players leave reviews")
- **VG Insights**: ~30x recent, 20-100x adjusted by release year (calibrated against 10k+ actuals)
- **GameDiscoverCo NB (2025)**: 63x average, 36-59x by sales tier (developer-reported actuals)
- **Gamalytic**: dynamic 20-60x, uses 4 signals (review count, score, age, genre)
- **Jake Birkett (2018 survey)**: 80x average (likely outdated — review rates have increased)

The true multiplier varies significantly by:
1. **Review count** — mega-hits have lower review rates per sale (higher multiplier)
2. **Review score** — highly-rated games (>90%) get reviewed more per sale (lower multiplier ~30x);
   mixed games (~70%) get fewer reviews per sale (higher multiplier ~60x)
3. **Release recency** — older games have accumulated reviews over years (lower effective multiplier)
4. **Genre/audience** — niche audiences review more; mainstream audiences review less

## Goals

1. Fix `boxleiter_v1` in place — replace the flat bucket multiplier with a multi-signal
   variable multiplier. We haven't launched yet so there's no version migration concern.
2. Cross-check output against known data points (table above) and external sites
3. Keep the architecture: pure function, backfill-friendly
4. Same `estimated_owners` / `estimated_revenue_usd` columns, same `METHOD_VERSION = "boxleiter_v1"`

## Algorithm Design

### Base multiplier: 30x

This is the starting point — consensus midpoint between VG Insights (30x) and
steam-revenue-calculator (48x). All adjustments are multiplicative on this base.

### Signal 1: Review-count scaling (the Boxleiter curve)

Games with more reviews have a lower review-to-sale ratio. Model this as a log-scale
adjustment:

```
review_factor = clamp(log10(review_count) / log10(500000), 0.6, 1.5)
```

- 100 reviews → factor ~0.68 (few reviews = higher uncertainty, pull toward base)
- 1,000 reviews → factor ~0.79
- 10,000 reviews → factor ~0.88
- 100,000 reviews → factor ~1.0 (calibration anchor)
- 500,000+ reviews → factor ~1.0+ (mega-hits get slightly higher multiplier)

Wait — this is backwards. More reviews = *more* sales per review (higher multiplier).
Let me reconsider. The insight from GameDiscoverCo:

| Sales tier | Median multiplier |
|---|---|
| < 5,000 sales | 36x |
| 5,000-50,000 | 42x |
| 50,000-500,000 | 48x |
| > 500,000 | 59x |

So the multiplier *increases* with popularity. Model as a piecewise function on review count
(using review count as a proxy for sales tier):

```python
def _review_count_factor(review_count: int) -> Decimal:
    """Scale multiplier by review volume.

    Mega-popular games have proportionally fewer reviewers per buyer.
    Based on GameDiscoverCo 2025 data (36x-59x by sales tier).
    """
    if review_count < 500:
        return Decimal("0.85")    # ~25x effective — small games, higher review rate
    if review_count < 5_000:
        return Decimal("1.0")     # 30x — baseline
    if review_count < 50_000:
        return Decimal("1.2")     # ~36x — mid-tier
    if review_count < 200_000:
        return Decimal("1.4")     # ~42x — popular
    return Decimal("1.6")         # ~48x — mega-hit
```

### Signal 2: Review score adjustment

Gamalytic's key finding: games with >90% positive reviews have a ~30x ratio (fans are
motivated to review), while ~70% positive games have ~60x (fewer reviews per sale).

```python
def _review_score_factor(positive_pct: float) -> Decimal:
    """Adjust for review-score-driven review propensity.

    High-rated games attract more reviews per sale (lower multiplier).
    Low-rated games get fewer reviews per sale (higher multiplier).
    """
    if positive_pct >= 90:
        return Decimal("0.85")    # fans review eagerly
    if positive_pct >= 75:
        return Decimal("1.0")     # baseline
    if positive_pct >= 60:
        return Decimal("1.3")     # mixed — fewer people bother reviewing
    return Decimal("1.5")         # negative — only angry players review
```

### Signal 3: Release age (graduated, not binary)

Replace the v1 binary cliff (>3y → 0.85x) with a graduated curve. Older games have
accumulated reviews over many years, so their review-to-*current*-sales ratio is inflated.
But we're estimating *lifetime* sales, so older games need a *higher* multiplier (not lower)
because early buyers who never reviewed are a larger proportion.

Actually — the v1 age decay was *reducing* the multiplier for old games, which makes them
*under*-estimate even more. That's wrong. Older games should get a *higher* multiplier
because the review rate was lower in Steam's early years (fewer people reviewed) and
early buyers are diluted.

```python
def _age_factor(release_year: int | None) -> Decimal:
    """Adjust for release age.

    Older games have a higher owner-to-review ratio because:
    - Steam's review feature launched in 2013; pre-2013 games have very few reviews
    - Review culture has intensified over time
    - Early buyers who never reviewed dilute the ratio
    """
    if release_year is None:
        return Decimal("1.0")
    current_year = date.today().year
    age = current_year - release_year
    if age <= 2:
        return Decimal("1.0")     # recent — base rate
    if age <= 5:
        return Decimal("1.1")     # moderate dilution
    if age <= 10:
        return Decimal("1.3")     # significant — pre-2016
    return Decimal("1.5")         # very old — pre-2013, review culture was nascent
```

### Signal 4: Genre bucket (simplified from v1)

Keep genre as a signal but simplify — the other signals now handle most of the variance:

```python
def _genre_factor(genres: list[dict], tags: list[dict]) -> Decimal:
    """Genre/audience-driven adjustment.

    Niche audiences review at higher rates per sale (lower multiplier).
    Mainstream/casual audiences review less (higher multiplier).
    """
    tag_names = {(t.get("name") or "").strip().lower() for t in tags}
    genre_names = {(g.get("name") or "").strip().lower() for g in genres}

    # Niche audiences are engaged and review-happy → lower multiplier
    if tag_names & NICHE_TAGS:
        return Decimal("0.9")

    # Casual/mainstream audiences barely review → higher multiplier
    if genre_names & CASUAL_GENRES:
        return Decimal("1.2")

    # Strategy/sim players review at moderate rates
    if genre_names & STRATEGY_SIM_GENRES:
        return Decimal("1.1")

    return Decimal("1.0")  # default
```

### Signal 5: Price tier

Cheap games have higher review rates per sale (people feel more entitled to opine on
cheap purchases). Expensive games have lower rates.

```python
def _price_factor(price_usd: Decimal) -> Decimal:
    if price_usd < Decimal("5"):
        return Decimal("0.8")     # cheap → more reviews per sale
    if price_usd < Decimal("15"):
        return Decimal("1.0")     # baseline
    if price_usd < Decimal("40"):
        return Decimal("1.1")     # mid-price
    return Decimal("1.2")         # premium — fewer reviews per sale
```

### Combined formula

```python
BASE_MULTIPLIER = Decimal("30")

multiplier = (
    BASE_MULTIPLIER
    * _review_count_factor(review_count)
    * _review_score_factor(positive_pct)
    * _age_factor(release_year)
    * _genre_factor(genres, tags)
    * _price_factor(price_usd)
)

owners = int(Decimal(review_count) * multiplier)
revenue = (Decimal(owners) * price_usd).quantize(Decimal("0.01"))
```

### Validation targets

After implementing, run the estimator against these games and compare:

| Game | Reviews | Price | Target owners | Target gross rev | Source |
|---|---|---|---|---|---|
| Elden Ring | 785k | $60 | 25-30M | $1.5-1.8B | FromSoft confirmed 28M+ |
| BG3 | 677k | $48 | 15-20M | $700M-1B | VG Insights $657M in 2023 |
| Terraria | 1.1M | $10 | 30-35M | $300-350M | Re-Logic confirmed 33M |
| Black Myth | 848k | $60 | 15-20M | $800M-1.2B | Multiple sources |
| Stardew Valley | 574k | $15 | 20-25M | $300-375M | ConcernedApe: 30M+ all platforms |
| Hades | 127k | $25 | 5-8M | $125-200M | Supergiant: 6M+ |
| Dwarf Fortress | 38k | $30 | 1-2M | $30-60M | Kitfox confirmed "millions" |
| Victoria 3 | 16k | $50 | 600k-1M | $30-50M | Paradox: "below expectations" |

If any estimate is off by more than 2x from the target range, adjust the factors.
The goal is **±50% accuracy for most games** — we're explicit about the confidence
band in the UI.

## Files to Change

### 1. `src/library-layer/library_layer/services/revenue_estimator.py`
- Keep `METHOD_VERSION = "boxleiter_v1"` — we haven't launched, no version bump needed
- Replace the flat `GENRE_MULTIPLIERS` dict with `BASE_MULTIPLIER = 30`
- Replace `_select_bucket()` with the five factor functions above
- Update `compute_estimate()` to use the multiplicative factor chain
- Keep `RevenueEstimate` model unchanged
- Keep exclusion logic (F2P, DLC, <50 reviews, missing price) unchanged
- Add `positive_pct` as a required parameter to `compute_estimate()`

### 2. `scripts/backfill_revenue_estimates.py`
- Pass `game.positive_pct` to `compute_estimate()`
- No other changes needed — the backfill already iterates all games

### 3. `tests/services/test_revenue_estimator.py`
- Update all existing tests for the new multiplier values
- Add tests for each factor function
- Add a validation test that checks the reference games above are in the target range
- Test edge cases: very old games, very cheap games, mega-hits, niche games

### 4. Frontend — no changes
- `MarketReach.tsx` already shows method version and ±50% confidence band

## Backfill & Rollout

1. Implement v2 in `revenue_estimator.py`
2. Run backfill with `--dry-run` first to spot-check a few games
3. Run full backfill: `poetry run python scripts/backfill_revenue_estimates.py --all`
4. Refresh matviews: `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_price_positioning;`
5. Verify on the site that estimates look reasonable

## What This Does NOT Do

- No scraping of external sites — all calibration is from published research
- No net revenue / developer take-home calculation — we show gross only
- No per-game overrides or manual corrections
- No dynamic recalibration — the factors are static; future versions can add ML
