# SteamPulse Packaging Strategy — From-Scratch Recommendation

> **Status:** exploration. The user asked: throwing out current assumptions, what would a smart business operator do for packaging, given the constraints (1) free stuff, (2) paid stuff, (3) one-time-purchase PDFs? This is my honest answer after researching the competitive landscape and applying patio11-style pricing thinking.

## TL;DR

Stop selling $49/$149/$499 genre PDFs as the headline product. Restructure as:

| Tier             | Product                            | Price            | Job-to-be-done                                |
|------------------|------------------------------------|------------------|------------------------------------------------|
| **Free**         | Every game page (SEO-indexed)      | $0               | Discovery, brand, traffic                       |
| **Per-Game PDF** | Decision Pack (one-time)           | **$99**          | "Should I make/price/launch this game?"        |
| **Per-Genre PDF**| Market Atlas (one-time)            | **$499**         | "Should we enter this genre? What's the market?" |
| **Pro Sub**      | Studio Pass for indies             | **$79/mo · $790/yr** | "Ongoing competitive intel + unlimited Decision Packs" |
| **Studio Sub**   | Multi-seat + API + atlases included| **$499/mo · $4,990/yr** | "Publisher/mid-studio depth + team usage"      |
| **Enterprise**   | Custom (don't publish price)       | $2k–$10k/mo      | M&A screening, weekly delivered intel           |

Key moves: **kill the $49 and $149 tiers** (signal cheapness, attract pathological customers), **enter the $79/mo competitive gap** (nobody is there), **price-anchor the subscription with the one-time PDF** ("$99/game OR $79/mo unlimited" is obvious math).

---

## How I got here

### Competitive landscape (real prices)

```
   $0/mo ────────────── $25/mo ────────── $75/mo ────────── $500/mo ────────── $20k/yr
   │                    │                  │                  │                  │
   Steam Sentimeter     GameDiscoverCo     Gamalytic Pro      [GAP]              PitchBook
   GameDevAnalytics     Plus ($19/mo)      ($75/mo)                              ($12k-40k/yr)
   IMPRESS free                                                                    Bloomberg
   VGInsights free      Gamalytic Starter  VGInsights Indie                      ($20k+/yr)
                        ($25/mo)           (~$20/mo)
                        Crunchbase Pro     
                        ($49/mo equiv)     
```

**The gap is between $75/mo and enterprise.** Nobody offers serious-indie / small-studio analytics in the $79–$499/mo band. That's where SteamPulse can win — and where its differentiated data (audience overlap + ML modeling + LLM reports) actually justifies the price.

### What patio11 / "smart operator" thinking says

From McKenzie, Cohen, Sethi (paraphrased + applied):

1. **Charge more.** Almost every founder underprices. Higher prices → better customers → less support → more profitable per logo.
2. **Free plans are marketing, not monetization.** Free should be a customer acquisition channel, not a customer-success tier.
3. **Don't compete on price** — that's a race to the bottom against well-funded incumbents. Compete on the audience that has *budget AND pain*.
4. **Information products price by decision value, not data cost.** A pricing study from a consultant is $1,000–$5,000. A "should we greenlight" study is $10k–$50k. Your PDFs replace those.
5. **Anchor higher tiers off lower tiers.** "$99 per game OR $79/mo unlimited" is the trick. The one-time price makes the subscription obvious math.
6. **Skip the cheapest tier.** A $19 tier brings $19 problems. Set the floor where serious customers live.

### Stakeholder budget reality

| Stakeholder            | Pre-launch decision value | Annual analytics budget |
|------------------------|--------------------------|-------------------------|
| Solo indie dev         | $20k–$200k (their savings) | $0–$300/yr              |
| Indie studio (2–10)    | $100k–$1M               | $300–$3,000/yr           |
| Mid studio (10–50)     | $500k–$5M               | $3k–$25k/yr              |
| Publisher (small)      | $2M–$20M+ portfolio      | $25k–$100k/yr            |
| Investor / VC          | $50M+ fund               | $50k–$500k/yr            |

The current $49 / $149 / $499 PDFs hit the bottom two and badly mismatch the upper three. The packaging below covers the full ladder.

---

## Recommended packaging in detail

### Free tier — every game page (zero gating)

**Job:** Drive SEO traffic, build brand trust, become the default "where I look up a Steam game's analytics."

**Content:** Game card with health score, archetype label, top-3 strengths and frictions (LLM excerpt), 5 audience-overlap competitors, genre-space map position (small embed), genre-median time-to-milestone, hidden-gem flag if applicable. Public, indexable, shareable.

**Why generous:** Every indie dev googles their own game and their competitors. If they land on SteamPulse and the page is rich, you've earned discovery. This is your acquisition channel.

**What's *not* free:** The depth (full data, all 50 competitors, model confidence intervals, exports, comparisons, projections, custom queries).

---

### One-time PDFs — the productized info products

#### Per-Game Decision Pack — $99

**Job:** "I'm spending 18 months and $50k+ on this game. Should I, and how should I position it?"

**Buyer:** Solo indie dev, marketer prepping a launch, consultant doing client research.

**Content (everything for one game):**
- Full LLM `GameReport` (all sections, no truncation)
- Hedonic fair-value with confidence band + SHAP feature importance ("you're priced 19% below model fair value of $18.50; top drivers: tag X, platform Y")
- Survival curve for your archetype + your projected lifecycle position
- Time-to-milestone with P10/P50/P90 bands vs your cohort
- 50-competitor positioning (audience-overlap + feature-similarity, with full deltas)
- Top association rules for your tag combo
- Vocabulary fingerprint vs genre norms
- Anomaly flags + sentiment over/underperformance with feature drivers
- Cohort z-score
- Genre-space map with your game pinned

**Why $99:** It's one consultant hour, one Steam asset purchase, lunch for the studio. Painless for anyone with a real game in development. Below $99 (e.g., $49) signals "amateur tool" and attracts customers who'll send you 12 support tickets. $99 says serious.

**Sales hook:** "Replaces a $1,500 pricing study. Read it tonight."

#### Per-Genre Market Atlas — $499

**Job:** "Should our studio/portfolio enter this genre? What's the real market structure?"

**Buyer:** Studio strategy lead, publisher acquisition team, investor analyst.

**Content (everything for one genre):**
- LLM `GenreSynthesis` (cross-genre themes, friction patterns, dev priorities)
- Genre-space 2D map of all genre members (hero visual)
- Niche opportunities (white-space tag combos)
- Launch window optimizer (when to ship)
- Tag association rules (what works, anti-patterns)
- Cohort trajectories (how each release year is performing)
- Genre identity drift (how the genre is changing year-on-year)
- Survival curves by archetype
- Revenue concentration (Gini coefficient + top-10% share)
- Top 25 games, top 10 developers, top 10 franchises in genre with trajectories

**Why $499:** A greenlight committee can expense it. A consultant can mark it up. It replaces a $5k–$15k market study from a research firm. At $499 it's "yes" without committee approval.

**What was the $49 / $149 tier for?** Mostly customers who'd be a support burden. Drop them. The $99 Decision Pack absorbs the per-game intent; the $499 Atlas absorbs the per-genre intent.

---

### Subscriptions — for ongoing usage

#### Pro — $79/month or $790/year

**Job:** "I'm a serious indie dev / small studio and I look at competitor games every week."

**Buyer:** Solo devs and 2–10 person studios with active development.

**Content:**
- Everything in the free tier
- **Unlimited Per-Game Decision Pack downloads** (any game, any time)
- Live dashboards (vs static PDFs)
- Interactive Niche Finder, Launch Window Optimizer, Hedonic Pricing tool
- Save/track: portfolio of "watched" games + competitor list
- CSV export
- Email digests (weekly genre summary)
- Email alerts when competitor sentiment shifts (when alerting infra exists)

**Annual pricing:** $790/yr = 2 months free. Drives prepay.

**Anchoring math:** "$99 per game OR $79/mo for unlimited." Anyone analyzing >1 game per month picks the sub. This is the conversion engine.

**Why $79 (not $19, not $49):** Patio11 territory — the $79 customer is serious, won't ask 47 support questions, will renew. $19/mo customers churn fast and cost more in support than they pay. Also leaves room above for Studio tier without compression.

#### Studio — $499/month or $4,990/year

**Job:** "We're a publisher or mid-studio. We need this for our team, with API access and depth."

**Buyer:** 10+ person studios, small publishers, dev consultancies.

**Content:**
- Everything in Pro
- **Per-Genre Market Atlas PDFs included** (any genre, on demand)
- Up to 10 user seats
- API access (programmatic pulls for internal tools)
- Custom comparable-set definitions
- Quarterly genre deep-dive emailed
- Priority email support
- White-label option for client reports (consultancy use)

**Anchoring math:** "$499 per Atlas OR $499/mo for unlimited Atlases + Pro for the whole team." Any studio touching >1 genre per quarter picks the sub.

#### Enterprise — Custom (don't publish price)

**Job:** "We're an investor or major publisher. We want bespoke intelligence."

**Buyer:** VCs, M&A teams, big publishers, strategic acquirers.

**Content:**
- Custom data pulls + bespoke reports
- Acquisition target screening (anomaly detection cross-catalog)
- Weekly/monthly delivered intelligence packets
- White-glove onboarding + dedicated contact
- Embargo on data publication for sensitive deals

**Pricing:** $2k–$10k/month. Negotiated. The fact that you don't publish the price is the signal.

---

## Why this packaging is smart

### Each tier has a clear, distinct buyer

```
   Solo indie    ──→  Free + occasional $99 Decision Pack
   Active indie  ──→  Pro $79/mo (one Pack/mo math justifies it)
   Studio        ──→  Studio $499/mo (one Atlas/quarter math justifies it)
   Publisher/VC  ──→  Enterprise (decisions worth $1M+ each)
```

No tier cannibalizes the next.

### Each price point anchors the next

- $99/game → makes $79/mo subscription obvious (>1 game/mo and you save)
- $499/genre → makes $499/mo Studio subscription obvious (1 atlas/mo and the rest is free)
- Visible pricing on the first 3 tiers builds trust; opaque Enterprise pricing captures whales

### The free tier is a marketing asset, not a product

Every game page is SEO-bait. Devs google their own game; competitors look up each other; press references SteamPulse. Free isn't generosity — it's the customer acquisition cost.

### Packaging mirrors the actual job-to-be-done

- Free = "I'm browsing"
- $99 PDF = "I'm making a specific decision NOW about ONE game"
- $499 PDF = "I'm making a specific decision NOW about ONE genre"
- $79/mo Sub = "I make these decisions all the time"
- $499/mo Sub = "My team makes these decisions and we need API + depth"

Mismatched packaging (e.g., forcing the Pro features into a $19 tier) attracts customers whose job-to-be-done isn't aligned with what you offer.

---

## What changes vs current assumptions

| Current                                | Recommended                              | Why                                              |
|----------------------------------------|------------------------------------------|--------------------------------------------------|
| $49 / $149 / $499 genre PDF tiers      | Single $499 Per-Genre Market Atlas       | $49 is too cheap; signals low quality, attracts pathological customers |
| No per-game paid product               | $99 Per-Game Decision Pack               | The killer use case; no competitor offers this   |
| No subscription tier                   | $79/mo Pro + $499/mo Studio              | Recurring revenue; competitive gap at $79 band   |
| No enterprise tier                     | Custom Enterprise (unpublished)          | Captures publisher/investor upside               |
| Tier 2 add-ons gated by triggers       | Subscription absorbs add-on use cases    | Triggers are confusing; flat unlimited is clean  |

The "Tier 2 add-ons gated by numerical triggers" idea (from the existing business model memo) was clever but adds cognitive load at purchase. Cleaner: the Pro subscription is unlimited everything; the trigger logic disappears.

---

## Revenue model (illustrative back-of-envelope)

Assume year-2 catalog of 1,000 covered games + 50 covered genres + organic SEO traffic.

| Source                          | Volume / month | Avg price | MRR |
|---------------------------------|----------------|-----------|-----|
| Per-Game PDFs                   | 50 sales       | $99       | $4,950 |
| Per-Genre Atlases               | 5 sales        | $499      | $2,495 |
| Pro subscriptions               | 100 active     | $79       | $7,900 |
| Studio subscriptions            | 8 active       | $499      | $3,992 |
| Enterprise                      | 2 active       | $4,000    | $8,000 |
| **Total MRR**                   |                |           | **$27,337** |

That's ~$328k ARR from a 1,000-game catalog with conservative conversion. The Pro subscription is the engine; the PDFs are the entry; Enterprise captures the upside.

Compare to current $49/$149/$499 PDF model: same 50 sales/mo at $49 average = $2,450 MRR. The new packaging is **>10× revenue** at the same volume.

---

## Risks and tradeoffs

1. **No $19 or $49 entry tier means losing some traffic to Gamalytic / GameDiscoverCo Plus.** That's intentional. Those customers are price-sensitive and high-support; let competitors have them.

2. **$79/mo is harder to convert than $19/mo.** True. But the conversion math from a $99 Decision Pack ("you've already spent $99; another $79 unlocks unlimited and Live tools") does the work.

3. **$499/mo Studio tier may seem high vs Gamalytic's $75/mo Pro.** Gamalytic's $75/mo doesn't include multi-seat, API, or report PDFs. The $499 is for a different buyer.

4. **Building Enterprise sales takes founder time.** Yes — but 2–5 enterprise contracts at $4k+/mo are 25%+ of revenue with low support burden once landed.

5. **Cannibalization risk between PDFs and Pro.** Actually a feature: the PDF is the entry point, the subscription is the destination. The math should clearly favor subscription for repeat users.

6. **Pre-launch we have no proof points.** Counter: launch the $99 Decision Pack first (single SKU, simplest), prove it sells, then layer on subscription. Don't build all 5 tiers day one.

---

## Suggested launch sequence

1. **Soft launch: free tier + $99 Per-Game Decision Pack.** One SKU. Prove people pay $99 for an automated decision pack. (~6 weeks)
2. **Add: $499 Per-Genre Market Atlas.** Once a few studios have bought Decision Packs, sell them the Atlas. (~4 weeks)
3. **Add: Pro $79/mo subscription.** When repeat PDF buyers emerge, give them the subscription option. The PDF anchors the price. (~6 weeks)
4. **Add: Studio $499/mo.** When a Pro customer asks for multi-seat or API, you have the tier ready. (~4 weeks)
5. **Add: Enterprise.** When an inbound publisher asks for custom data, take the meeting. Don't publish — quote.

Total to fully-staged packaging: ~5 months. But revenue starts from week 6.

---

## What the existing roadmap unlocks for which tier

Mapping the 31-feature `data-intelligence-roadmap.md` to the packaging:

| Feature                              | Free | $99 PDF | $499 PDF | Pro $79 | Studio $499 |
|--------------------------------------|------|---------|----------|---------|-------------|
| 1 Game Health Score                  | ✓    | ✓       | ✓        | ✓       | ✓           |
| 2 Review Pattern Signals (top 2)     | ✓    | ✓       | ✓        | ✓       | ✓           |
| 2 Review Pattern Signals (full)      |      | ✓       |          | ✓       | ✓           |
| 3 Archetype Clustering (label)       | ✓    | ✓       | ✓        | ✓       | ✓           |
| 3 Archetype Clustering (full sheet)  |      | ✓       | ✓        | ✓       | ✓           |
| 4 Genre-Space Map (small embed)      | ✓    | ✓       | ✓        | ✓       | ✓           |
| 4 Genre-Space Map (interactive)      |      |         | ✓        | ✓       | ✓           |
| 5 Time-to-Milestone (genre median)   | ✓    | ✓       | ✓        | ✓       | ✓           |
| 5 Time-to-Milestone (your projection)|      | ✓       |          | ✓       | ✓           |
| 6 Tag Association Rules (top 3)      | ✓    | ✓       | ✓        | ✓       | ✓           |
| 6 Tag Association Rules (full)       |      | ✓       | ✓        | ✓       | ✓           |
| 7 Niche Finder                       |      |         | ✓        | ✓       | ✓           |
| 8 Launch Window Optimizer            |      | ✓       | ✓        | ✓       | ✓           |
| 9 Hedonic Pricing (basic)            |      | ✓       |          | ✓       | ✓           |
| 9 Hedonic Pricing (full SHAP)        |      | ✓       |          | ✓       | ✓           |
| 10 Competitive Positioning (top 5)   | ✓    | ✓       | ✓        | ✓       | ✓           |
| 10 Competitive Positioning (top 50)  |      | ✓       |          | ✓       | ✓           |
| 11 Survival Curves                   |      | ✓       | ✓        | ✓       | ✓           |
| 14 Sentiment Predictor (badge)       | ✓    | ✓       | ✓        | ✓       | ✓           |
| 14 Sentiment Predictor (SHAP)        |      | ✓       |          | ✓       | ✓           |
| 15 Cohort Analysis                   |      | ✓       | ✓        | ✓       | ✓           |
| 17 Revenue Intelligence (Gini)       |      |         | ✓        | ✓       | ✓           |
| 19 Market Segmentation Map           |      |         | ✓        | ✓       | ✓           |
| 20 Feature Similarity                |      | ✓       |          | ✓       | ✓           |
| API access                           |      |         |          |         | ✓           |
| Multi-seat                           |      |         |          |         | ✓           |
| White-label                          |      |         |          |         | ✓           |

Free tier is rich enough to drive SEO; PDFs are decision-complete; subscriptions add tools/scale/collaboration. Each upgrade has a clear "why."

---

## Bottom line

The current $49/$149/$499 model is leaving money on the table at every level — too cheap for studios who'd pay $499/mo, missing the $99 per-game sweet spot for indies, and absent an enterprise tier. The packaging above is **denser revenue per customer, fewer pathological support cases, and aligned with how competitors price the adjacent market**.

The single most important move: **launch the $99 Per-Game Decision Pack first**. It's one SKU, the highest-value deliverable, and the price-anchor that makes everything else obvious. Everything else can layer on once it sells.
