# Monetization strategy — committed direction for launch

## Context

SteamPulse is about to launch and needs a committed monetization strategy. Two hard constraints shape every option:

1. **Catalog-wide backfill is economically impossible.** At ~$1/report (Bedrock Sonnet via the three-phase analyzer) × ~20,000 eligible games on Steam = ~$20,000 up-front. Current LLM budget for the wedge launch is $500 total. The strategy must never assume "all games have reports."
2. **The per-game AI-review-analysis category is saturated as of 2026-04** (Datahumble, Steam Sentimeter, HowlRound, SteamReview AI — see `memory/project_market_saturation_2026.md`). Direct head-to-head on "we synthesise a single game's reviews" is a losing commodity fight. The wedge differentiator is **cross-genre synthesis at depth** (currently roguelike-deckbuilder; expansion path defined in `steam-pulse.org` → Wedge Strategy).

The existing launch plan already has Pro gating plumbing (`NEXT_PUBLIC_PRO_ENABLED`, `usePro()` hook, `/api/validate-key` stub, blur + overlay CTA patterns) and a packaging principle (`memory/feedback_packaging_principle.md` — free = publishable insight, Pro = toolkit to ask your own questions). Payment integration is deferred; `auth0-authentication.md` sits in the Backlog. This document is the **committable direction** so landing-page copy, the `/pro` page, and waitlist messaging can all be written *now* against a real target, not a placeholder.

Research performed 2026-04-16; re-verify pricing claims before committing publicly.

## Market reconnaissance (verified 2026-04-16)

| Competitor | Model | Free tier | Paid tier(s) |
|---|---|---|---|
| **Gamalytic** | Subscription | Game list, basic stats | **Starter $25/mo**, Pro $75/mo |
| **GameDiscoverCo Plus** | Substack newsletter + data | Free weekly newsletter | **$15/mo ($150/yr)** — Friday edition, Hype chart, data suite, Discord |
| **VGInsights** (Sensor Tower) | Tiered / enterprise | Limited public | Historical Patreon ~$14.50/mo; now enterprise-priced |
| **Steam Sentimeter** | Free (research / portfolio) | Full | — |
| **HowlRound, SteamReview AI** | Subscription (indie-dev) | Limited trials | Not publicly priced |
| **Perplexity** (reference SaaS) | Freemium + credits | 5 Pro queries/day | Pro $20/mo, Max $200/mo (10k credits) |

**Key anchors:**
- Indie-dev willingness-to-pay clusters at **$15–$25/mo** for solo/hobbyist, **$75/mo** for pros.
- **$15 (GameDiscoverCo Plus) is the psychological bottom** for paid indie-dev tools in this space.
- Freemium conversion averages 1–10%; opt-in trial (no card) ~15–20%.

## Five options considered

### Option 1 — Classic tiered subscription (Gamalytic-style)
- Free: browsing + structured-data game pages + wedge genre insights page.
- Pro $15–25/mo: unlimited access to generated reports, cross-genre synthesis, filters/drill-down/export, API.
- Generation funding: whatever MRR supports.
- *Pros:* Simplest; proven in-category; predictable MRR.
- *Cons:* Doesn't solve the backfill problem — most games never get reports. Free users see empty "no report yet" states. Pro value thin until cross-genre breadth exists.

### Option 2 — Pay-per-report only (on-demand, user-funded generation)
- Free: all per-game pages + featured reports only.
- $2–5 one-time to trigger report generation for any un-analysed game. Report becomes permanently public (SEO benefit).
- No subscription.
- *Pros:* Aligns cost to revenue perfectly — never generate a report we can't pay for. Users fund the catalog. SEO compounds.
- *Cons:* No recurring revenue. Friction for casual visitors. Hard to forecast.

### Option 3 — Credit system (Perplexity-style)
- Free: structured-data pages + limited reports.
- Pro $15/mo = N credits (e.g. 25). Spend on: unlock Pro sections, analyse a game, run cross-genre comparison, export CSV.
- Optional credit top-up packs.
- *Pros:* Usage-aligned; flexible; meters expensive operations.
- *Cons:* Most complex to explain; meter + billing infra; "what does a credit cost?" FAQ burden.

### Option 4 — Hybrid: tiered subscription + on-demand unlock *(RECOMMENDED)*
- Free: all structured-data pages + top-200 featured reports + wedge genre insights.
- Pro $15/mo: unlimited reports + cross-genre synthesis + Pro sections + 5 "analyse a game" tokens/month + exports.
- One-off $3 unlock: any visitor can pay $3 to generate a specific game's report. Report becomes permanently public.
- *Pros:* Three revenue streams (recurring + transactional + cost-aligned generation). Solves backfill without upfront capital. Anchors at $15 (GameDiscoverCo), undercuts Gamalytic's $25. Captures casual $3 users the subscription funnel would lose.
- *Cons:* Two price points to communicate. Requires recurring + one-off payment integration. Slightly more onboarding copy.

### Option 5 — Community-funded marketplace
- Free: all browsing.
- Bounties: users vote or pool funds to analyse a specific genre/game.
- Optional Pro subscription bolt-on.
- *Pros:* Community ownership; clear demand signal; costs only when demand exists.
- *Cons:* Requires critical-mass community *before* revenue; payment + bounty tracking is real engineering; slow ramp.

## Recommendation: Option 4 — Hybrid tiered subscription + on-demand unlock

### Why this wins

1. **Directly solves the $20K backfill problem.** We never generate reports we haven't been paid for. Upfront spend is the $341 wedge + top-200 already in the launch plan. Beyond that, catalog expansion is funded by users: subscribers consuming monthly tokens, or one-off unlock purchases.
2. **Two conversion funnels on the same traffic.** A casual visitor who wouldn't subscribe still converts at $3. An indie dev doing competitor research converts at $15/mo. Subscription-only sites leave the $3 user on the table.
3. **Survivable pricing floor.** $15/mo matches GameDiscoverCo Plus exactly — the psychological anchor for indie-dev paid tools — and undercuts Gamalytic's $25 Starter. Our wedge (cross-genre synthesis) is a feature neither has; $15 reads as "worth it."
4. **Aligns to the wedge strategy.** Cross-genre synthesis pages (core differentiator, already shipping) become the Pro-tier hook. The rest of Pro (filters/drill-down/export/API) is icing. Free users get everything Gamalytic's free tier has, plus our wedge pages.
5. **SEO-compatible.** Paid unlocks become permanently public (indexable). Every unlock grows the searchable catalog. Over time the catalog expands organically at no cost to us.

### Concrete design

**Free tier** (SEO moat + funnel top)
- Every per-game page renders structured data: Steam metadata, `positive_pct`, `review_count`, genre/tag affiliations, audience overlap, review velocity chart, playtime-sentiment chart, genre-relative ranking, price context, top 3 reviews, related games. (What `audit-game-page-no-report-state.md` delivers.)
- Top-200 games have full AI reports visible at launch.
- `/genre/roguelike-deckbuilder/insights` — the full free wedge page.
- New genre insights pages (Survival, Horror, etc.) added as Pro MRR funds additional batch runs.

**Pro tier — $15/mo ($150/yr, ~17% saving)**
- All existing AI reports, no gating.
- All current + future cross-genre synthesis pages.
- Pro-only sections on game pages: `dev_priorities`, `churn_triggers`, `player_wishlist` (already gated in code via `validate-key`).
- Full audience overlap (50 games vs 5 on free).
- Pro lenses: Compare (4 games × 14 metrics), Builder (6 metrics), full Trends lens.
- CSV / PDF export of any report or genre page.
- **5 "analyse this game" tokens per month** — user requests a specific un-analysed appid; report runs via the existing batch Step Functions and becomes public.
- Weekly genre-digest email (segmented by subscribed genres).

**One-off unlock — $3 per game**
- Public visitor hits a game with no report → sees structured data + banner: "Unlock this game's full AI analysis — $3. Becomes public forever."
- Stripe Checkout, no account required.
- Report runs within ~15 min (existing pipeline).
- Unlocked report is identical to Pro-tier reports and publicly readable.
- Margin: $3 unlock − ~$1 LLM cost ≈ $2 gross covers payment fees + Lambda + attribution.

### Why not the other four
- **Option 1**: doesn't address backfill; Pro value thin until cross-genre synthesis has breadth.
- **Option 2**: leaves recurring MRR on the table; forecasting harder.
- **Option 3**: right at scale but over-complicates launch. Hold as evolution target if credit complexity becomes natural fit.
- **Option 5**: community-first but needs community first, which we don't have yet. Revisit if waitlist/Discord ≥ 500.

## Integration with the existing launch plan

This document **clarifies Phase D** ("50+ signups → start building Pro features") of the Active Launch Plan in `steam-pulse.org` — it names *what* those Pro features are. It also **enables pre-launch copy** on the landing page + `/pro` page so positioning can be committed *now* even though payment integration ships later.

### Prompts this strategy generates (to be written)

1. **`scripts/prompts/pricing-page.md`** — `/pro` page content: $15/mo tier, $3 unlock, what's included, what's not, annual discount. Dev time only, no backend.
2. **`scripts/prompts/auth0-authentication.md`** — already in Backlog (High effort). Prerequisite for Pro. Bring forward to Phase D start.
3. **`scripts/prompts/stripe-payment-integration.md`** — subscribe + one-off checkout flows, webhook handling, entitlement DB. Prerequisite for Pro. Pair with auth0.
4. **`scripts/prompts/unlock-report-flow.md`** — `/games/[appid]/[slug]` banner for un-analysed games → Stripe Checkout → report generation via existing batch Step Functions → public visibility after generation. Depends on payment prompt.
5. **`scripts/prompts/pro-token-ledger.md`** — track 5 monthly tokens per Pro subscriber, atomic decrement on `/analyze-this-game` request, reset on billing-cycle boundary. Small repo + service.

### Files likely to touch (when the prompts above execute)

- `frontend/app/pro/page.tsx` — pricing page (exists as stub per Deferred list in steam-pulse.org)
- `frontend/app/games/[appid]/[slug]/page.tsx` — unlock banner when `report === null`
- `frontend/app/layout.tsx` — Pro status in auth context
- `src/library-layer/library_layer/repositories/entitlement_repo.py` (new) — subscription + unlock records
- `src/library-layer/library_layer/repositories/report_token_repo.py` (new) — monthly token ledger
- `src/lambda-functions/lambda_functions/api/handler.py` — `/api/subscribe`, `/api/unlock-report`, `/api/validate-key` (remove stub), `/api/analyze-this-game`
- `src/lambda-functions/lambda_functions/webhooks/stripe_webhook.py` (new)
- `infra/stacks/compute_stack.py` — new Lambda for Stripe webhooks
- `infra/stacks/data_stack.py` — `entitlements` + `report_tokens` tables (migrations)
- `scripts/prompts/landing-page-positioning.md` — already queued; "For Developers" CTA points at `/pro` with this packaging

### Execution order (slots into Active Launch Plan)

**Now, pre-launch (commit the direction; no payment code):**
- Landing page + `/pro` page copy written against the $15 / $3 model.
- `steam-pulse.org` Monetisation Strategy section references this doc as the committed direction.
- Waitlist signup messaging: "Pro launches at $15/mo. Waitlist members get first 3 months free." — strong incentive for early signups.

**Phase D trigger (post-launch, if ≥ 50 signups):**
- Prompts 2 + 3 + 1 in parallel (~1–2 weeks dev).
- Then prompts 4 + 5.
- Soft launch Pro to waitlist members first (3-month-free coupon).

## Verification (how to tell if this is working)

Within 4 weeks of Pro launching:

1. **Free-to-paid conversion** ≥ 2% of monthly uniques (industry minimum for freemium). Below 1% → pricing or packaging issue.
2. **Unlock revenue** ≥ 10 paid unlocks in first month = strong signal the on-demand funnel works. < 5 → friction too high or banner copy weak.
3. **Pro cancellation rate** < 10%/month = healthy. Above → value gap in what Pro delivers.
4. **Cost coverage**: paid unlocks cover their own LLM cost within the same week. Alert if unlock-to-cost ratio drops below 2×.
5. **Catalog growth from unlocks**: track appids that transition `report = null → report generated` via unlock. Each is a permanent SEO asset.
6. **Waitlist → Pro conversion**: of waitlist members offered the 3-month-free coupon, ≥ 15% activate within 14 days.

## Out of scope

- **Ad monetisation** — gaming CPMs poor for early traffic; conflicts with "intelligence platform" positioning.
- **Affiliate / Steam referral links** — negligible revenue, distraction from core.
- **Enterprise tier** — wait for inbound demand; don't build proactively.
- **Credit system (Option 3)** — defer as evolution path if "analyse this game" usage complexity grows.
- **Community bounties (Option 5)** — revisit post-launch if Discord / waitlist ≥ 500.
- **Lifetime subscription / founder deals** — no early-bird pricing gimmicks; keep pricing honest and predictable.

## Sources

- [Gamalytic Pricing](https://gamalytic.com/pricing) — Starter $25/mo, Professional $75/mo (verified 2026-04-16)
- [GameDiscoverCo Plus subscribe page](https://newsletter.gamediscover.co/p/gamediscoverco-plus-subscribe-today) — $15/mo or $150/yr
- [VGInsights Pricing](https://vginsights.com/pricing/) — tiered / enterprise
- [Steam Sentimeter](https://steamsentimeter.com/) — currently free
- [Perplexity Pricing 2026 (Finout)](https://www.finout.io/blog/perplexity-pricing-in-2026) — freemium + $20 Pro + $200 Max with credits
- [SaaS Pricing Models 2026 (Revenera)](https://www.revenera.com/blog/software-monetization/saas-pricing-models-guide/)
- [9 Software Monetization Models for SaaS and AI Products 2026 (Schematic)](https://schematichq.com/blog/software-monetization-models)
- [Usage-Based Billing Explained 2026 (Schematic)](https://schematichq.com/blog/why-usage-based-billing-is-taking-over-saas) — usage-based growing 38% faster than flat subs
- [Monetizing in the AI Era (Userpilot)](https://userpilot.com/blog/ai-saas-monetization/)
- [AI Pricing in Practice 2025 (Metronome)](https://metronome.com/blog/ai-pricing-in-practice-2025-field-report-from-leading-saas-teams)
- [Freemium Model (HubSpot)](https://blog.hubspot.com/service/freemium) — conversion rates 1–10%
