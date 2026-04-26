# Free Tier Content Strategy for Unanalyzed Games

> **Status:** exploration. Companion to `monetization-strategy.md` (six-tier packaging) and `data-intelligence-roadmap.md` (sklearn + matview features). This doc answers: *"How do we make every game's free page worth someone's time when only a fraction get LLM analysis?"* And then: *"How do we present free vs paid?"*

## The problem

Catalog: 130k+ games. LLM analysis cost: ~$0.50–1/game even with the hybrid pipeline. We can't afford to analyze all of them. But the free tier is the SEO/discovery/trust engine — every game page needs to be substantive enough to:

- Rank in Google (avoid thin-content penalties: ≥500 unique words, ≥30% differentiation)
- Be share-worthy (someone tweets a link)
- Establish expertise (visitors trust SteamPulse)
- Convert browsers → $99 Decision Pack buyers (or Pro subscribers)

The good news: most of `data-intelligence-roadmap.md` runs on every game from structured data + sklearn alone. **No per-game LLM cost.** The gap is qualitative content ("what reviewers actually say") for games we haven't LLM-analyzed.

## The strategy in one sentence

Every game gets a rich free page from sklearn + structured data + cleverly-presented review excerpts; LLM analysis runs **on-demand when someone buys the $99 Decision Pack** (self-funding); pre-analyze the catalog top-N for SEO + Pro subscribers ahead of demand.

## Two-state model

```
   ┌──────────────────────────────────────────────────────────────┐
   │ STATE A — UNANALYZED (default for ~99% of catalog)           │
   │                                                                │
   │ Free page: structured data + sklearn + review excerpts       │
   │ Paid page (Decision Pack): same as free + LLM analysis        │
   │ Trigger: purchase → run LLM analysis → deliver in ~10 min     │
   └──────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ STATE B — ANALYZED (wedge + featured + previously-purchased) │
   │                                                                │
   │ Free page: same sklearn content + LLM teaser (top-3 only)    │
   │ Paid page (Decision Pack): same as free + full LLM           │
   │ Trigger: purchase → instant download                          │
   └──────────────────────────────────────────────────────────────┘
```

Free page **looks identical structurally** in both states. Visitors don't see "analyzed" vs "unanalyzed" branding. The difference is only visible at the moment of purchase: instant delivery vs ~10-minute wait.

## The free page — anatomy of every game

```
   ┌───────────────────────────────────────────────────────────────────┐
   │ HEADER                                                             │
   │ ┌──────────┐  Game Name (Developer)                                │
   │ │  HEADER  │  ★★★★☆  84% positive (12,450 reviews) · $24.99       │
   │ │   IMAGE  │  Released Mar 2024 · Roguelike · Deckbuilder          │
   │ └──────────┘                                                       │
   │                                                                    │
   │ [HEALTH SCORE: 87/100]  [HIDDEN GEM]  [OVERPERFORMER +9pp vs tags]│
   │ Archetype: "Story-driven roguelike with heavy meta-progression"    │
   ├───────────────────────────────────────────────────────────────────┤
   │ MAP                                                                │
   │ Position on the genre-space map (small interactive embed)          │
   │ ◯ ◯ ◯ ◯ ◯       ← you-are-here marker                            │
   │ ◯ ◯ ★ ◯ ◯       Cluster: Narrative Roguelike                     │
   │ ◯ ◯ ◯ ◯                                                            │
   ├───────────────────────────────────────────────────────────────────┤
   │ AT A GLANCE (5–7 numeric badges from data-intelligence layer)     │
   │ • Sentiment trend: ↗ Improving (last 90d: 89% positive)            │
   │ • Review velocity: 47/week (vs cohort median 22/week, +114%)       │
   │ • Refund-window risk: 3.2% of negatives < 2hr playtime (LOW)      │
   │ • Engagement cliff: 73% of players reach 8h+ (cohort: 41%)         │
   │ • Time to 1,000 reviews: month 7 (your cohort P50: month 11)       │
   │ • Free-key sentiment delta: +1pp (no inflation)                    │
   │ • EA loyalty: 64% of EA reviewers have 100h+                       │
   ├───────────────────────────────────────────────────────────────────┤
   │ WHAT REVIEWERS EMPHASIZE (sklearn-derived)                         │
   │                                                                    │
   │ Most-discussed topics (from review clustering):                    │
   │ ┌─ Topic 1: Art and visual design (n=892 mentions, 96% positive) │
   │ │  "The hand-drawn art style is genuinely beautiful…"             │
   │ │  "Every card looks like it belongs in a museum…"                │
   │ │  "Visual polish carries the early game when mechanics are…"     │
   │ ├─ Topic 2: Difficulty curve (n=634, 71% positive, 29% friction) │
   │ │  "The first 3 runs feel impossible but click around run 5…"   │
   │ │  …                                                              │
   │ └─ Topic 3: Run length (n=412, 58% positive)                     │
   │    …                                                              │
   │                                                                    │
   │ Tag votes: Roguelike (1,234) · Deckbuilder (892) · Strategy (445) │
   │           Story Rich (234) · Difficult (198) · Indie (167)        │
   ├───────────────────────────────────────────────────────────────────┤
   │ TOP REVIEWS (highest helpful-vote count)                           │
   │ ┌─ ✓ POSITIVE  47h playtime · 312 helpful votes                   │
   │ │  "I've tried every roguelike-deckbuilder since Slay the Spire…" │
   │ ├─ ✗ NEGATIVE  4h playtime · 189 helpful votes                    │
   │ │  "Refunded after the third boss — the difficulty spike feels…" │
   │ └─ ✓ POSITIVE  121h playtime · 156 helpful votes                  │
   │    "After 100 hours I've unlocked everything and want more…"     │
   ├───────────────────────────────────────────────────────────────────┤
   │ COMPETITIVE LANDSCAPE                                              │
   │ Players of this game also play:                                    │
   │ 1. Slay the Spire    (78% audience overlap, 96% positive, $24.99)│
   │ 2. Monster Train     (62% overlap, 95% positive, $24.99)          │
   │ 3. Inscryption       (54% overlap, 96% positive, $19.99)          │
   │ 4. Balatro           (47% overlap, 97% positive, $14.99)          │
   │ 5. Roguebook         (38% overlap, 81% positive, $24.99)          │
   ├───────────────────────────────────────────────────────────────────┤
   │ LIFECYCLE / SURVIVAL                                               │
   │ Time-to-milestone (your archetype):                                │
   │   100 reviews:   month 1 (you reached at month 0.8) ✓             │
   │   1,000 reviews: month 7 (you reached at month 5) ✓               │
   │   10,000 reviews: month 24 (P50) — you're tracking ahead          │
   │                                                                    │
   │ Survival curve (% of cohort still active at month T):              │
   │   month 6:  78% [genre median] · 95% [you] ✓                      │
   │   month 12: 54% [genre] · projected 82% [you]                     │
   │   month 24: 28% [genre] · projected 61% [you]                     │
   ├───────────────────────────────────────────────────────────────────┤
   │ 🔒 GO DEEPER                                                       │
   │ Get the full Decision Pack — $99 one-time                          │
   │  ✓ Full review analysis (themes, friction, dev priorities)        │
   │  ✓ Hedonic price model (your fair value: ?, vs actual $24.99)     │
   │  ✓ 50-competitor positioning (vs 5 free)                          │
   │  ✓ Survival projection with feature drivers                        │
   │  ✓ Anomaly explanation (why you're an Overperformer)              │
   │  ✓ Audience profile + dev priorities                               │
   │  ✓ Exportable PDF · 30-day money-back guarantee                    │
   │                                                                    │
   │ [Get the Decision Pack →]   or   [Pro: $79/mo unlimited]          │
   │                                                                    │
   │ Sample Decision Pack (Slay the Spire) →                            │
   └───────────────────────────────────────────────────────────────────┘
```

That's ~600 unique words of structured data + sklearn-derived content per game, well over the ≥500 SEO threshold and high-differentiation per game (every number is genuine).

## Sklearn-derived qualitative content (the "themes" gap-filler)

The hardest part is filling the qualitative gap — "what reviewers say" — without LLM. Three layered techniques:

### 1. Top helpful reviews by vote count (no ML, instant)

`SELECT body, voted_up, playtime_hours, votes_helpful FROM reviews WHERE appid=? ORDER BY votes_helpful DESC LIMIT 10` — split positive/negative. Show the top 3 of each. This is what Steam already shows but you present cleaner with playtime + helpfulness context.

**Why it works:** community-validated quotes carry their own credibility.

### 2. HDBSCAN review clusters + cluster reps (no LLM, periodic)

For each game with ≥50 reviews:
- Embed reviews with `sentence-transformers/all-MiniLM-L6-v2` (already-cached embeddings if Stage 1 of `analysis-pipeline-sklearn-hybrid.md` ships)
- HDBSCAN cluster (min_cluster_size=10)
- Per cluster: pick 1-2 representative quotes (centroid distance × helpfulness)
- Show 3–5 clusters with topic labels + sample quotes

**Topic labeling without per-game LLM:** Run **one LLM call per genre** (~$1/genre × 50 genres = $50 total) that produces a taxonomy of typical clusters for the genre ("Visual design", "Difficulty curve", "Run length", "Boss design", "Music", "Story", "Replayability"). Each game's clusters get matched to the nearest taxonomy item by centroid embedding distance.

**Result:** every game has 3–5 labeled themes with quote evidence. No per-game LLM cost.

### 3. TF-IDF + RAKE keywords (no ML, periodic)

`TfidfVectorizer` over game's review corpus + `rake-nltk` for multi-word phrases. Top 10 keywords/phrases. Surface as "Reviews emphasize: [keyword cloud]" or as a tag-vote complement.

**Cross-cut with sentiment:** keywords from positive reviews vs keywords from negative reviews. Often surfaces friction patterns directly ("crashes", "matchmaking", "balance").

---

These three layers together produce qualitative content for every game that's genuinely substantive — not slop, not template-filled. A reader gets clear themes with real quote evidence.

## Free vs paid — the feature matrix

| Section                              | Free (every game)                          | $99 Decision Pack (this game)                          | $79/mo Pro (any game) |
|--------------------------------------|---------------------------------------------|---------------------------------------------------------|------------------------|
| Header + game stats                  | ✓                                           | ✓                                                       | ✓                      |
| Health Score                         | ✓ (number + badge)                          | ✓ + breakdown of 5 components                           | ✓ + breakdown          |
| Archetype label                      | ✓ (name only)                               | ✓ + full archetype profile sheet                        | ✓ + profile            |
| Genre-space map                      | ✓ (small embed, you-are-here)              | ✓ + nearest 50 with distance + interactive              | ✓ + interactive        |
| At-a-glance numeric badges           | 5–7 top-line                                | ✓ + drill-down per metric                               | ✓ + drill-down         |
| Review themes (sklearn clusters)     | Top 3 themes, 1 quote each                  | All themes (5–10), 3 quotes each, sentiment breakdown   | Same                   |
| LLM `GameReport` themes              | 🔒 Top 1 strength teased                    | ✓ Full prose: design strengths, gameplay friction, audience profile, dev priorities (5 ranked actions with effort estimates) | Same |
| Helpful review quotes                | Top 3 positive + top 3 negative             | Top 10 each, sortable by playtime/votes/recency         | Same                   |
| Tag votes                            | Top 6                                       | All tags ranked + tag-sentiment cross-cut               | Same                   |
| Audience-overlap competitors         | Top 5                                       | Top 50 with all dimensions (price, sentiment, velocity, deck, achievements, revenue, tag overlap) | Same |
| Feature-similarity neighbors         | (not shown free)                            | Top 20 with distance breakdown                          | Top 20                 |
| Sentiment trend                      | Direction + 90-day delta                    | Full timeline + change-point detection                  | Full timeline          |
| Review velocity                      | Current vs cohort median                    | Full timeline vs cohort                                 | Full timeline          |
| Time-to-milestone                    | Your progress + cohort P50                  | P10/P50/P90 bands + your projection                     | Same                   |
| Survival curve                       | Cohort median + your status                 | Cohort + your projection + Cox feature drivers          | Same                   |
| Hedonic fair-value                   | "Overperformer" or "Fairly priced" badge    | Predicted price + 25/75 band + SHAP top-5 features      | Same                   |
| Sentiment over/underperformance      | Badge ("Overperformer +9pp")                | Predicted % + actual + top-3 driver features            | Same                   |
| Anomaly flags                        | Badge ("Hidden Gem")                        | Full anomaly score + dimensions where anomalous          | Same                   |
| Cohort z-score                       | (not shown free)                            | Your z-score + percentile within cohort                  | Same                   |
| Refund risk + engagement cliff       | Top-line numbers                            | Full distribution + drill-down                          | Same                   |
| Vocabulary fingerprint               | (not shown free)                            | Cosine distance from genre + missing concepts + over-used terms | Same        |
| Tag association rules                | Top 3                                       | Full rules + lift scores                                | Same                   |
| Helpfulness skew, funny-vote anomaly | (not shown free)                            | All review pattern signals                              | Same                   |
| Exportable PDF                       | ✗                                           | ✓                                                       | ✓ (any game, anytime)  |

The free tier delivers ~80% of the structured signal value. The Decision Pack delivers the **interpretation** (LLM prose), the **depth** (50 vs 5 competitors, full SHAP), the **projection** (your survival curve vs cohort median), and the **artifact** (PDF). That's the structural difference, not "more of the same."

## Conversion mechanics

### Strategic friction (visible locked content converts better)

Every locked section shows enough to demonstrate value: the badge alone for the LLM prose ("Top strength: Visual design — see 4 more"), the 5 competitors for audience overlap ("see all 50 in Decision Pack"). **Hidden locked content converts worse than visible locked content.** Don't hide; tease.

### Sample Decision Packs (3 publicly viewable)

Pick 3 well-known games (e.g., Slay the Spire, Hades, Vampire Survivors). Run full LLM analysis. Publish the full Decision Pack PDF for free download. Anyone considering a $99 purchase can see exactly what they'd get for *another* game.

This is the single highest-impact trust move. Without it, $99 is a leap of faith. With it, $99 is a known quantity.

### On-demand analysis pitch

For unanalyzed games, the CTA is:

> "Analysis runs in ~10 minutes after purchase. We'll email your PDF link as soon as it's ready. Money-back guarantee if you're not satisfied within 30 days."

For analyzed games (wedge + featured + previously-purchased):

> "Instant download. Sample Decision Pack →"

The 10-minute wait is acceptable for a $99 purchase — analogous to print-on-demand books — and the email delivery removes the staring-at-a-spinner anxiety.

### Anchor pricing visible at every CTA

```
   [Get this game's Decision Pack — $99]
   
   Or unlimited Decision Packs + live tools: Pro at $79/mo
                       (1 game/mo and you save)
```

The math sells the subscription itself.

## On-demand LLM economics

```
   Decision Pack price:              $99.00
   Stripe fee (2.9% + $0.30):       -$3.17
   LLM analysis cost (avg):         -$0.75
   PDF generation + S3 + email:     -$0.05
   ────────────────────────────────────────
   Net per Decision Pack sale:       $95.03  (96% gross margin)
```

A single Decision Pack sale funds ~125 game analyses worth of LLM cost. Self-funding is a comfortable understatement.

## Pre-analysis strategy (which games get LLM ahead of demand)

Three triggers for pre-analyzing a game without a purchase:

1. **Wedge games (operator-curated):** the active wedge (roguelike-deckbuilder, 141 games per `project_wedge_and_budget.md`). Pre-analyze all of them. ~$70 investment for the seed catalog.

2. **Pro subscriber watchlist:** when a Pro subscriber adds a game to their watchlist, queue it for analysis. They're paying $79/mo; the $0.75 analysis cost is amortized. Caps + rate limits prevent abuse.

3. **Traffic-driven (operator-decided, monthly):** look at Plausible page-view data; for any game page with >100 monthly views, queue analysis. SEO converts better when the page has rich LLM content.

Pre-analysis is a marketing investment; on-demand analysis is a unit-economics-aligned product feature. Both coexist.

## SEO architecture

Every free page must clear these bars to not be a thin-content liability:

- **Word count:** ≥500 unique words from real data per page. Achievable with the layout above.
- **Differentiation:** ≥30% per page. Every number is genuinely different per game; cluster quotes are unique; competitor lists differ.
- **Schema.org markup:** `VideoGame` schema with name, developer, publisher, genre, contentRating, applicationCategory, aggregateRating (review count + positive_pct), offers (price). Powers rich snippets in Google.
- **Internal linking:** archetype neighbors (5), audience-overlap competitors (5), genre page, dev portfolio page. ~20 outbound internal links per game page.
- **Canonical tags:** prevent duplicate-content issues across slug variants.
- **Sitemap:** auto-regenerated daily; submitted to Google Search Console.

## Trust and risk handling

- **Sample Decision Packs** as described above (3 publicly viewable).
- **30-day money-back guarantee.** Cost: a refund is $99 lost + maybe LLM cost ($1) — manageable.
- **Methodology page:** how we compute Health Score, what the survival curve assumes, where the data comes from. Builds expertise signal.
- **No "AI-generated" branding for the LLM content.** The reader cares whether it's accurate, not how it was made. Phrase as "Our analysis."
- **Quality floor on LLM analysis:** if a game has <50 reviews, the LLM has thin source material. Either gate Decision Pack purchases at a review-count floor, or warn ("Analysis depth is limited for games with <50 reviews; consider waiting until X reviews accumulate"). Refund risk is highest here.

## Critical files / implementation outline

| Purpose                         | Path / change                                                                  |
|---------------------------------|---------------------------------------------------------------------------------|
| Analysis state flag             | `games.analysis_state ENUM('unanalyzed','queued','analyzed','failed')`        |
| On-demand trigger endpoint      | `POST /api/games/{appid}/analyze` (called by Stripe webhook on Decision Pack purchase) |
| Pre-analysis batch              | New scheduled Lambda: scans Plausible analytics, queues high-traffic games    |
| Cluster taxonomy per genre      | One-time Lambda per genre; outputs `genre_cluster_taxonomy` table              |
| Per-game review clustering      | Stage 1+2 of `analysis-pipeline-sklearn-hybrid.md` — ships embeddings + clusters as a side-effect |
| Tier-aware page renderer        | `frontend/components/GamePage.tsx` — single component, props flag locked/unlocked sections |
| Sample Decision Pack publisher  | New script + S3 bucket; 3 sample PDFs hosted with public URLs                  |
| Stripe webhook → analysis trigger | `lambda_functions/stripe_webhook/handler.py` — on Decision Pack purchase, call analyze endpoint |
| Refund handler                  | Stripe webhook handles refund; PDF revoked (signed URL expires)                |

## Open questions

1. **What's the right cluster taxonomy granularity per genre?** Too few labels (3) loses nuance; too many (15) makes matching unreliable. Tune empirically.

2. **How do we handle games with <50 reviews?** Cluster step needs a floor. Below that, the page falls back to Top Helpful Reviews + structured data only. Decision Pack purchase: warn or block?

3. **Cold-start subscriber retention:** if a Pro subscriber's first month they only download 2 Decision Packs ($158 value vs $79 paid), great. If they download 30 in month 1 and zero in month 2, churn risk. Worth measuring once live.

4. **Sample Decision Pack selection:** which 3 games? Probably one mid-tier indie (relatable), one well-known indie (Slay the Spire), one AAA-ish (so studio buyers see the depth). Worth A/B testing.

5. **Should the pre-analysis batch use the cheaper sklearn-hybrid pipeline or full LLM?** Cheaper for pre-analysis (the cost matters); full quality for purchase-triggered analysis (the customer paid for it).

## Recommended next step

Before building anything, **publish 1 sample Decision Pack PDF** for an existing roguelike-deckbuilder wedge game. Treat it as the proof-of-concept artifact. Use it to:

- Validate the page anatomy resonates
- Test the conversion narrative ("would I pay $99 for this?")
- Calibrate LLM analysis quality
- Inform what to lock vs reveal

Until that PDF exists, all of the above is theoretical. Once it exists, the rest of the implementation gets concrete fast.

## Tieback to packaging

This proposal validates the `monetization-strategy.md` six-tier model:

- **Free** is genuinely substantive on every game (no thin-content risk)
- **$99 Decision Pack** delivers structurally different value (LLM prose, depth, exports)
- **$79/mo Pro** is obvious math for repeat buyers (1 game/mo and it's free)
- **$499/mo Studio** absorbs Genre Atlases + multi-seat
- **Enterprise** stays bespoke

The on-demand-analysis model is what makes the catalog economics work. Every game gets a free page worth visiting; every paid game gets full analysis; nothing else has to.
