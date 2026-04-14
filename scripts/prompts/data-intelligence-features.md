# Data-Only Intelligence Features — Design Spec

Comprehensive catalog of game intelligence features SteamPulse can deliver using
ONLY structured data already in the database. No LLM analysis required. Every game
in the catalog gets value immediately — not just the fraction with AI reports.

---

## Why This Matters

LLM analysis costs ~$1/game and will roll out gradually. With 130k+ games in
`app_catalog` but only a fraction analyzed, the platform needs a strong data-only
value proposition. The database already contains 89 columns per game, full review
history with playtime/sentiment/timestamps, player tags with vote counts, audience
overlap, revenue estimates, and 17 materialized views. Most of this data is
underutilized beyond basic listing and charting.

---

## Competitive Landscape

The game analytics market has 7+ active platforms. None combine market-level
quantitative intelligence with review-derived qualitative intelligence.

| Platform                      | Focus                                                          | Pricing                      | Key Gap SteamPulse Fills                                              |
|-------------------------------|----------------------------------------------------------------|------------------------------|-----------------------------------------------------------------------|
| **VGInsights** (Sensor Tower) | Revenue estimates, 50+ datapoints/game, market sizing          | Freemium (acquired Mar 2025) | No review intelligence, no competitive positioning from audience data |
| **Gamalytic**                 | Revenue/sales, visual asset history, regional splits           | $25/mo – $75/mo              | No review analysis, no qualitative insights                           |
| **GameDiscoverCo**            | Editorial newsletter + unreleased game hype scoring            | $15/mo ($150/yr)             | Not self-service, one person's expertise, can't explore ad-hoc        |
| **GG Insights**               | 50k+ games, funnel builder, AI assistant, collections          | Freemium (1000+ devs)        | No structured review intelligence, no audience overlap                |
| **Game Dev Analytics**        | Free basic analytics (revenue, player counts, review trends)   | Free                         | Very basic, no deep analysis or competitive positioning               |
| **SteamDB**                   | Historical player counts, price history, update/patch tracking | Free (ads)                   | Pure data tracker, zero analysis or actionable intelligence           |
| **Indie Launch Lab**          | AI launch strategy, 16 years of release data                   | Launching Q2 2026            | Pre-launch competitor to watch                                        |
| **Steam Sentimeter**          | Per-game AI review sentiment (up to 10k reviews)               | Free                         | Per-game only, no market-level intelligence, no portfolio analysis    |
| **Datahumble**                | Side-by-side benchmarking, Steam Financial API integration     | Unknown                      | New entrant, focused on financial reporting                           |

**SteamPulse's structural advantage**: Audience overlap data from cross-referencing
reviewers across games. No competitor has this at scale — it enables genuine
competitive intelligence (who your players actually play, not just shared tags).

---

## What Developers Actually Need

From Chris Zukowski (howtomarketagame.com), GDC talks, dev forums, and market
research articles:

1. **"What are players saying about games like mine?"** — structured review
   intelligence, not just star ratings. Developers spend hours manually reading
   competitor reviews.
2. **"Is my price right?"** — comparable-set pricing relative to quality and genre
   norms. 51% of paid games launch under $10; getting this wrong is fatal.
3. **"When should I launch?"** — release timing by genre and tags. 58 games release
   daily on Steam; November peaks at 2,214/month.
4. **"What's the real competitive landscape?"** — actual audience overlap, not just
   "games with the same tags."
5. **"What killed similar games?"** — failure pattern recognition from review data.
6. **Affordable tooling** — 90% of indie studios can't afford professional market
   research. 56% self-fund; solo devs grew from 18% to 21% of releases.
7. **Localization decisions** — Chinese-speaking users became >50% of Steam in Feb
   2025. Which languages drive demand in which genres?

**Market context (2025-2026)**:
- 21,273 games released on Steam in 2025 (19.7% YoY growth)
- 30% of titles underperform due to oversaturation
- Indie games generated 25% of total Steam revenue in 2025
- Steam hit 42M concurrent users in Jan 2026
- Academic research confirms Steam tags can classify trends as fads, fashions,
  or stable classics (arxiv.org/html/2506.08881v1)

---

## Stakeholders

| Stakeholder | Primary Questions | Willingness to Pay |
|---|---|---|
| **Indie developer** | Pre-launch competitive research, pricing, launch timing, what players love/hate in genre | Medium ($10-25/mo) |
| **Marketing / UA** | Positioning, audience targeting, store page optimization, review language trends | Medium-High |
| **Publisher / investor** | Portfolio intelligence, acquisition targets, genre trends, market concentration | High ($50-100/mo) |
| **Gamer / consumer** | Should I buy this? Is this game healthy? Discovery by quality signals | Free tier only |

---

## Feature Catalog

### Tier 1 — Highest Value, Ships Quickly

These use existing data and matviews. No new matviews required (or only trivial
extensions). Can ship in 1-2 sprints each.

---

#### 1.1 Competitive Positioning Dashboard

**Question**: "How does my game compare to its direct competitors on every
measurable dimension?"

**Data**: `mv_audience_overlap` (exists), `games` (price, sentiment, velocity,
platforms, deck, achievements, metacritic, revenue), `game_tags`, `game_genres`.

**Implementation**:
- New endpoint `GET /api/games/{appid}/competitive-profile`
- Joins top-N audience-overlap games and returns structured comparison:
  - Price positioning vs competitors (tier delta)
  - Sentiment gap (positive_pct delta)
  - Review velocity comparison (reviews/day)
  - Platform coverage gaps (competitor has Mac/Linux/Deck, you don't)
  - Tag overlap (shared tags, unique tags per game)
  - Achievement count comparison
  - Revenue estimate comparison
- New repo method in `analytics_repo.py` joining `mv_audience_overlap` + `games` + `game_tags`
- Service computes deltas and percentile rankings within the competitor set
- No new matview — reads existing `mv_audience_overlap` + `games`

**Free/Pro**: Top 5 competitors with sentiment + price = free. Full profile (all
dimensions, 50 competitors, exportable) = Pro.

**Competitor gap**: No platform does multi-dimensional competitive analysis from
audience overlap data. VGInsights shows similar games but not this depth.

**Value**: Dev HIGH / Marketing HIGH / Publisher MEDIUM / Consumer MEDIUM

---

#### 1.2 Review Pattern Signals

**Question**: "What can raw review numbers tell me about player behavior without
reading any text?"

**Data**: `reviews` (voted_up, playtime_hours, posted_at, votes_helpful,
votes_funny, written_during_early_access, received_for_free). All in DB.

**Implementation**:
- Extend existing `GET /api/games/{appid}/review-stats` and
  `GET /api/games/{appid}/playtime-sentiment` with additional computed signals:

| Signal | Formula | What It Means |
|---|---|---|
| **Refund risk** | % negative reviews with playtime < 2h | Players bouncing within Steam's refund window |
| **Engagement cliff** | Playtime bucket with sharpest volume drop | Where players simply stop playing (distinct from churn wall which tracks sentiment) |
| **Helpfulness skew** | helpful_votes(negative) / helpful_votes(positive) | When negative reviews get disproportionate "helpful" votes = unresolved issues community agrees on |
| **Funny-vote anomaly** | funny / (funny + helpful) ratio | High ratio = review bombing or meme culture |
| **Free-key bias** | sentiment(received_for_free=true) − sentiment(organic) | Whether free-key reviews inflate/deflate sentiment |
| **EA loyalty** | % of EA reviewers with 100+ hours | Early Access community stickiness |

- SQL aggregates against `reviews` table, added to existing repo methods
- No new matviews for per-game data

**Free/Pro**: Refund risk + engagement cliff = free. Full suite = Pro.

**Competitor gap**: Steam Sentimeter does some of this per-game but doesn't offer
market-level aggregation or comparative analysis.

**Value**: Dev HIGH / Marketing MEDIUM / Publisher MEDIUM / Consumer LOW

---

#### 1.3 Game Health Score

**Question**: "At a glance, how healthy is this game right now?"

**Data**: `games.positive_pct`, `games.review_count`, review velocity trend,
`games.estimated_revenue_usd`, `games.platforms`, `games.deck_compatibility`,
`games.achievements_total`, `games.metacritic_score`.

**Implementation**:
- New denormalized column: `health_score NUMERIC(4,2)` on `games` (0-100)
- Weighted composite:
  - Sentiment (positive_pct): 30%
  - Engagement momentum (review velocity trend): 25%
  - Market presence (review_count percentile within genre): 20%
  - Platform reach (Windows + Mac + Linux + Deck verified): 15%
  - Content maturity (achievements > 0, metacritic presence): 10%
- Computed on the write path (same as revenue estimates)
- Surfaced in game cards, game list sorting (new sort option), game detail page
- No new matview — denormalized column, matching pattern for `positive_pct`,
  `review_velocity_lifetime`, `estimated_revenue_usd`

**Free/Pro**: Score visible everywhere (free). Component breakdown + genre
percentile context = Pro.

**Competitor gap**: No platform has a composite health metric. SteamDB shows player
count (one dimension). This is multi-dimensional.

**Value**: Dev MEDIUM / Marketing MEDIUM / Publisher HIGH / Consumer HIGH

---

#### 1.4 Market Niche Finder

**Question**: "Where are the underserved niches — tag/genre combos with high player
sentiment but low game supply?"

**Data**: `games`, `game_tags`, `game_genres`, `tags`, `genres`. All in DB.

**Implementation**:
- New matview `mv_niche_opportunities`: for each (genre_slug, tag_slug) pair,
  compute game_count, avg_positive_pct, avg_review_count, avg_revenue_usd,
  median_price. Filter to pairs with >= 3 games.
- Composite opportunity score:
  `opportunity_score = avg_positive_pct * log(avg_review_count) / sqrt(game_count)`
  High sentiment × high demand × low supply = opportunity.
- New endpoint: `GET /api/analytics/niche-finder?genre=<slug>&min_sentiment=70&max_supply=50`
- Frontend: searchable/filterable table + scatter plot (supply vs demand vs sentiment)
- Unique index on (genre_slug, tag_slug) for CONCURRENTLY refresh

**Free/Pro**: Top 10 results = free. Full drill-down + filtering + export = Pro.

**Competitor gap**: VGInsights has market sizing but not gap analysis. Nobody
cross-cuts tag × genre × sentiment × supply to find white space.

**Value**: Dev HIGH / Marketing HIGH / Publisher HIGH / Consumer LOW

---

#### 1.5 Launch Window Optimizer

**Question**: "When should I launch my [genre + tag] game for the best reception
and least competition?"

**Data**: `games.release_date`, `games.positive_pct`, `games.review_count`,
`game_genres`, `game_tags`. All in DB.

**Implementation**:
- New matview `mv_launch_windows`: month × genre_slug × tag_slug (top 20 tags),
  with releases_count, avg_positive_pct, avg_review_count, competition_density
  (releases in ±2 week window). Bounded to last 3 years.
- Service computes `launch_score` per month: high sentiment + low competition = good
- New endpoint: `GET /api/analytics/launch-windows?genre=<slug>&tags=<slug1>,<slug2>`
- Unique index on (month, genre_slug, tag_slug)

**Free/Pro**: Genre-only view = free. Tag cross-cut + historical comparison = Pro.

**Competitor gap**: Indie Launch Lab (launching Q2 2026) may do this. The existing
`mv_release_timing` has month × genre but not tag dimension or launch scoring.

**Value**: Dev HIGH / Marketing HIGH / Publisher MEDIUM / Consumer LOW

---

#### 1.6 Price Intelligence

**Question**: "What should I price my game at given its genre, tags, and platform
support?"

**Data**: `games.price_usd`, `games.positive_pct`, `games.review_count`,
`games.estimated_revenue_usd`, `game_genres`, `game_tags`, `games.platforms`. In DB.

**Implementation**:
- New endpoint: `GET /api/analytics/price-intelligence?genre=<slug>&tags=<s1>,<s2>&platforms=windows,mac`
- Service finds "comparable set" (same genre + overlapping tags + same platform
  footprint), returns:
  - Price distribution (p10, p25, p50, p75, p90) of comparable games
  - Sentiment by price band within comparable set
  - Revenue by price band
  - "Sweet spot" recommendation: price band with best revenue × sentiment product
- Can leverage existing `mv_price_positioning` with minor tag-dimension extension,
  or run a focused query against `games` for the filtered comparable set

**Free/Pro**: Genre-level distribution = free. Tag-filtered + revenue overlay +
recommendation = Pro.

**Competitor gap**: VGInsights and Gamalytic show price data but don't
*recommend*. This is prescriptive, not just descriptive.

**Value**: Dev HIGH / Marketing HIGH / Publisher MEDIUM / Consumer LOW

---

### Tier 2 — High Value, Needs New Matviews

Each requires one new matview + new endpoint + frontend work. 2-3 sprints each.

---

#### 2.1 Trend Forecasting (Rising / Falling Tags & Genres)

**Question**: "Which tags/genres are gaining momentum and which are fading?"

**Data**: `mv_tag_trend` (exists: year × tag × game_count + avg_positive_pct),
`mv_trend_by_genre`, `mv_trend_by_tag`. All exist.

**Implementation**:
- New service method computing growth acceleration (2nd derivative of game_count
  over years):
  - Growing + accelerating = **emerging**
  - Growing + decelerating = **peaking**
  - Growing supply + declining sentiment = **saturating**
  - Growing supply + growing sentiment = **thriving**
  - Shrinking supply = **declining**
- New endpoint: `GET /api/analytics/trend-signals?type=tags|genres&limit=20&window=3y`
- Returns: slug, growth_rate, growth_acceleration, sentiment_trend, signal
  classification
- No new matview needed — service-layer computation over existing matview data

**Free/Pro**: Top 10 trends = free. Full list + sparklines + genre cross-cut = Pro.

**Competitor gap**: Academic research (arxiv 2506.08881v1) shows tags can be
classified as fad/fashion/classic. Nobody productizes this for developers.

**Value**: Dev MEDIUM / Marketing HIGH / Publisher HIGH / Consumer MEDIUM

---

#### 2.2 Tag Affinity Network

**Question**: "Which tags frequently co-occur, and what does that mean for my
game's positioning?"

**Data**: `game_tags` (tag co-occurrence on same game), `tags.category`,
`games.positive_pct`.

**Implementation**:
- New matview `mv_tag_affinity`: for each (tag_a_slug, tag_b_slug) pair on same
  game, compute co_occurrence_count, avg_positive_pct, jaccard_index. Filter to
  pairs with >= 10 co-occurrences. Optional genre_slug dimension.
- New endpoint: `GET /api/analytics/tag-affinity?tag=<slug>&genre=<slug>&limit=20`
- Frontend: network graph (nodes = tags, edges = affinity, color = category, size
  = game count). Force-directed layout.
- Unique index on (tag_a_slug, tag_b_slug, genre_slug)

**Free/Pro**: Top-10 affinities per tag = free. Full network + genre filter +
sentiment overlay = Pro.

**Competitor gap**: Nobody offers tag co-occurrence intelligence. This is a
differentiated visualization.

**Value**: Dev MEDIUM / Marketing HIGH / Publisher MEDIUM / Consumer LOW

---

#### 2.3 Developer Trajectory Analysis

**Question**: "Is this developer improving, stagnating, or declining?"

**Data**: `games.developer_slug`, `games.release_date`, `games.positive_pct`,
`games.review_count`, `games.estimated_revenue_usd`, `games.price_usd`,
`game_genres`, `games.platforms`. All in DB.

**Implementation**:
- New matview `mv_developer_trajectory`: per developer_slug (>= 2 games), compute:
  total_games, avg_positive_pct, latest_positive_pct, trajectory
  (improving/stable/declining), total_estimated_revenue, avg_time_between_releases,
  genre_diversity (distinct genre count), platform_expansion (added Mac/Linux/Deck
  over time), review_velocity_trend
- New endpoint: `GET /api/developers/{slug}/trajectory` (richer than existing portfolio)
- Developer page: "trajectory spark" mini line chart of positive_pct across releases
- Cross-developer comparison: `GET /api/analytics/developer-leaderboard?genre=<slug>&min_games=3&sort=trajectory`
- Unique index on developer_slug

**Free/Pro**: Individual trajectory = free. Leaderboard + cross-comparison = Pro.

**Competitor gap**: VGInsights shows publisher data but not developer trajectory
with sentiment arc visualization.

**Value**: Dev HIGH / Marketing MEDIUM / Publisher HIGH / Consumer MEDIUM

---

#### 2.4 Revenue Intelligence Dashboard

**Question**: "What does the revenue landscape look like for my genre? How
winner-take-all is it?"

**Data**: `games.estimated_revenue_usd`, `games.estimated_owners`,
`games.price_usd`, `game_genres`, `game_tags`, `games.release_date`. All in DB.

**Implementation**:
- New matview `mv_revenue_landscape`: per (genre_slug, year), compute:
  total_estimated_revenue, game_count, avg_revenue_per_game, median_revenue,
  p90_revenue, gini_coefficient, top_10_pct_share (revenue concentration)
- New endpoint: `GET /api/analytics/revenue-landscape?genre=<slug>&granularity=year`
- Service computes:
  - **Gini coefficient** per genre (0 = equal, 1 = one game takes all)
  - **Revenue-per-review efficiency** (which genres convert reviews to $ best)
  - **Breakeven threshold**: review count + sentiment needed to hit genre median
    revenue at a given price
- Unique index on (genre_slug, year)

**Free/Pro**: Genre overview = free. Gini + breakeven calculator + tag cross-cut = Pro.

**Competitor gap**: VGInsights has revenue data but not concentration analysis.
Nobody shows how winner-take-all a genre is.

**Value**: Dev HIGH / Marketing MEDIUM / Publisher HIGH / Consumer LOW

---

#### 2.5 DLC / Content Lifecycle Analysis

**Question**: "How does DLC release affect base game health? Which games have
thriving content ecosystems?"

**Data**: `games.dlc_appids`, `games.parent_appid`, `games.type`,
`games.release_date`, `games.positive_pct`, `games.review_count`,
`reviews.posted_at`. All in DB.

**Implementation**:
- New matview `mv_dlc_ecosystem`: per base game (with DLC), compute: dlc_count,
  base_positive_pct, avg_dlc_positive_pct, total_ecosystem_reviews,
  total_ecosystem_revenue, days_since_last_dlc, dlc_release_cadence_days
- New endpoint: `GET /api/games/{appid}/dlc-ecosystem` and
  `GET /api/analytics/dlc-patterns?genre=<slug>`
- Derived metrics:
  - **DLC velocity spike**: review velocity delta 30d pre vs 30d post each DLC
    release (requires joining `reviews.posted_at` against DLC release dates)
  - **Content cadence impact**: do games with regular DLC cadence have higher
    base game sentiment?
- Unique index on (appid)

**Free/Pro**: DLC count + basic stats = free. Velocity analysis + cadence impact = Pro.

**Competitor gap**: Nobody analyzes DLC ecosystem health or content cadence impact.

**Value**: Dev HIGH / Marketing HIGH / Publisher HIGH / Consumer MEDIUM

---

#### 2.6 Market Segmentation Map

**Question**: "How does the Steam market break down by genre × price × sentiment?
Where are the white spaces?"

**Data**: `games`, `game_genres`, `game_tags`. All in DB.

**Implementation**:
- New matview `mv_market_segments`: per (genre_slug, price_tier, sentiment_bucket),
  compute game_count, avg_review_count, avg_revenue, platform/Deck counts.
  - Price tiers: free, <$5, $5-10, $10-20, $20-30, $30-50, $50+
  - Sentiment buckets: negative (<40), mixed (40-65), positive (65-85),
    very_positive (85-95), overwhelmingly_positive (95+)
- New endpoint: `GET /api/analytics/market-map?genre=<slug>`
- Frontend: heatmap (price tier × sentiment, intensity = game count, bubble = avg
  revenue). Click a cell → drill into games.
- Unique index on (genre_slug, price_tier, sentiment_bucket)

**Free/Pro**: Full map = free (discovery driver). Cell drill-down + tag overlay = Pro.

**Competitor gap**: VGInsights does genre analytics but not this three-dimensional
cross-cut visualization.

**Value**: Dev MEDIUM / Marketing HIGH / Publisher HIGH / Consumer MEDIUM

---

#### 2.7 Steam Deck Opportunity Finder

**Question**: "Is Deck verification creating competitive advantage in my genre?"

**Data**: `games.deck_compatibility`, `game_genres`, `game_tags`,
`games.positive_pct`, `games.review_count`. All in DB.

**Implementation**:
- New matview `mv_deck_opportunity`: per (genre_slug, tag_slug), compute:
  total_games, verified_count, playable_count, unsupported_count, unknown_count,
  verified_avg_positive_pct, unverified_avg_positive_pct, verified_avg_review_count,
  unverified_avg_review_count
- Compute **Deck premium** per genre: positive_pct delta between Verified and
  non-Verified games. Consistent premium = Deck support matters for that audience.
- New endpoint: `GET /api/analytics/deck-opportunity?genre=<slug>`
- Per-game surface: "X of your Y competitors are Deck Verified. You are not."
- Unique index on (genre_slug, tag_slug)

**Free/Pro**: Genre-level stats = free. Per-game competitive Deck analysis = Pro.

**Competitor gap**: Nobody treats Deck verification as competitive intelligence.

**Value**: Dev HIGH / Marketing MEDIUM / Publisher LOW / Consumer MEDIUM

---

#### 2.8 Publisher Portfolio Intelligence

**Question**: "How does this publisher's portfolio compare to peers?"

**Data**: `games.publisher_slug`, `games.positive_pct`, `games.review_count`,
`games.estimated_revenue_usd`, `games.price_usd`, `game_genres`. All in DB.

**Implementation**:
- New matview `mv_publisher_portfolio`: per publisher_slug (>= 3 games), compute:
  total_games, total_reviews, avg_positive_pct, hit_rate (% with positive_pct >= 80),
  total_estimated_revenue, avg_price, genre_concentration (HHI), platform_coverage
- New endpoint: `GET /api/publishers/{slug}/intelligence` and
  `GET /api/analytics/publisher-leaderboard?sort=hit_rate&min_games=5`
- Cross-publisher comparison endpoint
- Unique index on publisher_slug

**Free/Pro**: Individual publisher view = free. Leaderboard + comparison = Pro.

**Competitor gap**: Gamalytic and VGInsights show publisher data but not hit rate,
genre concentration (HHI), or cross-publisher benchmarking.

**Value**: Dev LOW / Marketing MEDIUM / Publisher HIGH / Consumer LOW

---

### Tier 3 — Needs Significant New Infrastructure or Data

These are high-value but require either new data collection, parsing unstructured
fields, or infrastructure (user accounts) that doesn't exist yet.

---

#### 3.1 Review Bomb Detection

**Question**: "Has this game been review bombed? When, and has sentiment recovered?"

**Data**: `reviews.posted_at`, `reviews.voted_up`. Detect anomalous spikes in
review volume with disproportionately negative sentiment (3-sigma from rolling
30-day mean, >70% negative).

**What's needed**: Windowed aggregate per game. Could be a denormalized
`review_bomb_detected BOOLEAN` + `review_bomb_date DATE` on `games`, recomputed
periodically. Or a new `review_events` table.

**Value**: Dev MEDIUM / Marketing MEDIUM / Publisher MEDIUM / Consumer HIGH

---

#### 3.2 Language / Localization Intelligence

**Question**: "Which languages drive review volume in my genre? Is there untapped
demand in non-English markets?"

**Data**: `games.supported_languages` (stored as HTML text), `reviews.language`.

**What's needed**: One-time parse/normalization of `supported_languages` HTML into
a structured `game_languages` table. Then matview `mv_language_demand` cross-cutting
language × genre × review_volume × sentiment. Especially valuable given Chinese now
>50% of Steam users.

**Value**: Dev HIGH / Marketing HIGH / Publisher MEDIUM / Consumer LOW

---

#### 3.3 Audience Size Estimation

**Question**: "How large is the total addressable audience for a game with tags
[X, Y, Z]?"

**Data**: `games.estimated_owners` + `game_tags`. Sum estimated owners across games
sharing those tags. Deduplication is imprecise but a reasonable approximation.

**What's needed**: Straightforward aggregate, but results require caveats about
double-counting. Audience overlap data could refine but only covers games with
>= 100 reviewers.

**Value**: Dev MEDIUM / Marketing HIGH / Publisher HIGH / Consumer LOW

---

#### 3.4 Real-Time Market Alerts

**Question**: "Alert me when a new game launches in my genre with high early reviews,
or when a competitor's sentiment shifts."

**What's needed**: User accounts (Auth0 pending), subscription model, notification
delivery. Infrastructure exists (SNS/SQS) but no user-facing subscription system.

**Value**: Dev HIGH / Marketing HIGH / Publisher HIGH / Consumer MEDIUM

---

## Implementation Priority

### Phase A — No new matviews, fastest to ship

| # | Feature                           | Work Required                                           |
|---|-----------------------------------|---------------------------------------------------------|
| 1 | Review Pattern Signals            | Extend existing repo methods + endpoints                |
| 2 | Competitive Positioning Dashboard | New repo method + endpoint (reads existing matviews)    |
| 3 | Trend Forecasting                 | New service method + endpoint (reads existing matviews) |
| 4 | Game Health Score                 | New denormalized column + write-path computation        |

### Phase B — New matviews, 1-2 per sprint

| # | Feature                 | New Matview              |
|---|-------------------------|--------------------------|
| 5 | Market Niche Finder     | `mv_niche_opportunities` |
| 6 | Tag Affinity Network    | `mv_tag_affinity`        |
| 7 | Revenue Intelligence    | `mv_revenue_landscape`   |
| 8 | Launch Window Optimizer | `mv_launch_windows`      |

### Phase C — Richer features

| #  | Feature                 | New Matview                   |
|----|-------------------------|-------------------------------|
| 9  | Price Intelligence      | Extend `mv_price_positioning` |
| 10 | Developer Trajectory    | `mv_developer_trajectory`     |
| 11 | DLC Lifecycle           | `mv_dlc_ecosystem`            |
| 12 | Market Segmentation Map | `mv_market_segments`          |
| 13 | Deck Opportunity        | `mv_deck_opportunity`         |
| 14 | Publisher Intelligence  | `mv_publisher_portfolio`      |

### Phase D — Infrastructure-dependent

| #  | Feature                  | Blocker                            |
|----|--------------------------|------------------------------------|
| 15 | Review Bomb Detection    | Periodic computation + event table |
| 16 | Language Intelligence    | Parse `supported_languages` HTML   |
| 17 | Audience Size Estimation | Deduplication methodology          |
| 18 | Real-Time Alerts         | Auth0 + subscription system        |

---

## Architectural Notes

- All new matviews follow existing patterns: DROP before CREATE, unique index for
  CONCURRENTLY refresh, register in `MATVIEW_NAMES` in `matview_repo.py`, auto-
  refreshed by existing `matview_refresh_handler.py`
- Per-game computed values (health_score) are denormalized columns matching pattern
  for `positive_pct`, `review_velocity_lifetime`, `estimated_revenue_usd`
- All new endpoints: `Cache-Control: public, s-maxage=300, stale-while-revalidate=600`
- Free/Pro gating: frontend-only (backend returns full data)
- No changes to crawl pipeline or data collection — everything uses data already
  gathered

### Critical files for implementation

| Purpose              | File                                                             |
|----------------------|------------------------------------------------------------------|
| Analytics repository | `src/library-layer/library_layer/repositories/analytics_repo.py` |
| Matview registry     | `src/library-layer/library_layer/repositories/matview_repo.py`   |
| Analytics service    | `src/library-layer/library_layer/services/analytics_service.py`  |
| API endpoints        | `src/lambda-functions/lambda_functions/api/handler.py`           |
| Schema reference     | `src/library-layer/library_layer/schema.py`                      |
| Migrations           | `src/lambda-functions/migrations/`                               |
| Game model           | `src/library-layer/library_layer/models/game.py`                 |

---

## Differentiation Summary

| What SteamPulse Has                                    | Nearest Competitor                   | Our Edge                                                    |
|--------------------------------------------------------|--------------------------------------|-------------------------------------------------------------|
| Audience overlap competitive analysis                  | VGInsights (basic similar games)     | Cross-referencing actual reviewers, not just tag similarity |
| Review pattern signals (refund risk, engagement cliff) | Steam Sentimeter (per-game)          | Market-level aggregation, comparative analysis              |
| Game Health Score (composite)                          | SteamDB (player count only)          | Multi-dimensional, actionable                               |
| Market Niche Finder (tag × genre gap)                  | VGInsights (market sizing)           | Prescriptive opportunity scoring, not just descriptive      |
| Tag Affinity Network                                   | Nobody                               | Entirely unique                                             |
| Revenue concentration (Gini)                           | VGInsights (revenue estimates)       | How winner-take-all is your genre?                          |
| DLC ecosystem health                                   | Nobody                               | Content cadence impact analysis                             |
| Trend forecasting (fad/fashion/classic)                | GameDiscoverCo (editorial)           | Automated, self-service, scalable                           |
| Launch Window Optimizer                                | Indie Launch Lab (launching Q2 2026) | Self-service, tag-level granularity                         |
| + LLM reports (when available)                         | Nobody at scale                      | Structured qualitative intelligence                         |
