# Monetization strategy — committed direction for launch

## Context

SteamPulse is about to launch and needs a committed monetization strategy. Two realities
shape every option:

1. **The market is saturated in per-game AI review analysis as of 2026-04.** Datahumble,
   Steam Sentimeter, HowlRound, SteamReview AI, LEYWARE, Steam Summarize — and as of this
   research pass, **GG Insights** (positioning itself as "trusted by 1000+ game developers,"
   50k+ game Steam dataset + AI chat). Direct head-to-head on "we synthesise a single
   game's reviews" is a losing commodity fight. The wedge differentiator is
   **cross-genre synthesis at depth** (currently roguelike-deckbuilder; expansion path in
   `steam-pulse.org` → Wedge Strategy).

2. **Catalog-wide coverage is neither needed nor tried.** Running the three-phase analyzer
   across ~20,000 eligible Steam games at ~$1/report would cost ~$20K and is not the
   product. The product is **depth in chosen wedges**. The active wedge is 141 games
   (~$141 of analysis). Extending to ten wedge genres is order-of-magnitude ~$1,500
   total — trivially fundable by Pro MRR once it exists. Previous drafts of this doc
   framed a "$20K backfill problem." That framing was wrong: we never needed to cover
   the catalog.

The existing launch plan already has Pro gating plumbing (`NEXT_PUBLIC_PRO_ENABLED`,
`usePro()` hook, `/api/validate-key` stub, blur + overlay CTA patterns) and a packaging
principle (`memory/feedback_packaging_principle.md` — free = publishable insight,
Pro = toolkit to ask your own questions). Payment integration is deferred;
`auth0-authentication.md` sits in the Backlog. This document is the **committable
direction** so landing-page copy, the `/pro` page, and waitlist messaging can all be
written *now* against a real target, not a placeholder.

Research re-verified 2026-04-16; re-verify pricing claims before committing publicly.

## Market reconnaissance (verified 2026-04-16)

| Competitor | Model | Free tier | Paid tier(s) |
|---|---|---|---|
| **Gamalytic** | Subscription | Game list, basic stats | **Starter $25/mo**, **Pro $75/mo** |
| **GameDiscoverCo Plus** | Newsletter + data platform | Free weekly newsletter | **Individual $15/mo ($150/yr)**, **Company $500/yr** (20+ employees) |
| **GG Insights** *(new — not previously surfaced)* | Freemium + lifetime deal | Free (10 chat credits/mo, CSV downloads) | **$64.35 one-time** (early-bird lifetime; regular $99) |
| **GameAnalytics Indie Program** | Subscription | Free tier | **$99/mo** (locked 12 mo) |
| **VGInsights** | Absorbed into Sensor Tower | — | Enterprise-only |
| **Steam Sentimeter** | Free (research/portfolio) | Full | — |
| **HowlRound, SteamReview AI, LEYWARE, Steam Summarize** | Indie-dev SaaS | Limited trials | Not publicly priced |
| **Perplexity** (reference SaaS) | Freemium + credits | 5 Pro queries/day | Pro $20/mo, Max $200/mo |
| **AppTopia** (reference — enterprise floor) | Enterprise | — | **From $2,000/mo** |

**Price anchors in this category (ladder, from the data):**

- **$15/mo** — GameDiscoverCo Plus individual. Psychological bottom for paid indie-dev tools.
- **$25/mo** — Gamalytic Starter. Solo-dev "real tool" anchor.
- **$42/mo equiv** — GameDiscoverCo Plus company plan ($500/yr / 12).
- **$75/mo** — Gamalytic Pro. Pro-grade / small-studio ceiling for self-serve tools.
- **$99/mo** — GameAnalytics Indie Program. Another ~$100 ceiling.
- **$2,000/mo+** — AppTopia. True enterprise floor (out of scope).

**2026 freemium conversion benchmarks (updated from sources):**
- Median ~8% free→paid across SaaS (up from earlier 1–5% estimates).
- "Good" = 3–5%; "Great" = 8–12%.
- AI-assisted products cluster at **15–20%** (higher perceived value).
- Analytics tooling often performs better with a **trial** than a perpetual free tier
  (configuration friction rewards structured onboarding).

## Reframing the strategic question

The earlier draft treated monetization as "how do we fund backfilling the catalog?" That
is the wrong question:

- The catalog is not the product. **Depth in chosen wedges is the product.**
- Ten wedge genres ≈ $1,500. One Pro subscriber ($15/mo) at 100 subscribers funds all
  ten genres plus the full year's refresh cadence.
- Inventing a one-off transactional funnel to fund analysis we don't actually need to
  run is engineering effort solving a non-problem.

The real question: **How do we price a free/paid split that (a) anchors credibly in
the indie-dev tools market, (b) separates casual users from paying users cleanly, and
(c) leaves room to grow into an agency/publisher tier when signal warrants?**

## Options considered

### Option A — Single paid tier (Free + Pro $15/mo)
- Free: structured data pages + featured reports + wedge insights pages.
- Pro $15/mo: all reports + all cross-genre synthesis + Pro sections + export + digests.
- *Pros:* Simplest possible launch. Matches GameDiscoverCo's proven anchor. One price point
  to explain. Fastest to ship (auth0 + Cleeng subscription only, no one-off purchase flow,
  no entitlement complexity beyond active/inactive; Cleeng absorbs tax, chargebacks, dunning).
- *Cons:* Leaves agency/publisher willingness-to-pay on the table. A researcher at a
  publisher wanting CSV exports + API access pays $15 just like a hobbyist.

### Option B — Three tiers (Free + Pro $15/mo + Pro+ $40–50/mo) *(RECOMMENDED, staged)*
- Free and Pro: as in Option A.
- Pro+ $40–50/mo: CSV/PDF export, API access, "request a genre" queue with priority,
  saved comparisons, email digests segmented per genre, multi-seat (up to 3 users).
- Positioned for **agencies, publishers, consultants, analysts** — users doing work
  WITH the data, not just consuming it.
- *Pros:* Captures the willingness-to-pay gap between $15 (indie solo) and $75 (Gamalytic
  Pro). Pro+ targets a different persona with different features, not "more of the same."
  Matches GameDiscoverCo's own $500/yr company tier shape.
- *Cons:* Speculative until we see Pro demand signals. Risk of building Pro+ features
  that nobody asks for.

### Option C — Hybrid subscription + $3 one-off unlock *(previous recommendation — rejected)*
- Pro $15 + per-game $3 unlock via hosted one-off checkout (Cleeng supports one-off
  purchases natively), report becomes permanently public.
- *Why rejected on review:*
  1. **Engineering cost-benefit is poor.** A second checkout flow, webhook-routed
     Step Function trigger, public-flip logic, entitlement records distinct from
     subscription state — real work for a stated success metric of "≥ 10 unlocks in
     month 1" = $30 revenue. Cleeng supporting one-off purchases natively lowers
     the cost, but doesn't make the revenue worth it.
  2. **Cannibalizes Pro.** "Why pay $15/mo if I can unlock the one game I care about for $3?"
     Subscription economics depend on recurring lock-in; $3 unlocks undercut that.
  3. **Zero exclusivity for the payer.** Report goes public immediately → the paying user
     gets nothing a non-paying user won't get 15 min later. Weak conversion psychology.
  4. **Solves the wrong problem.** Framed as funding catalog backfill; catalog backfill
     isn't the product (see reframe above). Pro MRR funds wedge expansion directly.
  5. **Not category-normal.** None of the verified competitors (Gamalytic, GameDiscoverCo,
     GG Insights, GameAnalytics, Sensor Tower) use per-item unlock as a primary motion.
     Indie-dev buyers expect subscription.
- Defer indefinitely. Revisit only if Pro conversion is healthy AND users organically
  ask for "analyze this specific game" — i.e. evidence-based, not speculative.

### Option D — Credit/usage-based (Perplexity-style)
- Pro $15/mo = N credits. Spend on reports, cross-genre compare, exports.
- *Pros:* Usage-aligned at scale.
- *Cons:* Over-complicated for launch. "What does a credit cost me?" FAQ burden. Meter
  + billing infra is real. Hold as an *evolution* path if usage complexity grows, not
  a launch model.

### Rejected outright
- **Community bounties** — requires a community we don't have.
- **Ad monetization** — gaming CPMs poor; conflicts with "intelligence platform" positioning.
- **Affiliate / Steam referral** — negligible revenue, distraction.
- **Lifetime deals** — GG Insights is using one; it's a signal they can't raise MRR. Don't follow.

## Recommendation: staged execution of Option B

Do not build Pro+ until Pro demand is proven. The launch sequence is:

### Stage 1 — Launch (Free + Pro $15/mo only)

**Free tier** (SEO moat + funnel top)
- Every per-game page renders structured data: Steam metadata, `positive_pct`,
  `review_count`, genre/tag affiliations, audience overlap, review velocity chart,
  playtime-sentiment chart, genre-relative ranking, price context, top 3 reviews,
  related games.
- Top-200 games have full AI reports visible at launch.
- `/genre/roguelike-deckbuilder/insights` — the full free wedge page.
- New wedge-genre insights pages added as Pro MRR funds them.

**Pro — $15/mo ($150/yr, ~17% saving)**
- All existing AI reports, no gating.
- All current + future cross-genre synthesis pages.
- Pro-only sections on game pages: `dev_priorities`, `churn_triggers`, `player_wishlist`
  (already gated in code via `validate-key`).
- Full audience overlap (50 games vs 5 on free).
- Pro lenses: Compare (4 games × 14 metrics), Builder (6 metrics), full Trends lens.
- Weekly genre-digest email (segmented by subscribed genres).

**Why this anchor works:**
- **$15 matches GameDiscoverCo exactly** — the category psychological floor.
- **Undercuts Gamalytic's $25 Starter** while offering a feature (cross-genre synthesis)
  Gamalytic doesn't have.
- **Clearly differentiates from GG Insights** — they sell raw data + chat; we sell
  synthesized narrative at genre depth.
- **Single Cleeng subscription flow** — minimum viable payment integration. Cleeng is free up to 10K subscribers, is the merchant of record (handles tax remittance across 13K+ jurisdictions, chargebacks, PCI, GDPR), and ships with native entitlement + coupon + churn analytics out of the box. See `cleeng-integration.md`.

### Stage 2 — Post-launch, gated on signal (add Pro+ $40–50/mo)

Only build Pro+ once Stage 1 shows:
- ≥ 30 active Pro subscribers (enough MRR to warrant more engineering),
- ≥ 3 inbound asks for export/API/agency features, OR
- churn analysis reveals "I'd pay more for X" in exit surveys.

**Pro+ — $40–50/mo (target $45)**
- CSV/PDF export of any report, genre page, or comparison.
- Read-only API access (rate-limited; analytics endpoints).
- "Request a genre" priority queue — subscriber picks a genre, we run the wedge analysis
  within 2 weeks.
- Saved comparisons + annotated collections (workspace primitive).
- Multi-seat (up to 3 users per subscription).
- Email digests segmented per-genre.

**Why $40–50, not $75:**
- $75 matches Gamalytic Pro and locks us into a feature-parity fight we don't want.
- $40–50 sits in the clear gap between GameDiscoverCo ($15 solo / $42 company-equiv)
  and Gamalytic ($75), which no one owns.
- Annual plan at $450/yr ($37.50/mo equiv) anchors cleanly near GameDiscoverCo's $500
  company plan — the same buyer persona.

**Why defer Pro+:**
- Speculative features are the #1 way to waste launch engineering effort.
- Every feature in Pro+ is individually easy to add *after* you have a user asking for it.
- Export + API + multi-seat each take ~2–3 days of focused work — not worth it pre-demand.

## Why not the other options

- **Option A (Free + Pro only forever):** Leaves high-willingness-to-pay segment unmonetized.
  Fine for Stage 1; not the endgame.
- **Option C (one-off $3 unlock):** See rejection analysis above. Engineering cost-to-value
  is poor; cannibalizes Pro; solves a non-problem.
- **Option D (credits):** Over-complication at launch. Re-consider only if "which reports
  has this user accessed" becomes a meaningful usage-based cost center later.

## Integration with the existing launch plan

This document **clarifies Phase D** of the Active Launch Plan in `steam-pulse.org` — it
names *what* the Pro features are and **stages Pro+ until signal warrants it**. It also
**enables pre-launch copy** on the landing page + `/pro` page so positioning can commit
*now* even though payment integration ships later.

### Prompts this strategy generates (to be written)

1. **`scripts/prompts/pricing-page.md`** *(to be written)* — `/pro` page content: $15/mo
   Pro tier only at launch. Copy hints at Pro+ as "coming soon for teams" without
   committing to date or price. Dev time only, no backend.
2. **`scripts/prompts/auth0-authentication.md`** — already in Backlog (High effort).
   Prerequisite for Pro. Bring forward to Stage 2 start.
3. **`scripts/prompts/cleeng-integration.md`** *(written)* — Cleeng (https://cleeng.com)
   as subscription platform + merchant of record. Covers: hosted checkout, webhook
   handler, local `entitlements` table synced from Cleeng webhooks, `is_pro(user_id)`
   via DB cache (no API call on hot path), waitlist-coupon wiring via Cleeng campaigns.
   Replaces Stripe-based integration. **Scope: Pro $15/mo subscription only. No one-off
   unlock, no per-item purchase, no token ledger.**
4. *(Stage 4, gated)* **`scripts/prompts/pro-plus-export.md`** — CSV/PDF export for
   reports + genre pages. Only write this prompt after Stage 4 trigger fires.
5. *(Stage 4, gated)* **`scripts/prompts/pro-plus-api.md`** — read-only analytics API.
   Rate-limited per subscription. Only after Stage 4 trigger.

### Files likely to touch (when the prompts above execute)

- `frontend/app/pro/page.tsx` — pricing page (exists as stub); subscribe CTA → `/api/subscribe` → Cleeng hosted checkout
- `frontend/app/layout.tsx` — Pro status in auth context; `usePro()` reads `/api/me/entitlement`
- `src/library-layer/library_layer/repositories/entitlement_repo.py` (new) — cached subscription state
- `src/library-layer/library_layer/services/cleeng_client.py` (new) — Cleeng REST API wrapper
- `src/library-layer/library_layer/services/entitlement_service.py` (new) — is_pro, webhook apply, checkout-url builder
- `src/lambda-functions/lambda_functions/api/handler.py` — `/api/subscribe`, `/api/me/entitlement`, `/api/subscription/cancel`; remove `/api/validate-key` stub
- `src/lambda-functions/lambda_functions/webhooks/cleeng_webhook.py` (new) — subscription lifecycle events from Cleeng
- `infra/stacks/compute_stack.py` — new Lambda for Cleeng webhook, Function URL
- Secrets Manager: `steampulse/{env}/cleeng-api-key`, `steampulse/{env}/cleeng-webhook-secret`
- Migration: `entitlements` table (per `cleeng-integration.md`)
- `scripts/prompts/landing-page-positioning.md` — already queued; "For Developers" CTA points at `/pro` with this packaging

### Execution order (slots into Active Launch Plan)

**Now, pre-launch (commit the direction; no payment code):**
- Landing page + `/pro` page copy written against Pro $15/mo.
- `steam-pulse.org` Monetisation Strategy section references this doc.
- Waitlist signup messaging: "Pro launches at $15/mo. Waitlist members get first 3 months
  free." — strong incentive for early signups.

**Stage 2 trigger (post-launch, if ≥ 50 signups — Pro ships):**
- Prompts 2 + 3 + 1 in parallel (~1 week dev; smaller scope because Cleeng absorbs tax, chargebacks, dunning, identity/entitlement lifecycle).
- Soft launch Pro to waitlist members first (3-month-free via Cleeng coupon `WAITLIST3M`).

**Stage 4 trigger (post-Pro, on signal — Pro+ evaluation):**
- ≥ 30 active Pro subs + ≥ 3 inbound asks → write prompts 4 + 5.
- Launch Pro+ to existing Pro users first via upgrade flow (add second Cleeng offer; update tier handling).

## Verification (how to tell if this is working)

**Stage 1 — within 4 weeks of Pro launching:**

1. **Free→Pro conversion** ≥ 2% of monthly uniques. Below 1% → pricing or packaging issue.
   Note: 2026 benchmark for AI-assisted tools is 15–20%; our initial aim is modest because
   of saturated category + limited brand.
2. **Pro cancellation rate** < 10%/month = healthy. Above → value gap in what Pro delivers.
3. **Waitlist → Pro conversion**: of waitlist members offered the 3-month-free coupon,
   ≥ 15% activate within 14 days.
4. **Cost coverage**: Pro MRR ≥ monthly LLM + infra burn within 60 days of launch.

**Stage 2 — decision gate to build Pro+:**

5. **Pro MRR ≥ $450/mo** (30 subs × $15). Below this, Pro+ engineering is premature.
6. **Inbound export/API asks ≥ 3** (email, Discord, exit surveys). Zero asks after 30 subs
   means agency segment isn't hearing about us yet — fix marketing before adding tier.
7. **Churn exit reason** — track "missing feature X" as a structured exit field.

**Stage 2 — within 4 weeks of Pro+ launching:**

8. **Pro → Pro+ upgrade rate** ≥ 5% of active Pro. Below → tier differentiation too weak.
9. **Pro+ cancellation** < 8%/month (sticky segment, should churn lower than Pro).

## Out of scope

- **Ad monetisation** — gaming CPMs poor; conflicts with positioning.
- **Affiliate / Steam referral links** — negligible revenue.
- **Enterprise tier** — wait for inbound demand ≥ $500/mo ask; don't build proactively.
- **One-off per-game unlock (prior Option C)** — defer indefinitely; revisit only on
  evidence of organic demand AND Pro conversion healthy.
- **Credit system (prior Option D)** — defer as evolution path if usage complexity grows.
- **Community bounties** — requires pre-existing community.
- **Lifetime subscription / founder deals** — no early-bird gimmicks; keep pricing honest
  and predictable. (GG Insights is doing this — it signals they can't sustain MRR. Don't follow.)

## Sources

- [Gamalytic Pricing](https://gamalytic.com/pricing) — Starter $25/mo, Professional $75/mo (verified via search 2026-04-16)
- [GameDiscoverCo Plus subscribe page](https://newsletter.gamediscover.co/p/gamediscoverco-plus-subscribe-today) — $15/mo, $150/yr individual; $500/yr company (20+ employees) *(new tier data)*
- [GG Insights Pricing](https://www.gginsights.io/pricing) — Free + $64.35 early-bird lifetime (regular $99) *(new competitor not in prior draft)*
- [GameAnalytics Indie Program](https://www.gameanalytics.com/pricing/indie) — $99/mo
- [VGInsights → Sensor Tower](https://app.sensortower.com/vgi/pricing/) — enterprise-only now
- [Steam Sentimeter](https://steamsentimeter.com/) — currently free
- [HowlRound](https://www.howlround.dev/) — pricing not public
- [Perplexity Pricing](https://www.finout.io/blog/perplexity-pricing-in-2026) — $20 Pro + $200 Max
- [First Page Sage — SaaS Freemium Conversion Rates 2026](https://firstpagesage.com/seo-blog/saas-freemium-conversion-rates/) — median 8%, AI 15–20%
- [Artisan Strategies — 2026 SaaS Conversion Benchmarks](https://www.artisangrowthstrategies.com/blog/saas-conversion-rate-benchmarks-2026-data-1200-companies)
- [HubSpot — Freemium Model](https://blog.hubspot.com/service/freemium)
- [Cleeng Pricing](https://cleeng.com/pricing) — free platform to 10K subs; MoR promo $0.35 + 3.5%, regular $0.39 + 3.9%
- [Cleeng Merchant of Record](https://cleeng.com/merchant-of-record) — 200+ payment methods, 13K+ tax jurisdictions, GDPR/PSD2
- [Cleeng Free Plan](https://blog.cleeng.com/free-cleeng-plan) — what's in the free tier + BYO gateway option
