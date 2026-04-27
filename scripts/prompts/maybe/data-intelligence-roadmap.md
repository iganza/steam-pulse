# SteamPulse Data Intelligence Roadmap

> **Pairs with `monetization-strategy.md`.** That doc defines the six-tier packaging (Free / $99 Decision Pack PDF / $499 Atlas PDF / $79/mo Pro / $499/mo Studio / Enterprise). This roadmap defines what features feed each tier. Per-feature "Free/Pro" annotations in this document map to the packaging as: **Free** = the public per-game / per-genre web page; **Pro** = the $79/mo subscription and above; **PDF** items appear in the $99 Decision Pack (per-game) or $499 Atlas (per-genre).

## Table of Contents

1. [Why this matters](#why-this-matters)
2. [Two-layer architecture](#two-layer-architecture)
3. [Competitive landscape](#competitive-landscape)
4. [What stakeholders need](#what-stakeholders-need)
5. [Feature catalog — priority-ordered](#feature-catalog)
   - [Tier 1 — Highest value, ships fastest (1–10)](#tier-1)
   - [Tier 2 — High value, more engineering (11–23)](#tier-2)
   - [Tier 3 — Needs new infrastructure or parsing (24–31)](#tier-3)
6. [What goes in PDF reports](#pdf-reports)
7. [Implementation priority phases](#implementation-phases)
8. [Architectural notes](#architectural-notes)
9. [Differentiation summary](#differentiation-summary)
10. [Data gaps blocking future work](#data-gaps)

---

<a id="why-this-matters"></a>

## Why this matters

LLM analysis costs ~$1/game and rolls out gradually. The catalog has 130k+ games but only a fraction are LLM-analyzed. The platform needs a strong data-only intelligence layer that delivers value to every game in the catalog before any LLM touches it.

The database already contains 89 columns per game, full review history (playtime, sentiment, timestamps, helpful votes, EA status, free-key flag), tag votes, audience overlap, revenue estimates, and 17 materialized views. Most of this data is underutilized beyond basic listing and charting.

This roadmap delivers two complementary layers using only existing data, with a few items gated on minor data-collection additions.

<a id="two-layer-architecture"></a>

## Two-layer architecture

The features in this roadmap split into two engineering shapes that ship side-by-side into the same product surfaces:

```
   ┌─────────────────────────────────────────────────────────────────┐
   │  DESCRIPTIVE LAYER  (matviews + denormalized columns + SQL)     │
   │                                                                  │
   │  Counts, percentiles, group-by aggregates. "What's there."      │
   │  Refreshed nightly/6h. Cheap, deterministic, easy to debug.     │
   │  ~Half the catalog below: niche finder, price positioning,     │
   │  launch windows, market segmentation, audience overlap, etc.   │
   └─────────────────────────────────────────────────────────────────┘
                                  +
   ┌─────────────────────────────────────────────────────────────────┐
   │  PREDICTIVE LAYER  (sklearn models, periodic fit + scoring)     │
   │                                                                  │
   │  Models: regression, clustering, anomaly, survival, association.│
   │  "What's typical, what's anomalous, what's predictable."        │
   │  Fit weekly/monthly, score per-game on demand or batch.         │
   │  ~Half the catalog below: archetype, hedonic pricing, survival  │
   │  curves, association rules, vocabulary fingerprint, etc.       │
   └─────────────────────────────────────────────────────────────────┘
                                  ↓
                    Both feed: web dashboards, API endpoints,
                    per-game PDF reports, per-genre PDF reports.
```

Each feature in the catalog below is tagged `[matview]`, `[ML]`, or `[matview + ML]`.

<a id="competitive-landscape"></a>

## Competitive landscape

The game analytics market has 7+ active platforms. None combine market-level quantitative intelligence with review-derived qualitative intelligence, and **none combine matview aggregations with predictive ML modeling on Steam catalog data**.

| Platform                      | Focus                                                        | Pricing                      | Key gap SteamPulse fills                                              |
|-------------------------------|--------------------------------------------------------------|------------------------------|-----------------------------------------------------------------------|
| **VGInsights** (Sensor Tower) | Revenue estimates, 50+ datapoints/game, market sizing        | Freemium (acquired Mar 2025) | No review intelligence, no competitive positioning from audience data |
| **Gamalytic**                 | Revenue/sales, visual asset history, regional splits         | $25/mo – $75/mo              | No review analysis, no qualitative insights                           |
| **GameDiscoverCo**            | Editorial newsletter + unreleased game hype scoring          | $15/mo ($150/yr)             | Not self-service, single expert, can't explore ad-hoc                 |
| **GG Insights**               | 50k+ games, funnel builder, AI assistant, collections        | Freemium (1000+ devs)        | No structured review intelligence, no audience overlap                |
| **Game Dev Analytics**        | Free basic analytics (revenue, player counts, review trends) | Free                         | Very basic, no deep analysis or competitive positioning               |
| **SteamDB**                   | Player counts, price history, update/patch tracking          | Free (ads)                   | Pure data tracker, zero analysis or actionable intelligence           |
| **Indie Launch Lab**          | AI launch strategy, 16 years of release data                 | Launching Q2 2026            | Pre-launch competitor to watch                                        |
| **Steam Sentimeter**          | Per-game AI review sentiment (up to 10k reviews)             | Free                         | Per-game only, no market-level intelligence, no portfolio analysis    |
| **Datahumble**                | Side-by-side benchmarking, Steam Financial API               | Unknown                      | New entrant, focused on financial reporting                           |

**SteamPulse's structural advantages**:
1. **Audience overlap from cross-referenced reviewers** — no competitor has this at scale.
2. **Predictive ML on the same catalog** — competitors are descriptive only. Hedonic pricing, survival curves, archetype clustering, and association rules are not productized anywhere in this space.
3. **LLM-derived qualitative intelligence** when paired with the GameReport pipeline.

<a id="what-stakeholders-need"></a>

## What stakeholders need

From Chris Zukowski (howtomarketagame.com), GDC talks, dev forums, and market research:

1. **"What are players saying about games like mine?"** — structured review intelligence, not just star ratings.
2. **"Is my price right?"** — comparable-set + regression-based fair value. 51% of paid games launch under $10; getting this wrong is fatal.
3. **"When should I launch?"** — release timing by genre and tags. 58 games release daily on Steam; November peaks at 2,214/month.
4. **"What's the real competitive landscape?"** — actual audience overlap, not just "games with the same tags."
5. **"How long until I hit milestones?"** — time-to-100/1000/10000 reviews distributions by genre.
6. **"What killed similar games?"** — failure pattern recognition; survival analysis.
7. **"What kind of game am I, in market terms?"** — archetype assignment for positioning narrative.
8. **Affordable tooling** — 90% of indie studios can't afford professional market research. 56% self-fund.
9. **Localization decisions** — Chinese-speaking users became >50% of Steam in Feb 2025.

**Market context (2025–2026)**:
- 21,273 games released on Steam in 2025 (19.7% YoY growth)
- 30% of titles underperform due to oversaturation
- Indie games generated 25% of total Steam revenue in 2025
- Steam hit 42M concurrent users in Jan 2026
- Academic research confirms tags can be classified as fads, fashions, or stable classics (arxiv 2506.08881v1)

### Stakeholder priorities (mapped to packaging tiers)

| Stakeholder              | Primary questions                                                                          | Likely tier                                  |
|--------------------------|--------------------------------------------------------------------------------------------|-----------------------------------------------|
| **Indie developer**      | Pre-launch research, pricing, launch timing, milestones, what players love/hate            | Free + occasional $99 PDF, then Pro $79/mo    |
| **Marketing / UA**       | Positioning, audience targeting, store-page optimization, archetype, vocabulary            | Pro $79/mo                                    |
| **Studio executive**     | Genre health, ROI horizon, cohort comparison, franchise trajectory, lifecycle survival     | Studio $499/mo (often via Atlas $499 first)   |
| **Publisher / investor** | Portfolio intelligence, acquisition targets, hit rate, dev networks, anomaly screening     | Studio $499/mo or Enterprise                  |
| **IP owner**             | Franchise health, sequel performance arcs, brand strength signals, audience inheritance    | Studio $499/mo or Enterprise                  |
| **Gamer / consumer**     | Should I buy this? Hidden gems. Genre-space discovery.                                     | Free tier only                                |

<a id="feature-catalog"></a>

## Feature catalog — priority-ordered

Each feature includes: type tag, question answered, data, implementation outline, free/Pro split, competitor gap, audience value (Dev / Marketer / Studio / Publisher / Owner / Consumer).

<a id="tier-1"></a>

### Tier 1 — Highest value, ships fastest (#1–10)

These use existing data and existing matviews (with at most trivial extensions). Each ships in 1–2 sprints. Prioritized by audience-impact × engineering-speed × visual-impact.

---

#### 1. Game Health Score `[matview / denormalized]`

**Question:** "At a glance, how healthy is this game right now?"

**Data:** `games.positive_pct`, `games.review_count`, review velocity, `games.estimated_revenue_usd`, `games.platforms`, `games.deck_compatibility`, `games.achievements_total`, `games.metacritic_score`.

**Implementation:**
- New denormalized column `health_score NUMERIC(4,2)` on `games` (0–100)
- Weighted composite: sentiment 30% / momentum 25% / market presence 20% / platform reach 15% / content maturity 10%
- Computed on the write path (same pattern as revenue estimates)
- Surfaced in game cards, list sorting, detail page

**Free/Pro:** Score visible everywhere (free). Component breakdown + genre percentile = Pro.

**Competitor gap:** No platform has a composite health metric. SteamDB shows player count (one dimension).

**Value:** Dev MED · Marketer MED · Studio HIGH · Publisher HIGH · Consumer HIGH

---

#### 2. Review Pattern Signals `[matview]`

**Question:** "What can raw review numbers tell me about player behavior without reading any text?"

**Data:** `reviews` (voted_up, playtime_hours, posted_at, votes_helpful, votes_funny, written_during_early_access, received_for_free).

**Implementation:** extend `GET /api/games/{appid}/review-stats` and `/playtime-sentiment` endpoints with computed signals:

| Signal               | Formula                                                       | Meaning                                              |
|----------------------|---------------------------------------------------------------|------------------------------------------------------|
| Refund risk          | % negative reviews with playtime < 2h                         | Players bouncing within Steam's refund window        |
| Engagement cliff     | Playtime bucket with sharpest volume drop                     | Where players stop playing                           |
| Helpfulness skew     | helpful_votes(negative) / helpful_votes(positive)             | Negative reviews community endorses = unresolved     |
| Funny-vote anomaly   | funny / (funny + helpful)                                     | High ratio = review bombing or meme culture          |
| Free-key bias        | sentiment(received_for_free=true) − sentiment(organic)        | Whether free keys inflate sentiment                  |
| EA loyalty           | % of EA reviewers with 100+ hours                             | Early Access community stickiness                    |

**Free/Pro:** Refund risk + engagement cliff = free. Full suite = Pro.

**Competitor gap:** Steam Sentimeter does some per-game; no market-level aggregation or comparative analysis exists.

**Value:** Dev HIGH · Marketer MED · Studio MED · Publisher MED · Consumer LOW

---

#### 3. Game Archetype Clustering `[ML]`

**Question:** "What kind of game am I, in market terms?"

**Data:** `game_tags` (vote-weighted) + `game_genres` + price + platforms + sentiment + content depth → feature vector per game.

**Implementation:**
- Build feature vectors: tag-vote TF-IDF + genre one-hot + scaled numerics
- `MiniBatchKMeans` (K=20–40) over 130k games
- Persist archetype label per game; describe each archetype with most-distinctive tags + median price + median sentiment + top-5 example games
- Refit weekly; assign new games to nearest centroid daily

**Free/Pro:** Archetype label visible per-game (free). Archetype profile sheet + cross-archetype comparison = Pro.

**Competitor gap:** Nobody productizes catalog-wide archetype assignment.

**Value:** Dev MED · Marketer HIGH · Studio MED · Publisher MED · Consumer MED

---

#### 4. Genre-Space 2D Map `[ML]`

**Question:** "Where does my game sit on the visual map of the catalog?"

**Data:** Same feature vectors as #3.

**Implementation:**
- `umap-learn` (or sklearn `PCA` for cheaper) → 2D coords per game
- Color by genre; point size by review count; highlight target game
- Cache 2D coords with archetype model fit
- Refit monthly

**Free/Pro:** Map embedded in genre and per-game pages (free). Interactive zoom + filter + competitor pin-drop = Pro. Export PNG = Pro.

**Competitor gap:** Quantic Foundry has done static visualizations; nobody productizes interactive per-game positioning.

**Value:** Dev MED · Marketer **VERY HIGH** · Studio HIGH · Publisher MED · Consumer MED

```
                  GENRE-SPACE MAP (illustrative)

          Adventure ◯   ◯ Story-rich
                    ◯ ◯ ◯
               ◯ ◯ ◯ ★ ◯ ◯  ← target game
                ◯ ◯ ◯ ◯ ◯
                   ◯ ◯ ◯  Roguelike
            Sim ◯ ◯
              ◯ ◯       ◯ ◯ ◯ ◯ Action
        Strategy
```

---

#### 5. Time-to-Milestone Distributions `[ML / aggregate]`

**Question:** "How long until 100, 1000, 10000 reviews — what should I expect?"

**Data:** `games.release_date` + `reviews.posted_at` (per-game running review count).

**Implementation:**
- Per game: compute `days_to_N_reviews` for N ∈ {10, 100, 1000, 10000}
- Empirical CDFs by genre/archetype; persist P10/P25/P50/P75/P90 in `mv_milestone_distributions`
- Optional Weibull fit for extrapolation when game hasn't yet hit milestone
- New endpoint surfaces milestone progress vs cohort

**Free/Pro:** Genre-level milestone times (free). Archetype-level + your game's progress vs cohort = Pro.

**Competitor gap:** Nobody answers this question quantitatively. It's the most-asked indie dev question.

**Value:** Dev **VERY HIGH** · Marketer LOW · Studio HIGH · Publisher HIGH · Consumer LOW

---

#### 6. Tag Association Rules `[ML]`

**Question:** "What tag combinations co-occur beyond pairwise — and which combos predict success?"

**Data:** `game_tags` baskets per game.

**Implementation:**
- `mlxtend.frequent_patterns.apriori` (or FP-Growth) over game-tag baskets
- Compute support, confidence, lift for K-tag rules (K=2,3,4)
- Filter to rules with min_support=0.005 and lift > 1.5
- Cross with sentiment to find synergistic combos vs anti-patterns
- Persist top rules per genre in `mv_tag_rules`

**Free/Pro:** Top-10 rules per genre (free). Full rules + sentiment overlay + filter by tag = Pro.

**Competitor gap:** Nobody offers higher-order tag rule mining for games.

**Value:** Dev MED · Marketer HIGH · Studio MED · Publisher MED · Consumer LOW

---

#### 7. Market Niche Finder `[matview]`

**Question:** "Where are the underserved niches — tag/genre combos with high sentiment but low supply?"

**Data:** `games`, `game_tags`, `game_genres`.

**Implementation:**
- New matview `mv_niche_opportunities`: per (genre_slug, tag_slug) pair, compute game_count, avg_positive_pct, avg_review_count, avg_revenue_usd, median_price. Filter to pairs with ≥3 games.
- Composite opportunity score: `avg_positive_pct × log(avg_review_count) / sqrt(game_count)`
- New endpoint: `GET /api/analytics/niche-finder?genre=<slug>&min_sentiment=70&max_supply=50`
- Frontend: searchable table + scatter plot (supply vs demand vs sentiment)

**Free/Pro:** Top 10 results (free). Full drill-down + filter + export = Pro.

**Competitor gap:** VGInsights has market sizing but not gap analysis. Nobody cross-cuts tag × genre × sentiment × supply for whitespace discovery.

**Value:** Dev HIGH · Marketer HIGH · Studio HIGH · Publisher HIGH · Consumer LOW

---

#### 8. Launch Window Optimizer `[matview]`

**Question:** "When should I launch my [genre + tag] game for the best reception and least competition?"

**Data:** `games.release_date`, `games.positive_pct`, `games.review_count`, `game_genres`, `game_tags`.

**Implementation:**
- New matview `mv_launch_windows`: month × genre_slug × tag_slug (top 20 tags), with releases_count, avg_positive_pct, avg_review_count, competition_density (releases in ±2-week window). Bounded to last 3 years.
- Service computes `launch_score`: high sentiment + low competition
- New endpoint: `GET /api/analytics/launch-windows?genre=<slug>&tags=<s1>,<s2>`

**Free/Pro:** Genre-only view (free). Tag cross-cut + historical comparison = Pro.

**Competitor gap:** Indie Launch Lab (Q2 2026) may compete. Existing `mv_release_timing` lacks tag dimension and scoring.

**Value:** Dev HIGH · Marketer HIGH · Studio MED · Publisher MED · Consumer LOW

---

#### 9. Price Intelligence + Hedonic Model `[matview + ML]`

**Question:** "What should I price my game given its features — and what does the regression say is fair?"

**Data:** `games.price_usd`, `games.positive_pct`, `games.review_count`, `games.estimated_revenue_usd`, `game_genres`, `game_tags`, `games.platforms`, `games.achievements_total`, dev track record.

**Implementation:** two complementary outputs in one feature:

**(a) Comparable-set descriptive view (matview-based):**
- Find comparable set (same genre + overlapping tags + same platforms)
- Return P10/P25/P50/P75/P90 price distribution, sentiment by price band, revenue by price band, "sweet spot" recommendation
- Leverages existing `mv_price_positioning` with tag-dimension extension

**(b) Hedonic regression (ML):**
- `GradientBoostingRegressor` on `price_usd ~ tags + genres + platforms + content_features + dev_history`
- Output: predicted fair value + 25/75 percentile band
- Surfaced as: "Your game is priced $14.99; the model predicts $18.50 (95% CI: $15–22). You're priced 19% below fair value."
- Top-5 features driving the prediction (SHAP values)
- Refit monthly, score on demand

**Free/Pro:** Genre-level distribution (free). Hedonic prediction + tag-filtered comparable set + revenue overlay = Pro.

**Competitor gap:** VGInsights and Gamalytic show price data but don't recommend. Nobody runs hedonic models on Steam catalog publicly.

**Value:** Dev HIGH · Marketer HIGH · Studio MED · Publisher MED · Consumer LOW

---

#### 10. Competitive Positioning Dashboard `[matview]`

**Question:** "How does my game compare to direct competitors on every measurable dimension?"

**Data:** `mv_audience_overlap` (exists), `games`, `game_tags`, `game_genres`.

**Implementation:**
- New endpoint `GET /api/games/{appid}/competitive-profile`
- Joins top-N audience-overlap games, returns:
  - Price positioning (tier delta), sentiment gap, review velocity comparison
  - Platform coverage gaps (competitor has Mac/Linux/Deck, you don't)
  - Tag overlap (shared, unique per game)
  - Achievement count, revenue estimate comparison
- Service computes deltas + percentile rankings within competitor set
- No new matview — reads existing `mv_audience_overlap` + `games`

**Free/Pro:** Top 5 competitors with sentiment + price (free). Full profile (50 competitors, all dimensions, exportable) = Pro.

**Competitor gap:** No platform does multi-dimensional competitive analysis from audience-overlap data.

**Value:** Dev HIGH · Marketer HIGH · Studio MED · Publisher MED · Consumer MED

---

<a id="tier-2"></a>

### Tier 2 — High value, more engineering (#11–23)

Each requires either new matview infrastructure or moderate ML modeling work. 2–3 sprints each. Lower in the priority list either because of higher effort, narrower audience, or dependency on Tier 1.

---

#### 11. Survival Curves & Lifecycle Analysis `[ML]`

**Question:** "How long do games like mine stay relevant?"

**Data:** `games.release_date`, `reviews.posted_at`, derived monthly review velocity.

**Implementation:**
- Define "active": rolling 30-day review velocity above threshold (e.g., 5 reviews/month for indie tier)
- Kaplan-Meier (`lifelines`) on `time_until_inactive` per genre/archetype
- Cox proportional hazards model: which features extend active life? (`platforms`, `achievements_total`, `metacritic_score`, EA-launched, DLC count)
- Output: survival curve per genre + hazard ratios per feature
- Refit monthly, score on demand

**Free/Pro:** Genre-level survival curve (free). Hazard ratios + your game's projection = Pro.

**Competitor gap:** Nobody runs survival analysis on Steam at scale.

**Value:** Dev HIGH · Marketer LOW · Studio HIGH · Publisher HIGH · Consumer MED

```
            "% of games still active at month T" (illustrative)
   100% ┤●
        │ ●●
    80% ┤   ●●
        │     ●●●●          ← roguelike-deckbuilder cohort
    60% ┤         ●●●●
        │             ●●●●●●
    40% ┤                    ●●●●●●●
        │                            ●●●●●●●●
    20% ┤                                    ●●●●●●
        └──────────────────────────────────────────
         0    6    12    18    24    30    36 months
```

---

#### 12. Trend Forecasting + Genre Identity Drift `[matview + ML]`

**Question:** "Which tags/genres are gaining momentum, fading, or shifting in meaning?"

**Data:** `mv_tag_trend` (year × tag × game_count + sentiment, exists), `game_tags` over time.

**Implementation:**

**(a) Trend signals (existing matview, service-layer):**
- Service method computes growth acceleration (2nd derivative)
  - Growing + accelerating = **emerging**
  - Growing + decelerating = **peaking**
  - Growing supply + declining sentiment = **saturating**
  - Growing supply + growing sentiment = **thriving**
  - Shrinking supply = **declining**
- New endpoint: `GET /api/analytics/trend-signals?type=tags|genres&limit=20&window=3y`

**(b) Genre identity drift (ML):**
- For each year, compute genre's tag distribution (vote-weighted)
- PCA into 2D; plot trajectory through time
- Output: a line through PCA space showing how a genre has drifted (e.g., "Roguelite" 2018 → 2024)

**Free/Pro:** Top 10 trends + signal classification (free). Full list + sparklines + drift trajectory = Pro.

**Competitor gap:** Academic research shows fad/fashion/classic classification (arxiv 2506.08881v1); GameDiscoverCo provides editorial. Nobody productizes both as a self-service tool.

**Value:** Dev MED · Marketer HIGH · Studio HIGH · Publisher HIGH · Consumer MED

---

#### 13. Tag Affinity Network `[matview]`

**Question:** "Which tags frequently co-occur, and what does that mean for positioning?"

**Data:** `game_tags`, `tags.category`, `games.positive_pct`.

**Implementation:**
- New matview `mv_tag_affinity`: per (tag_a_slug, tag_b_slug) pair on same game, compute co_occurrence_count, avg_positive_pct, jaccard_index. Filter ≥10 co-occurrences. Optional genre dimension.
- New endpoint: `GET /api/analytics/tag-affinity?tag=<slug>&genre=<slug>`
- Frontend: force-directed network graph

**Free/Pro:** Top-10 affinities per tag (free). Full network + genre filter + sentiment overlay = Pro.

**Competitor gap:** Nobody offers this visualization.

**Value:** Dev MED · Marketer HIGH · Studio MED · Publisher MED · Consumer LOW

> Cross-reference: Tier 1 #6 (Tag Association Rules) extends this from pairwise to higher-order rules.

---

#### 14. Sentiment Predictor (Over/Underperformance Badge) `[ML]`

**Question:** "Is this game over- or under-performing the sentiment its tag combo predicts?"

**Data:** `game_tags`, `game_genres`, `games.platforms`, `games.price_tier`, `games.positive_pct`, dev history.

**Implementation:**
- `RandomForestRegressor` on `positive_pct ~ tags + genres + platforms + price_tier + dev_history`
- Per game: predicted positive_pct + residual (actual − predicted)
- Classify: residual > +5 = overperformer, < −5 = underperformer, else on-pace
- Persist `predicted_sentiment NUMERIC(5,2)` and `sentiment_residual NUMERIC(5,2)` on `games`
- Surface as a badge

**Free/Pro:** Badge visible per-game (free). Top-3 features driving prediction (SHAP) = Pro.

**Competitor gap:** Nobody scores Steam games by sentiment over/underperformance.

**Value:** Dev HIGH · Marketer MED · Studio MED · Publisher HIGH · Consumer MED

---

#### 15. Release Cohort Analysis `[matview]`

**Question:** "How is my release cohort doing collectively, vs earlier cohorts?"

**Data:** `games.release_date`, `games.positive_pct`, `games.review_count`, `game_genres`.

**Implementation:**
- Group games by (genre, release_quarter)
- Per cohort: median positive_pct, median review_count, total estimated_revenue, cohort_size
- Per game: z-score within cohort
- New matview `mv_release_cohorts`
- New endpoint: `GET /api/analytics/cohorts?genre=<slug>&granularity=quarter`

**Free/Pro:** Genre cohort overview (free). Z-score ranking + cross-cohort comparison = Pro.

**Competitor gap:** No platform offers cohort analysis at this granularity.

**Value:** Dev HIGH · Marketer MED · Studio HIGH · Publisher MED · Consumer LOW

---

#### 16. Developer Trajectory Analysis `[matview + ML]`

**Question:** "Is this developer improving, stagnating, or declining?"

**Data:** `games.developer_slug`, `games.release_date`, `games.positive_pct`, `games.review_count`, `games.estimated_revenue_usd`, `games.price_usd`, `game_genres`, `games.platforms`.

**Implementation:**
- New matview `mv_developer_trajectory`: per developer_slug (≥2 games), compute total_games, avg_positive_pct, latest_positive_pct, trajectory (improving/stable/declining), total_estimated_revenue, avg_time_between_releases, genre_diversity, platform_expansion, review_velocity_trend
- ML add-on: Cox PH model on developer-level features predicting next-release sentiment percentile
- New endpoint: `GET /api/developers/{slug}/trajectory`
- Cross-developer leaderboard endpoint
- Frontend: trajectory spark mini-chart of positive_pct across releases

**Free/Pro:** Individual trajectory (free). Leaderboard + cross-comparison + Cox model prediction = Pro.

**Competitor gap:** VGInsights shows publisher data but not developer trajectory with sentiment-arc visualization.

**Value:** Dev HIGH · Marketer MED · Studio HIGH · Publisher HIGH · Consumer MED

---

#### 17. Revenue Intelligence Dashboard `[matview]`

**Question:** "What does the revenue landscape look like? How winner-take-all is my genre?"

**Data:** `games.estimated_revenue_usd`, `games.estimated_owners`, `games.price_usd`, `game_genres`, `game_tags`, `games.release_date`.

**Implementation:**
- New matview `mv_revenue_landscape`: per (genre_slug, year), compute total_revenue, game_count, avg_revenue, median_revenue, p90_revenue, **gini_coefficient**, **top_10_pct_share**
- Service computes:
  - Gini per genre (0 = equal, 1 = winner-take-all)
  - Revenue-per-review efficiency (which genres convert reviews to $ best)
  - Breakeven threshold: review count + sentiment to hit median revenue at given price
- New endpoint: `GET /api/analytics/revenue-landscape?genre=<slug>&granularity=year`

**Free/Pro:** Genre overview (free). Gini + breakeven calculator + tag cross-cut = Pro.

**Competitor gap:** VGInsights has revenue data but not concentration analysis.

**Value:** Dev HIGH · Marketer MED · Studio HIGH · Publisher HIGH · Consumer LOW

---

#### 18. DLC Lifecycle + Survival `[matview + ML]`

**Question:** "How does DLC release affect base game health? Which games have thriving content ecosystems?"

**Data:** `games.dlc_appids`, `games.parent_appid`, `games.type`, `games.release_date`, `games.positive_pct`, `games.review_count`, `reviews.posted_at`.

**Implementation:**

**(a) Matview part:** `mv_dlc_ecosystem` per base game with DLC: dlc_count, base_positive_pct, avg_dlc_positive_pct, total_ecosystem_reviews, total_ecosystem_revenue, days_since_last_dlc, dlc_release_cadence_days

**(b) ML part:**
- Survival curve comparison: base games with vs without DLC
- DLC velocity spike: review velocity delta 30d pre vs 30d post each DLC release (joining `reviews.posted_at` against DLC release dates)
- Cox model: DLC cadence as a hazard ratio for base game continued activity

**Free/Pro:** DLC count + basic stats (free). Velocity analysis + survival comparison + cadence impact = Pro.

**Competitor gap:** Nobody analyzes DLC ecosystem health.

**Value:** Dev HIGH · Marketer HIGH · Studio HIGH · Publisher HIGH · Consumer MED

---

#### 19. Market Segmentation Map `[matview]`

**Question:** "How does the Steam market break down by genre × price × sentiment? Where are the white spaces?"

**Data:** `games`, `game_genres`, `game_tags`.

**Implementation:**
- New matview `mv_market_segments`: per (genre_slug, price_tier, sentiment_bucket), game_count, avg_review_count, avg_revenue, platform/Deck counts
  - Price tiers: free, <$5, $5-10, $10-20, $20-30, $30-50, $50+
  - Sentiment buckets: negative (<40), mixed (40-65), positive (65-85), very_positive (85-95), overwhelmingly_positive (95+)
- New endpoint: `GET /api/analytics/market-map?genre=<slug>`
- Frontend: heatmap with click-to-drill-in

**Free/Pro:** Full map (free, discovery driver). Cell drill-down + tag overlay = Pro.

**Competitor gap:** No platform offers this 3D cross-cut visualization.

**Value:** Dev MED · Marketer HIGH · Studio HIGH · Publisher HIGH · Consumer MED

---

#### 20. Game Similarity from Structured Features `[ML]`

**Question:** "Find games like mine — including before I have any reviews."

**Data:** Same feature vectors as #3 (Archetype clustering).

**Implementation:**
- `NearestNeighbors` (cosine) over the persisted feature vectors
- Output: top-20 nearest games by feature profile, with distances
- Complements `mv_audience_overlap` which requires reviewer overlap (cold-start failure)
- Persist top-20 per game in `mv_feature_neighbors`

**Free/Pro:** Top-5 feature neighbors (free). Full top-20 + distance breakdown = Pro.

**Competitor gap:** Audience overlap is review-based; this is feature-based and works for unreleased games.

**Value:** Dev HIGH (cold-start positioning) · Marketer MED · Studio MED · Publisher MED · Consumer MED

---

#### 21. Steam Deck Opportunity Finder `[matview]`

**Question:** "Is Deck verification creating competitive advantage in my genre?"

**Data:** `games.deck_compatibility`, `game_genres`, `game_tags`, `games.positive_pct`, `games.review_count`.

**Implementation:**
- New matview `mv_deck_opportunity`: per (genre_slug, tag_slug), counts of verified/playable/unsupported/unknown + verified vs unverified avg sentiment + review counts
- Compute Deck premium per genre (positive_pct delta verified − unverified)
- Per-game surface: "X of your Y competitors are Deck Verified."

**Free/Pro:** Genre stats (free). Per-game competitive Deck analysis = Pro.

**Competitor gap:** Nobody treats Deck verification as competitive intelligence.

**Value:** Dev HIGH · Marketer MED · Studio MED · Publisher LOW · Consumer MED

---

#### 22. Publisher Portfolio Intelligence `[matview]`

**Question:** "How does this publisher's portfolio compare to peers?"

**Data:** `games.publisher_slug`, `games.positive_pct`, `games.review_count`, `games.estimated_revenue_usd`, `games.price_usd`, `game_genres`.

**Implementation:**
- New matview `mv_publisher_portfolio`: per publisher_slug (≥3 games), total_games, total_reviews, avg_positive_pct, hit_rate (% with positive_pct ≥80), total_revenue, avg_price, **genre_concentration (HHI)**, platform_coverage
- Endpoints for individual + leaderboard + cross-publisher comparison

**Free/Pro:** Individual publisher view (free). Leaderboard + comparison = Pro.

**Competitor gap:** Gamalytic / VGInsights show publisher data but not hit rate, HHI, or cross-publisher benchmarking.

**Value:** Dev LOW · Marketer MED · Studio HIGH · Publisher HIGH · Consumer LOW

---

#### 23. Review-Count Forecaster `[ML]`

**Question:** "How many reviews should I expect at 30/90/365 days?"

**Data:** Launch features (tags, genre, platforms, price, dev track record) + observed `reviews_at_T` for past games.

**Implementation:**
- Quantile regression (`GradientBoostingRegressor` with quantile loss) at q ∈ {0.1, 0.5, 0.9}
- Per launch features: P10/P50/P90 forecast at 30/90/365 days
- Output as fan chart

**Free/Pro:** Median forecast (free). Quantile bands + feature importance = Pro.

**Competitor gap:** Indie Launch Lab may compete; nobody currently productizes this.

**Value:** Dev MED · Marketer LOW · Studio HIGH · Publisher VERY HIGH · Consumer LOW

---

<a id="tier-3"></a>

### Tier 3 — Needs new infrastructure or parsing (#24–31)

These are high-value but require either new data collection, parsing of unstructured fields, or infrastructure (user accounts) that doesn't exist yet.

---

#### 24. Review Bomb Detection + Anomaly Scanning `[ML]`

**Question:** "Has this game been review bombed? When? Has it recovered? Are there other anomalies?"

**Implementation:**
- Windowed aggregate per game: detect spikes in volume × negative sentiment (3-sigma from rolling 30-day mean, >70% negative) → review bomb flag
- Broader: `IsolationForest` on (sentiment_residual, velocity_anomaly, helpful-vote-skew, funny-vote-spike) → general anomaly score
- Persist `review_bomb_detected BOOLEAN`, `review_bomb_date DATE`, `anomaly_score NUMERIC(4,2)` on `games`

**Value:** Dev MED · Marketer MED · Studio MED · Publisher MED · Consumer HIGH

---

#### 25. Description Vocabulary Fingerprint `[ML]`

**Question:** "How does my store-page language compare to genre norms?"

**Data:** `games.detailed_description`, `games.about_the_game` (HTML, needs cleaning).

**Implementation:**
- Strip HTML, tokenize with `TfidfVectorizer` over per-game text
- Compute genre centroid; per-game cosine distance from centroid
- RAKE (`rake-nltk`) or YAKE for characteristic phrases per genre
- Output: vocabulary heatmap; missing concepts; over-used phrases

**Value:** Dev MED · Marketer HIGH · Studio MED · Publisher LOW · Consumer LOW

---

#### 26. Franchise / Series Detection `[ML]`

**Question:** "What franchises exist? How are they performing across titles?"

**Data:** `games.name`, `games.developer`, `games.publisher`, `games.parent_appid`, `games.dlc_appids`.

**Implementation:**
- Fuzzy string matching (`rapidfuzz`) on game names within same dev/publisher
- Cluster sequels into franchise groups
- Series sentiment trajectory: does {1, 2, 3} get better or worse?
- Persist `franchise_id` on `games`; new `franchises` table

**Value:** Dev MED · Marketer HIGH · Studio HIGH · Publisher VERY HIGH · Owner **VERY HIGH** · Consumer MED

---

#### 27. Language / Localization Intelligence `[matview, needs HTML parse]`

**Question:** "Which languages drive review volume in my genre? Where's untapped demand?"

**Data:** `games.supported_languages` (HTML), `reviews.language`.

**Needs:** One-time parse of `supported_languages` HTML into `game_languages` table. Then matview `mv_language_demand` × language × genre × volume × sentiment.

**Value:** Dev HIGH · Marketer HIGH · Studio MED · Publisher MED · Consumer LOW

---

#### 28. System Requirements Clustering `[ML, needs HTML parse]`

**Question:** "What performance tier does my game fall in, and does that tier correlate with sentiment?"

**Data:** `games.requirements_windows` / `_mac` / `_linux` (HTML).

**Implementation:**
- Regex extraction of RAM/CPU/GPU specs from HTML
- KMeans on parsed (RAM_GB, GPU_year_class, CPU_cores)
- Test sentiment delta between performance tiers
- Output: performance tier badge + sentiment correlation by genre

**Value:** Dev MED · Marketer LOW · Studio LOW · Consumer MED

---

#### 29. Audience Size Estimation `[matview]`

**Question:** "How large is the total addressable audience for tags [X, Y, Z]?"

**Data:** `games.estimated_owners` + `game_tags`.

**Implementation:** Sum estimated owners across games with overlapping tags. Deduplication is imprecise but reasonable.

**Value:** Dev MED · Marketer HIGH · Studio HIGH · Publisher HIGH · Consumer LOW

---

#### 30. Developer Collaboration Network `[ML]`

**Question:** "Who works with whom, and which collaborations produce hits?"

**Data:** `games.developers[]`, `games.publishers[]`, `games.positive_pct`.

**Implementation:**
- Build bipartite graph (NetworkX) of developers ↔ publishers
- Centrality + community detection
- Hit rate per partnership cluster

**Value:** Dev LOW · Marketer LOW · Studio HIGH · Publisher VERY HIGH · Owner HIGH

---

#### 31. Real-Time Market Alerts `[infra]`

**Question:** "Alert me when a competitor's sentiment shifts or a new high-quality game enters my genre."

**Needs:** User accounts (Auth0 pending), subscription model, notification delivery (SNS/SQS exists but no user-facing subscription system).

**Value:** Dev HIGH · Marketer HIGH · Studio HIGH · Publisher HIGH · Consumer MED

---

<a id="pdf-reports"></a>

## What goes in PDF reports

Both layers feed into the paid PDF products at $49 / $149 / $499.

### Per-game PDF (companion to LLM `GameReport`)

| Section                         | Source feature(s)                                  | Tier |
|--------------------------------|---------------------------------------------------|------|
| Game Health Score               | #1 Game Health Score                               | T1   |
| Archetype + position on genre map | #3 Archetype + #4 Genre-Space Map                | T1   |
| Hedonic fair-value vs actual    | #9 Price Intelligence (hedonic part)               | T1   |
| Time-to-milestone progress      | #5 Time-to-Milestone                               | T1   |
| Sentiment over/underperformance | #14 Sentiment Predictor                            | T2   |
| Survival curve for archetype    | #11 Survival Curves                                | T2   |
| Anomaly flags                   | #24 Review Bomb / Anomaly                          | T3   |
| Vocabulary fingerprint vs genre | #25 Description Vocabulary                         | T3   |
| Top association rules          | #6 Tag Association Rules                            | T1   |
| Cohort comparison               | #15 Release Cohort                                 | T2   |
| Top-5 audience-overlap competitors | #10 Competitive Positioning Dashboard           | T1   |
| Top-5 feature-similar games     | #20 Game Similarity                                | T2   |

### Per-genre PDF (companion to `GenreSynthesis`)

| Section                         | Source feature(s)                                  | Tier |
|--------------------------------|---------------------------------------------------|------|
| Genre-space map (hero visual)   | #4 Genre-Space Map                                 | T1   |
| Archetype distribution          | #3 Archetype Clustering                            | T1   |
| Top-10 association rules        | #6 Tag Association Rules                           | T1   |
| Niche opportunities             | #7 Market Niche Finder                             | T1   |
| Launch window optimizer         | #8 Launch Window Optimizer                         | T1   |
| Genre cohort trajectory         | #15 Release Cohort                                 | T2   |
| Genre identity drift            | #12 Trend Forecasting + Drift                      | T2   |
| Survival curves by archetype    | #11 Survival Curves                                | T2   |
| Revenue concentration (Gini)    | #17 Revenue Intelligence                           | T2   |
| Market segmentation heatmap     | #19 Market Segmentation Map                        | T2   |
| Top franchises within genre     | #26 Franchise Detection                            | T3   |
| Top developers + trajectory     | #16 Developer Trajectory                           | T2   |

<a id="implementation-phases"></a>

## Implementation priority phases

Re-ordered from the source docs to balance descriptive and predictive layers, and to put visual / hero-output features early.

### Phase A — No new infrastructure, fastest visible wins (Tier 1, ~2 sprints total)

| # | Feature                              | Type     | Effort  |
|---|--------------------------------------|----------|---------|
| 1 | Game Health Score                    | matview  | 2 days  |
| 2 | Review Pattern Signals               | matview  | 2 days  |
| 6 | Tag Association Rules                | ML       | 1 day   |
| 5 | Time-to-Milestone Distributions      | ML/agg   | 1 day   |

### Phase B — Hero PDF visuals + first ML models (Tier 1)

| # | Feature                              | Type        | Effort   |
|---|--------------------------------------|-------------|----------|
| 3 | Game Archetype Clustering            | ML          | 1 day    |
| 4 | Genre-Space 2D Map                   | ML          | 2 days   |
| 9 | Price Intelligence + Hedonic Model   | matview+ML  | 4 days   |
| 10 | Competitive Positioning Dashboard   | matview     | 2 days   |

### Phase C — Tier 1 matview round-out

| # | Feature                              | Type     | Effort  |
|---|--------------------------------------|----------|---------|
| 7 | Market Niche Finder                  | matview  | 3 days  |
| 8 | Launch Window Optimizer              | matview  | 3 days  |

**End of Phase C: every game gets archetype + map + health score + niche + association rules + milestone + competitive positioning. The free product is now compelling.**

### Phase D — Tier 2: deeper ML and richer matviews

| # | Feature                              | Type        | Effort   |
|---|--------------------------------------|-------------|----------|
| 11 | Survival Curves & Lifecycle         | ML          | 3 days   |
| 14 | Sentiment Predictor                 | ML          | 2 days   |
| 15 | Release Cohort Analysis             | matview     | 2 days   |
| 12 | Trend Forecasting + Genre Drift     | matview+ML  | 4 days   |
| 13 | Tag Affinity Network                | matview     | 2 days   |
| 20 | Game Similarity from Features       | ML          | 2 days   |
| 23 | Review-Count Forecaster             | ML          | 3 days   |

### Phase E — Tier 2 matview heavy lifters

| # | Feature                              | Type        | Effort   |
|---|--------------------------------------|-------------|----------|
| 16 | Developer Trajectory + Cox PH       | matview+ML  | 4 days   |
| 17 | Revenue Intelligence Dashboard      | matview     | 3 days   |
| 18 | DLC Lifecycle + Survival            | matview+ML  | 4 days   |
| 19 | Market Segmentation Map             | matview     | 3 days   |
| 21 | Steam Deck Opportunity              | matview     | 2 days   |
| 22 | Publisher Portfolio Intelligence    | matview     | 3 days   |

### Phase F — Tier 3 (parsing + infrastructure)

| # | Feature                              | Blocker                              |
|---|--------------------------------------|--------------------------------------|
| 24 | Review Bomb + Anomaly Detection     | Periodic computation pipeline        |
| 25 | Description Vocabulary Fingerprint  | HTML clean of detailed_description   |
| 26 | Franchise Detection                 | Fuzzy match + manual review of edge cases |
| 27 | Language Intelligence               | Parse `supported_languages` HTML     |
| 28 | System Reqs Clustering              | Parse requirements HTML              |
| 29 | Audience Size Estimation            | Deduplication methodology            |
| 30 | Dev Collaboration Network           | Graph features + viz                 |
| 31 | Real-Time Alerts                    | Auth0 + subscription system          |

<a id="architectural-notes"></a>

## Architectural notes

### Matview features
- All new matviews follow existing patterns: DROP before CREATE, unique index for `CONCURRENTLY` refresh, register in `MATVIEW_NAMES` in `matview_repo.py`, auto-refreshed by `matview_refresh_handler.py`
- Per-game computed values (health_score, predicted_sentiment, anomaly_score) are denormalized columns matching the pattern for `positive_pct`, `review_velocity_lifetime`, `estimated_revenue_usd`
- All new endpoints: `Cache-Control: public, s-maxage=300, stale-while-revalidate=600`
- Free/Pro gating: frontend-only (backend returns full data)

### ML features (new)
- Models persist to S3 (versioned by fit timestamp): `s3://steam-pulse-models/{model_name}/{fit_timestamp}/{model.pkl, features.json, metrics.json}`
- Refit on a schedule (weekly for clustering / archetype, monthly for hedonic / sentiment predictor / survival)
- Scoring runs on the write path for new games (similar to revenue estimator) and as a backfill job for existing games after refit
- Model registry: `model_registry` table tracks `(model_name, version, fit_timestamp, training_set_size, metrics_json, s3_path, is_active)`
- ONNX export not needed for sklearn — pickled models load fast enough on Lambda
- LLM-cadence-economics rule (`feedback_llm_cadence_economics.md`) does NOT apply here — no per-game LLM cost in this layer

### Critical files
- Matview registry: `src/library-layer/library_layer/repositories/matview_repo.py`
- Analytics repo: `src/library-layer/library_layer/repositories/analytics_repo.py`
- Analytics service: `src/library-layer/library_layer/services/analytics_service.py`
- API endpoints: `src/lambda-functions/lambda_functions/api/handler.py`
- Schema: `src/library-layer/library_layer/schema.py`
- Migrations: `src/lambda-functions/migrations/`
- Game model: `src/library-layer/library_layer/models/game.py`
- **NEW** ML pipeline: `src/library-layer/library_layer/ml/` (new module)
- **NEW** Model registry: `src/library-layer/library_layer/repositories/model_registry_repo.py`
- **NEW** Trainer Lambda: `src/lambda-functions/lambda_functions/ml_trainer/handler.py` (scheduled fit)
- **NEW** Scorer Lambda: `src/lambda-functions/lambda_functions/ml_scorer/handler.py` (per-game scoring)

### Crawl pipeline
- No changes required for items #1–23.
- Items #24–28 require either new periodic jobs or HTML parsing helpers, but no new crawl endpoints.

<a id="differentiation-summary"></a>

## Differentiation summary

| What SteamPulse will have                                       | Nearest competitor                   | Our edge                                                                |
|-----------------------------------------------------------------|--------------------------------------|--------------------------------------------------------------------------|
| Audience-overlap competitive analysis                           | VGInsights (basic similar games)     | Cross-referencing actual reviewers, not just tag similarity              |
| Game Archetype Clustering + Genre-Space Map                     | Quantic Foundry (static)             | Productized per-game positioning + interactive                           |
| Hedonic pricing model                                           | VGInsights / Gamalytic (descriptive) | Prescriptive "fair value" prediction with feature importance             |
| Time-to-Milestone distributions                                 | Nobody                               | Answers the most-asked indie dev question quantitatively                 |
| Tag Association Rules (multi-tag)                               | Nobody                               | Beyond pairwise affinity                                                 |
| Survival curves + Cox PH                                        | Nobody                               | Lifecycle quantification with hazard ratios                              |
| Sentiment over/underperformance prediction                      | Nobody                               | Statistical residual signal per game                                     |
| Anomaly detection (Isolation Forest)                            | Nobody                               | Rigorous outlier flagging beyond heuristics                              |
| Genre identity drift                                            | Nobody                               | Visual time-evolution of genre meaning                                   |
| Vocabulary fingerprint                                          | Nobody                               | Store-page language vs genre norms                                       |
| Franchise detection + sentiment trajectory                      | Nobody                               | IP holder intelligence                                                   |
| Revenue concentration (Gini)                                    | VGInsights (revenue estimates)       | Winner-take-all metric per genre                                         |
| Review pattern signals (refund risk, engagement cliff)          | Steam Sentimeter (per-game)          | Market-level aggregation, comparative analysis                           |
| DLC ecosystem health + survival impact                          | Nobody                               | Content cadence as hazard                                                |
| Trend forecasting (fad/fashion/classic)                         | GameDiscoverCo (editorial)           | Automated, self-service, scalable                                        |
| Launch Window Optimizer                                         | Indie Launch Lab (Q2 2026)           | Self-service, tag-level granularity                                      |
| + LLM `GameReport` and `GenreSynthesis`                         | Nobody at scale                      | Structured qualitative intelligence layered on quantitative foundation   |

<a id="data-gaps"></a>

## Data gaps blocking future work

These are great ideas needing data we don't capture today. Mentioned for backlog awareness:

| Capability                       | What's needed                                | Unlocks                                    |
|----------------------------------|----------------------------------------------|--------------------------------------------|
| Discount elasticity              | Price-history snapshots                      | Discount A/B analysis, optimal discount depth |
| Store-page A/B test analysis     | Store-page edit history                      | Visual asset / copy effectiveness          |
| CCU decay curves                 | Concurrent-player snapshots                  | Engagement decay, alternative survival measure |
| Achievement completion analysis  | Achievement API per-game per-day             | Engagement signal, content-completion intelligence |
| Wishlist tracking                | Wishlist counts (Steam private API)          | Pre-launch demand forecasting              |

Each is one new crawl job + one storage table to unlock. Worth revisiting once the catalog above is in flight.
