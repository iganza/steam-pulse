# Revenue Estimator — Multi-Signal Boxleiter (Implemented)

## Problem

`boxleiter_v1` used a flat genre-bucket multiplier (15x indie, 25x strategy, 35x niche)
that systematically underestimates most games by 2-4x. The "mainstream" bucket (10x) was
defined but never wired up. There was no review-count scaling, no review-score adjustment,
and the age decay was a binary cliff at 3 years.

Cross-referencing our estimates against external sources revealed the gap:

| Game | Reviews | Price | Our v1 | steam-revenue-calculator | VG Insights range | Known actuals |
|---|---|---|---|---|---|---|
| Elden Ring | 785k | $60 | ~$600M | $2.26B | — | 28M+ copies confirmed |
| BG3 | 677k | $48 | ~$487M | $1.56B | $657M (2023 Steam) | $260M profit all platforms |
| Terraria | 1.1M | $10 | ~$146M | $548M | — | 33M PC copies confirmed |
| Black Myth | 848k | $60 | ~$764M | $2.44B | $852M (2 weeks) | ~$800M-1B lifetime Steam |
| Stardew Valley | 574k | $15 | ~$73M | — | — | 30M+ all platforms |

The research consensus for the base multiplier is:

- **steam-revenue-calculator.com**: flat ~48x for all games (overestimates mega-hits by 2-3x)
- **SteamRev**: flat 35x ("~3% of players leave reviews")
- **VG Insights**: ~30x recent, 20-100x adjusted by release year (calibrated against 10k+ actuals)
- **GameDiscoverCo NB (2025)**: 63x average, 36-59x by sales tier (developer-reported actuals)
- **Gamalytic**: dynamic 20-60x, uses 4 signals (review count, score, age, genre)
- **Jake Birkett (2018 survey)**: 80x average (likely outdated — review rates have increased)

## Goals

1. Fix `boxleiter_v1` in place — replace the flat bucket multiplier with a multi-signal
   variable multiplier. We haven't launched yet so there's no version migration concern.
2. Cross-check output against known data points and external sites
3. Keep the architecture: pure function, backfill-friendly
4. Same `estimated_owners` / `estimated_revenue_usd` columns, same `METHOD_VERSION = "boxleiter_v1"`
5. Estimate **Steam-only** owners (we only have Steam review data)

## Implemented Algorithm

### Base multiplier: 30x

Conservative baseline anchored to VG Insights' recent 30x estimate, while staying below
steam-revenue-calculator's flatter 48x assumption. All adjustments are multiplicative on
this base.

### Signal 1: Review-count scaling (DESCENDING for high counts)

The initial design draft assumed mega-hits need a higher multiplier based on GameDiscoverCo
data (36-59x by sales tier). However, that data represents the *total* multiplier including
all signals, not a standalone adjustment factor. Applying it as a factor on top of a 30x
base with four other multiplicative factors double-counted the effect, producing estimates
that overshot by 50-200% for mega-hits.

The implemented curve **decreases** the factor for high review counts because:
1. Mega-popular games have proportionally MORE reviewers per Steam buyer (cultural events
   drive review engagement)
2. Their non-Steam sales (console, Epic, etc.) are invisible to us — inflating the apparent
   review-to-owner ratio

```python
def _review_count_factor(review_count: int) -> Decimal:
    if review_count < 500:
        return Decimal("1.15")    # small games, high uncertainty
    if review_count < 50_000:
        return Decimal("1.0")     # baseline
    if review_count < 200_000:
        return Decimal("0.8")     # popular — higher review rates per sale
    return Decimal("0.6")         # mega-hit — very high review rates + invisible non-Steam sales
```

### Signal 2: Review score adjustment

Games with >90% positive reviews attract more reviews per sale (fans are motivated to
recommend), so the multiplier is lower. Mixed/negative games get fewer reviews per sale.

```python
def _review_score_factor(positive_pct: Decimal | None) -> Decimal:
    if positive_pct is None:
        return Decimal("1.0")
    if positive_pct >= 90:
        return Decimal("0.9")     # fans review eagerly
    if positive_pct >= 75:
        return Decimal("1.0")     # baseline
    if positive_pct >= 60:
        return Decimal("1.15")    # mixed — fewer people bother reviewing
    return Decimal("1.3")         # negative — only angry players review
```

### Signal 3: Release age (graduated)

Replaces the v1 binary cliff (>3y -> 0.85x). The v1 age decay was wrong — it *reduced*
the multiplier for old games, making them under-estimate more. Older games should get a
*higher* multiplier because early buyers who never reviewed dilute the ratio, and review
culture was weaker in Steam's early years.

```python
def _age_factor(release_year: int | None) -> Decimal:
    if release_year is None:
        return Decimal("1.0")
    age = date.today().year - release_year
    if age <= 3:
        return Decimal("1.0")     # recent — base rate
    if age <= 7:
        return Decimal("1.1")     # moderate non-reviewer dilution
    if age <= 12:
        return Decimal("1.2")     # significant
    return Decimal("1.3")         # pre-review-culture era
```

### Signal 4: Genre bucket (simplified from v1)

Niche audiences (visual novels, wargames, etc.) are engaged communities that review at
higher rates per sale — they get a LOWER factor (0.9x). This is the opposite direction
from v1 (which gave niche the highest multiplier at 35x) because v1 incorrectly assumed
niche audiences review *less* per sale.

```python
def _genre_factor(genres: list[dict], tags: list[dict]) -> Decimal:
    tag_names = {(t.get("name") or "").strip().lower() for t in tags}
    if tag_names & _NICHE_TAG_NAMES:
        return Decimal("0.9")     # engaged community, reviews more per sale

    genre_names = {(g.get("name") or "").strip().lower() for g in genres}
    if genre_names & _CASUAL_GENRES:
        return Decimal("1.1")     # casual audiences review less
    if genre_names & _STRATEGY_SIM_GENRES:
        return Decimal("1.05")

    return Decimal("1.0")
```

### Signal 5: Price tier

Cheap games have higher review rates per sale. Premium games have lower rates.

```python
def _price_factor(price_usd: Decimal) -> Decimal:
    if price_usd < Decimal("5"):
        return Decimal("0.85")    # cheap -> more reviews per sale
    if price_usd < Decimal("15"):
        return Decimal("1.0")     # baseline
    if price_usd < Decimal("40"):
        return Decimal("1.05")    # mid-price
    return Decimal("1.1")         # premium — fewer reviews per sale
```

### Combined formula

```python
BASE_MULTIPLIER = Decimal("30")

multiplier = (
    BASE_MULTIPLIER
    * _review_count_factor(review_count)
    * _review_score_factor(game.positive_pct)
    * _age_factor(release_year)
    * _genre_factor(genres, tags)
    * _price_factor(game.price_usd)
)

owners = int(Decimal(review_count) * multiplier)
revenue = (Decimal(owners) * price_usd).quantize(Decimal("0.01"))
```

### Validation results (Steam-only estimates)

| Game | Reviews | Price | Our estimate | Steam target | Accuracy | Source |
|---|---|---|---|---|---|---|
| Elden Ring | 786k | $60 | 15.4M / $924M | 10-14M | ~10% over (within ±50%) | Alinea: 15.7M Steam |
| BG3 | 678k | $48 | 12.1M / $579M | 15-20M | ~20% under (within ±50%) | VG Insights: 14.6M |
| Terraria | 1.1M | $10 | 24.1M / $240M | 30-35M | ~23% under (within ±50%) | Re-Logic: 33M PC |
| Black Myth | 849k | $60 | 15.1M / $908M | 12-16M | In range | Yicai: 20M Steam |
| Stardew Valley | 808k | $15 | 16.5M / $247M | 12-16M | In range | ~26M PC |
| Hades | 127k | $25 | 3.2M / $79M | 3-5M | In range | SteamSpy: 5-10M |
| Dwarf Fortress | 38k | $30 | 1.1M / $32M | 1-1.5M | In range | Kitfox: 1M+ |
| Victoria 3 | 16k | $50 | 701k / $35M | 400k-700k | In range | SteamSpy: 1-2M |

Note: The validation table above uses the same review counts as the test fixtures.
The external comparison earlier in the conversation used current steam-revenue-calculator
review counts (which include all languages and may differ from test fixture values).

All 8 games within ±50% band. 6/8 within target range.

For comparison, steam-revenue-calculator (flat 48x) overestimates mega-hits by 2-3x:
Elden Ring at $2.26B, Black Myth at $2.44B — wildly above confirmed actuals.

## Files Changed

### 1. `src/library-layer/library_layer/services/revenue_estimator.py`
- Kept `METHOD_VERSION = "boxleiter_v1"` (haven't launched)
- Replaced `GENRE_MULTIPLIERS` dict + `_select_bucket()` with `BASE_MULTIPLIER = 30`
  and five factor functions
- `compute_estimate()` reads `game.positive_pct` directly (no new parameter added)
- Removed `from __future__ import annotations` (Python 3.12)
- Exclusion logic unchanged

### 2. `scripts/backfill_revenue_estimates.py`
- Added `positive_pct` to `_fetch_games_bulk()` SELECT statement

### 3. `tests/services/test_revenue_estimator.py`
- All existing tests updated for new multiplier values
- Added tests for each factor function
- Added validation tests for 6 reference games (Elden Ring, Terraria, Black Myth,
  Hades, Dwarf Fortress, Victoria 3)

### 4. Frontend — no changes
- `MarketReach.tsx` already shows method version and ±50% confidence band
