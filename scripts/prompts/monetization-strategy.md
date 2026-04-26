# Monetization strategy — six-tier packaging

This document is the canonical strategic reference for pricing, product boundaries, and tier structure. Keep consistent with `steam-pulse.org` (Active Launch Plan) and the `project_business_model_2026.md` memory. When any of these three disagree, `steam-pulse.org` is the source of truth.

## Operating criterion — asynchronous transactions

Every surface, tier, and feature must support the full transaction flow asynchronously: a buyer can discover, sign up, pay, and receive value without operator real-time involvement. Stripe Checkout, S3 signed-URL delivery, recurring subscriptions, and scheduled email all qualify. Live sales calls, custom-quoted proposals, and any "hop on a call before you can buy" flow do not — except at the Enterprise tier (see below), which is intentionally bespoke.

This is not a constraint on operator labour itself — content production, editorial, and community work can require ongoing effort as long as the *transaction* closes async.

## The tier ladder

| Tier              | Product                                | Price            | Job-to-be-done                                                      |
|-------------------|----------------------------------------|------------------|----------------------------------------------------------------------|
| **Free**          | Every game page (SEO-indexed)          | $0               | Discovery, brand, traffic, virality                                  |
| **Per-Game PDF**  | Decision Pack (one-time)               | **$99**          | "Should I make / price / launch this game?"                          |
| **Per-Genre PDF** | Market Atlas (one-time)                | **$499**         | "Should we enter this genre? What's the market structure?"           |
| **Pro Sub**       | Studio Pass for indies                 | **$79/mo · $790/yr** | "Ongoing competitive intel + unlimited Decision Packs"           |
| **Studio Sub**    | Multi-seat + API + atlases included    | **$499/mo · $4,990/yr** | "Publisher / mid-studio depth + team usage"                  |
| **Enterprise**    | Custom (don't publish price)           | $2k–$10k+/mo     | M&A screening, weekly delivered intel, white-glove                   |

Each tier has a distinct buyer. No tier cannibalises the next. The one-time PDF anchors the subscription ("$99/game OR $79/mo unlimited" is obvious math for repeat users).

## Free vs paid — landscape vs plan

Free surfaces and paid surfaces answer **different questions**, not the same question with more items behind a paywall. The structural difference is what justifies the price — never the count of items 6–10.

- **Free** = landscape. *"What does the data show?"* Top-N headlines, the archetype label, the health score, named-author byline, basic charts. Aggregated, factual, shareable, SEO-indexed.
- **Paid** = plan. *"What should I do?"* Full model output (hedonic price prediction with confidence band, survival projection, 50-competitor positioning, SHAP feature importance), strategic recommendations, opinionated analyst output, exports.

Curation on the free page is load-bearing: Google's March 2026 core update demotes mass-produced AI content without human editing or named-expert attribution, and the anti-cannibalisation rule is that AI assistants should be able to *cite* the free page but not *finish* the buyer's question from what's public.

## Tier detail

### Free — every game page

**Content:** Game card with health score, archetype label, top-3 strengths and frictions (LLM excerpt), 5 audience-overlap competitors, genre-space map position (small embed), genre-median time-to-milestone, hidden-gem flag. Public, indexable, shareable.

**Why generous:** Every indie dev googles their own game and competitors. Rich free pages earn discovery. This is the customer acquisition channel — not a customer-success tier.

### Per-Game Decision Pack — $99 one-time

**Buyer:** Solo indie dev, marketer prepping a launch, consultant doing client research.

**Content (single game, comprehensive):**
- Full LLM `GameReport` (all sections, no truncation)
- Hedonic fair-value with confidence band + SHAP feature importance
- Survival curve for archetype + projected lifecycle position
- Time-to-milestone with P10/P50/P90 bands vs cohort
- 50-competitor positioning (audience-overlap + feature-similarity)
- Top association rules for tag combo
- Vocabulary fingerprint vs genre norms
- Anomaly flags + sentiment over/underperformance with feature drivers
- Cohort z-score
- Genre-space map with target game pinned

**Sales hook:** "Replaces a $1,500 pricing study. Read it tonight."

**Why $99:** It's one consultant hour, one Steam asset purchase. Painless for anyone with a real game in development. A $19/$49 floor signals "amateur tool" and attracts customers who'll generate disproportionate support load. $99 says serious.

### Per-Genre Market Atlas — $499 one-time

**Buyer:** Studio strategy lead, publisher acquisition team, investor analyst.

**Content (single genre, comprehensive):**
- LLM `GenreSynthesis` (cross-game themes, friction patterns, dev priorities)
- Genre-space 2D map of all genre members (hero visual)
- Niche opportunities (white-space tag combos)
- Launch window optimizer (when to ship in this genre)
- Tag association rules (synergies + anti-patterns)
- Cohort trajectories per release year
- Genre identity drift (year-on-year)
- Survival curves by archetype
- Revenue concentration (Gini + top-10% share)
- Top 25 games, top 10 developers, top 10 franchises with trajectories

**Why $499:** A greenlight committee can expense it. A consultant can mark it up. It replaces a $5k–$15k study from a research firm. At $499 it's "yes" without committee approval.

### Pro — $79/mo or $790/yr

**Buyer:** Solo devs and 2–10 person studios with active development.

**Content:**
- Everything in Free
- **Unlimited Per-Game Decision Pack downloads** on any game
- Live dashboards (vs static PDFs)
- Interactive Niche Finder, Launch Window Optimizer, Hedonic Pricing tool
- Save/track: portfolio of "watched" games + competitors
- CSV export
- Email digest (weekly genre summary)
- Email alerts when competitor sentiment shifts (when alerting infra exists)

**Anchoring math:** "$99 per game OR $79/mo for unlimited." Anyone analysing >1 game per month picks the sub. This is the primary conversion engine.

**Annual:** $790/yr = 2 months free. Drives prepay.

### Studio — $499/mo or $4,990/yr

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

**Anchoring math:** "$499 per Atlas OR $499/mo for unlimited Atlases + Pro for the whole team."

### Enterprise — custom

**Buyer:** VCs, M&A teams, big publishers, strategic acquirers.

**Content:**
- Custom data pulls + bespoke reports
- Acquisition target screening (anomaly detection cross-catalog)
- Weekly/monthly delivered intelligence packets
- White-glove onboarding + dedicated contact
- Embargo on data publication for sensitive deals

**Pricing:** $2k–$10k+/mo, negotiated. Don't publish the price; the opacity is the signal.

## Pricing rationale

1. **The $79–$499/mo band is the competitive gap.** GameDiscoverCo Plus tops at $19/mo; Gamalytic Pro at $75/mo; Sensor Tower / Pitchbook jump to enterprise. Nobody serves serious-indie / small-studio analytics in this band — that's where SteamPulse's differentiated data (audience overlap + ML modeling + LLM reports) actually justifies real money.

2. **Floor at $99 (skip $19/$49 entry tiers).** Lower price points attract customers whose support burden exceeds their LTV and signal a low-quality product. A $99 floor selects for serious buyers.

3. **One-time PDFs anchor the subscriptions.** Visible per-unit pricing makes the subscription's unit-economics self-evident.

4. **Information products price by decision value, not data cost.** A $99 Decision Pack supports a $20k–$200k bet. A $499 Atlas supports a $500k–$5M strategic call. The price is rounding error to the buyer.

5. **Single-SKU PDFs preserve the async-transaction property.** No tier selector, no contact form, no manual scoping. One Stripe Checkout per artifact.

6. **Skip the legacy $49/$149/$499 PDF tiers.** SaaS-style segmentation grafted onto one-off PDFs added implementation surface without validated willingness-to-pay. The new tier structure separates one-off from subscription cleanly: PDFs are atomic decisions; subs are ongoing tooling.

## Launch sequence

Each phase gates the next. Don't build downstream tiers before upstream tiers prove out.

| Phase | Window     | Ships                                                              | Revenue signal                |
|-------|------------|--------------------------------------------------------------------|--------------------------------|
| **A** | Week 1     | Free per-game pages live (SEO-indexed)                             | None (traffic only)           |
| **B** | Week 2–6   | $99 Per-Game Decision Pack — single SKU, one Stripe button         | First PDF revenue lands        |
| **C** | Week 6–10  | $499 Per-Genre Market Atlas — second SKU                           | First Atlas sale               |
| **D** | Week 10–16 | Pro $79/mo subscription                                            | First MRR                      |
| **E** | Week 16–20 | Studio $499/mo subscription                                        | First multi-seat MRR           |
| **F** | Inbound    | Enterprise — accept calls when publishers email                    | First custom-quote             |

**Phase A** is the SEO foundation: every game in the catalog gets a public page rich enough that Google indexes it and devs share it. No payment, no email capture.

**Phase B** is the killer experiment. Single SKU, single button. Ship the Decision Pack PDF and see if anyone pays $99. The deliverable is intentionally small in scope — one game's analysis — so it's a tight loop. **If 30 days of Phase B yields zero $99 sales, the price, the positioning, or the product-shape is wrong; iterate before building Phase C.** Pre-orders are an acceptable Phase B signal if the PDF isn't ready yet (Stripe webhook captures payment immediately; delivery worker holds the S3 URL until ship date).

**Phase C** adds the Atlas only after the Decision Pack proves the willingness-to-pay shape.

**Phase D** introduces the Pro subscription once a few buyers have purchased multiple Decision Packs (the natural moment to offer "$79/mo for unlimited").

**Phase E** introduces Studio when a Pro customer asks for multi-seat or API.

**Phase F** is reactive — don't pursue Enterprise outbound. Take the meeting when it comes.

## Architecture

- **Payment:** Stripe Checkout (one-off for PDFs, recurring for subs). See `stripe-checkout-report-delivery.md`.
- **Delivery (PDFs):** S3 signed URL emailed on successful webhook. No account, no login, no portal for one-off buyers.
- **Account (subs):** lightweight account for Pro/Studio with seat management, watchlist, alert prefs.
- **Content engine:**
  - Per-game PDF source: LLM `GameReport` pipeline (chunk → merge → synthesise) + data-intelligence layer (`data-intelligence-roadmap.md`)
  - Per-genre PDF source: cross-genre synthesiser matview + data-intelligence layer
- **Pricing display:** per-tier landing pages with comparison table; transparent prices on Free/PDF/Pro/Studio; "Contact us" on Enterprise.

## Operator load

- **Per Decision Pack PDF (automated):** ~$1 LLM cost (or ~$0.50 once sklearn-hybrid pipeline lands), zero hands-on. Pure margin at $99.
- **Per Atlas PDF:** ~$3–5 LLM (Phase 4 synthesiser + cross-game), ~10–20 hours editorial polish for the first few; can drop to ~5 hours with templates.
- **Pro/Studio sub support:** assume ~30 min/customer/month for the first 50 customers; templated FAQ + self-serve docs reduce thereafter.
- **Enterprise:** highly variable. Each contract is a small project.

## Revenue realism

Year-2 illustrative back-of-envelope, conservative conversion against a 1,000-game catalog + 50 covered genres + organic SEO traffic:

| Source                          | Volume / month | Avg price | MRR     |
|---------------------------------|----------------|-----------|---------|
| Per-Game PDFs                   | 50 sales       | $99       | $4,950  |
| Per-Genre Atlases               | 5 sales        | $499      | $2,495  |
| Pro subscriptions               | 100 active     | $79       | $7,900  |
| Studio subscriptions            | 8 active       | $499      | $3,992  |
| Enterprise                      | 2 active       | $4,000    | $8,000  |
| **Total MRR**                   |                |           | **~$27,300** |

That's ~$328k ARR. The Pro subscription is the engine; PDFs are the entry; Studio + Enterprise capture upside. Year 1 will be much smaller while phases stage in — modelling target is $5k–$30k Year 1.

## Verification — what "working" looks like

### Phase A signals (first 30 days after free pages live)

- **Plausible** shows ≥ 20 sessions/day from SEO + one amplification event by week 2
- **Lighthouse SEO** ≥ 90 on a random sample of per-game pages
- ≥ 100 game pages indexed by Google within 14 days of sitemap submission

### Phase B signals (first 30 days after $99 Decision Pack live)

- **First paid sale at $99** — existence proof
- **Stripe checkout conversion** from per-game page → Decision Pack > 0.5%
- **S3 signed-URL delivery** fires correctly on 100% of paid sales (webhook retry handled)

### Phase D signals (first 30 days after Pro sub live)

- **First MRR** — existence proof
- **Conversion from repeat PDF buyers to Pro** > 10%
- Pro churn < 5% in month 1

### Narrative / copy check

- Marketing copy reads as "landscape vs plan," not "free top-5 vs paid top-10"
- No "Indie / Studio / Publisher" persona naming on free or PDF pages (those terms only appear at subscription-tier signup)
- Free per-game pages contain landscape content only (no Decision Pack content leaked publicly)

## Market anchors

Reference only — competitive gap analysis behind the pricing.

- [GameDiscoverCo Plus](https://plus.gamediscover.co/) — $19/mo individual, $190/yr, $1,000/yr company. Newsletter cadence; SteamPulse competes on per-niche depth + tooling.
- [Gamalytic](https://gamalytic.com/pricing) — Starter $25/mo, Pro $75/mo. Breadth platform, no LLM intelligence, no audience-overlap depth.
- [VGInsights](https://vginsights.com/) — indie ~$20/mo (acquired by Sensor Tower 2025; enterprise pricing implicit above).
- [GG Insights](https://www.gginsights.io/) — freemium + lifetime-deal anchor.
- [Crunchbase Pro](https://www.crunchbase.com/) — $588/yr. Reference for affordable data-product subscription anchor.
- [Pitchbook](https://pitchbook.com/) — $12k–$40k/user/yr. Reference for enterprise-only premium data product (don't publish prices).
- [Bloomberg Terminal](https://www.bloomberg.com/professional/) — $20k–$25k/user/yr. Reference for premium data terminal positioning.
- [Lenny's Newsletter](https://www.lennysnewsletter.com/) — $200/yr, 4–5% paid conversion. Reference for one-tier subscription scale.
- [Stratechery](https://stratechery.com/) — $120/yr, 26k paid. Reference for one-tier research-subscription scale.
- [Chris Zukowski Wishlist & Visibility Masterclass](https://www.progamemarketing.com/p/visibility-and-wishlist-masterclass) — $400 course. Reference for indie-dev willingness-to-pay on one-off info products.
