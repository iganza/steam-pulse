# Monetization strategy — two-tier catalog model

## Context

SteamPulse sells a self-serve catalog of LLM-synthesised Steam genre
research reports. This document is the canonical strategic reference
for pricing, product boundaries, and which add-ons are in/out. It
stays consistent with `steam-pulse.org` (Active Launch Plan) and the
`project_business_model_2026.md` memory. When any of these three
disagree, `steam-pulse.org` is the source of truth and the others are
updated to match.

## Operating principle

*"If work can't be built once and sold 1,000 times without my
involvement, it doesn't belong in this business."*

Every future feature, tier, or surface passes the sleep test or is
killed/gated. This governs every decision in this document.

## Tier 1 — Launch & Run

The entire business for the first 12+ months.

### Launch sequence

Reports launch in three phases. Each phase gates the next.

| Phase | Window   | Ships                                                    | Revenue signal           |
|-------|----------|----------------------------------------------------------|--------------------------|
| **A** | Week 1   | Free `/genre/[slug]/` cross-genre synthesis page         | None (traffic only)      |
| **B** | Week 2–4 | Pre-order block on the synthesis page; Stripe Checkout   | Pre-orders               |
| **C** | Week 4–8 | Polished PDF; delivered to pre-order buyers + self-serve | First PDF revenue lands  |

**Phase A** ships the Phase-4 synthesiser output as a free,
SEO-indexed web page — the proof artifact. No payment. No email
capture. Just the page.

**Phase B** adds a pre-order block on that same page: *"Get the full
PDF — $49. Ships [date]."* Stripe Checkout captures payment
immediately; the Stripe webhook writes a `report_purchases` row; the
delivery worker sees `reports.published_at > now()` and holds the
S3-URL email until ship date. Pre-orders are the **real revenue
signal** — a deposit-based commitment, not a free waitlist. If
pre-orders are zero after two weeks of traffic, the positioning or
the product-shape is wrong; do not commit 60 hours of editorial to
the PDF.

**Phase C** is the 60 hours of human editorial work. When the PDF
assets land in S3, flip `reports.published_at` to `now()`; the
delivery worker sweeps the queue and emails every pre-order buyer
their signed URL. From that moment onward, self-serve checkout
delivers inline.

**Do not reverse the sequence.** Building the PDF first means
committing 60 hours to a product whose demand isn't proven. The
phased launch costs one extra email to each buyer (the shipping
notification); it buys you validated demand before the editorial
investment.

### The product

Self-serve catalog of flagship PDF genre reports. One new report per
quarter. Each report is the whole-niche cross-cutting synthesis of a
single Steam genre: friction points, wishlist items, benchmark games,
churn timing, ranked dev priorities — all quote-backed.

### Free vs paid — what differentiates the tiers

The free `/genre/[slug]/` page and the paid PDF report are built from
the same Phase-4 synthesiser output. They are **different artifacts**,
not different access levels to the same content.

| Artifact                     | What it is                                                  | Price  |
|------------------------------|-------------------------------------------------------------|--------|
| Free `/genre/[slug]/` page   | Phase-4 synthesis rendered in HTML: narrative summary, top-10 friction clusters with quotes + mention counts, top-10 wishlist, benchmark game list, churn insight, dev priorities table, methodology footer | $0 |
| Indie PDF                    | Above, plus editorial sequencing, 3-page executive summary, strategic recommendations chapter, methodology expanded, print-ready design, cover page                                  | $49    |
| Studio PDF + CSV             | Indie + CSV dataset of every friction / wishlist / benchmark with source_appid columns for independent analysis + 1-year update access                                                | $149   |
| Publisher PDF + CSV + JSON   | Studio + raw JSON payload of the synthesis + team license (up to 10 seats)                                                                                                            | $499   |

The critical piece missing from the free page that lives only in the
PDF: the **benchmark game deep-dives** (15–20 pages of 3–4 pages each
on Slay the Spire / Balatro / Inscryption / Monster Train / Dicey
Dungeons). These are not in the Phase-4 output — they are hand-written
editorial content. That's the real price justification.

### Pricing

| Product                       | Price  | Who it's for                                | Deliverable                                      |
|-------------------------------|--------|----------------------------------------------|---------------------------------------------------|
| Genre Report — Indie tier     | $49    | Solo devs, hobbyists, curious individuals    | 35-45 page PDF                                    |
| Genre Report — Studio tier    | $149   | Small teams (≤ 10 people)                    | PDF + CSV dataset + 1-year update access          |
| Genre Report — Publisher tier | $499   | Studios, publishers, fund managers, analysts | PDF + CSV + raw JSON + team license               |
| Per-game pages                | $0     | Everyone, indexed for SEO                    | Free forever                                      |
| Genre summary pages           | $0     | Everyone, indexed for SEO                    | Free forever                                      |

**All three paid tiers are fully self-serve Stripe buttons.** No
contact form, no manual invoicing, no email scoping. Even the $499
publisher tier is a self-checkout. The operating principle is
load-bearing here — if a publisher needs more than what's in the tier,
they can buy the tier and email; that's a bonus, not a prerequisite.

### Why this pricing

- **$49** is the psychological floor for a 35-45 page research PDF.
  Below that it reads as "low effort"; above it needs a quality
  justification for solo devs.
- **$149** is 3× indie — the standard "I'm buying this with company
  money" anchor across adjacent infoproduct markets.
- **$499** captures the studio/publisher buyer willingness-to-pay
  without needing a sales motion. Published comparables:
  GameDiscoverCo Company plan $500/yr, IndieWorldOrder-style reports
  $299-$999 per cut.
- **Free on-site content** is the SEO engine. Every per-game page is
  a long-tail landing page. Every genre summary page ranks for
  mid-tail queries ("best roguelike deckbuilder," "indie survival
  crafting trends"). Reports are the conversion target at the bottom
  of that funnel.

### Architecture

- **Payment:** Stripe Checkout (one-off purchase session, not
  subscription). See `stripe-checkout-report-delivery.md`.
- **Delivery:** S3 signed URL emailed on successful webhook. Buyer
  clicks link, gets PDF/CSV/JSON. No account, no login, no portal.
- **Content engine:** cross-genre synthesiser matview
  (`cross-genre-synthesizer-matview.md`) — Phase-4 LLM produces
  structured first draft; human curates to final report.
- **No auth stack.** No `usePro()`, no `/api/validate-key`, no magic
  links, no entitlements table. Delivery is per-sale.

### Operator load

- ~60 hours editorial for Report #1; ≤ 40 hours for Reports #2+.
- ~$200 LLM cost per report (analysis + synthesis + prompt iteration).
- ~2 hours one-time amplification per report (one Reddit, one
  Bluesky, one community share).
- Ongoing: nil. No weekly cadence, no per-sale labour, no support
  rotation. Stripe + S3 deliver while the operator sleeps.

## Tier 2 — Gated (do NOT build until the gate fires)

Every add-on has a specific numerical gate. Gates are evaluated
quarterly, honestly. The gates exist to protect the operator from
speculative complexity. Writing them here so future-me can't
rationalise around them.

| Add-on                                         | Gate (must fire first)                                                     | Labour once built           |
|------------------------------------------------|----------------------------------------------------------------------------|-----------------------------|
| Dataset add-on ($99 CSV+JSON per report)       | 3+ buyer emails asking for raw data                                        | 1 week, then passive        |
| "Alert me when a new report drops" email list  | Monthly uniques > 3k                                                       | 2 days, then passive        |
| $49/yr All-Access Pass (catalog-wide)          | 5+ reports shipped AND 100+ unique buyers                                  | 1-2 weeks                   |
| "Genre Audit" self-serve SKU ($79)             | Catalog MRR > $3k/mo for 3 consecutive months                              | 1-2 weeks, then passive     |
| Weekly newsletter                              | Catalog MRR > $10k/mo for 3 consecutive months AND operator wants to write | 6-10 hr/week ongoing        |
| Course ($249 one-off)                          | Newsletter at 1k engaged subs AND ≥ 3 buyers explicitly asking             | 200+ hr upfront, then light |
| NL chat / SaaS Pro ($25/mo)                    | ≥ 5 paying buyers explicitly asking "can I pay for ongoing access?"        | Heavy eng + 24/7 support    |

## Killed forever (not deferred — structurally incompatible)

These items cannot be "added later" because they fail the sleep test
at any scale, not just today:

- **1:1 consulting / custom gut-checks** — can't scale without
  operator time.
- **Publisher manual-invoice custom briefs** — the self-serve $499
  tier captures the value without the email dance.
- **Discord community management** — permanent 24/7 obligation.
- **Sponsorship / ad sales BD** — ongoing BD labour that never stops.
- **Product Hunt pre-launch theatre** — wrong audience, zero
  sleep-value.
- **Paid ads before measurable free→paid conversion data exists.**
- **Per-game Pro gating** of `dev_priorities` / `churn_triggers` /
  `player_wishlist` / audience overlap / any on-site content — 100%
  of on-site content is free forever.
- **Pro+ agency tier** as a separate product — folds into Studio/
  Publisher tiers.
- **One-off $3 per-game unlock** — cannibalises reports, zero
  exclusivity for the payer, solves a problem that doesn't exist.
- **Credit/token ledgers** — metering + billing infra + FAQ burden
  for no structural benefit.
- **Lifetime deals** — signals inability to sustain MRR; don't
  follow.

## Prompts this strategy keeps / drops

### Keep (active or pending)

- `scripts/prompts/stripe-checkout-report-delivery.md` — Tier 1
  payment engine.
- `scripts/prompts/cross-genre-synthesizer-matview.md` — Tier 1
  content engine.
- `scripts/prompts/genre-insights-page.md` — reframed from
  "Pro-gated preview" to "free SEO surface." All sections free, no
  blur, no CTA overlay.
- `scripts/prompts/soft-launch-seo-discipline.md` — Tier 1 SEO
  baseline.

### Dropped (do not build; prompt files deleted)

- `cleeng-integration.md` — subscription platform no longer used.
- `auth0-authentication.md` — no auth stack in Tier 1.
- `pricing-page.md` — `/pro` page no longer exists; replaced by
  `/reports` catalog.
- `pro-plus-export.md` / `pro-plus-api.md` / `report-export-premium.md`
  — Pro+ tier retired.

### Deferred behind Tier 2 gates (do not write the prompt until gate fires)

- NL chat + text-to-SQL prompt.
- `pro-subscription-tier.md`.
- Newsletter / course / audit SKU prompts — all speculative until the
  relevant gate fires.

## Files likely to touch (when Tier 1 prompts execute)

- `frontend/app/reports/page.tsx` (new) — catalog landing page
- `frontend/app/reports/[slug]/page.tsx` (new) — per-report landing
  page with three-tier Stripe buttons
- `src/lambda-functions/lambda_functions/api/handler.py` — new
  `/api/stripe/webhook` endpoint; remove `/api/validate-key` stub
- `src/library-layer/library_layer/services/stripe_client.py` (new)
- `src/library-layer/library_layer/services/report_delivery.py` (new)
  — signs S3 URL and triggers Resend email
- `infra/stacks/compute_stack.py` — S3 bucket for reports, Stripe
  webhook Lambda + Function URL
- Secrets Manager: `steampulse/{env}/stripe-api-key`,
  `steampulse/{env}/stripe-webhook-secret`

### Files to remove (separate implementation task)

- `frontend/lib/pro.tsx` / `usePro()` hook
- `frontend/components/toolkit/ProLockOverlay.tsx`
- Per-game blur + overlay CSS patterns
- `/api/validate-key` stub
- `NEXT_PUBLIC_PRO_ENABLED` flag references

## Verification — what "working" looks like

### Tier 1 launch signals (first 30 days after Report #1 ships)

- **First paid sale** lands on any tier — existence proof for the
  catalog model.
- **Stripe checkout conversion** from `/reports/[slug]` > 0.5%
  (realistic for cold traffic, no brand yet).
- **S3 signed-URL delivery** fires correctly on 100% of paid sales
  (webhook retry handled).
- **Plausible** shows ≥ 20 sessions/day by week 2 from SEO + one
  amplification event.
- **Lighthouse SEO** ≥ 90 on a random sample of per-game pages.

### Tier 2 gate triggers (revisit quarterly)

Each Tier 2 gate is a numerical trigger. Do not start Tier 2 prompt
work unless the corresponding gate has fired for the required window.
"Close enough" does not count.

## Out of scope (permanently or until gate)

See "Killed forever" above and the Tier 2 table. No item not
explicitly listed in Tier 1 above is part of the launch product.

## Market anchors (verified 2026-04-16 / 2026-04-19)

Reference only — do not infer that SteamPulse competes directly.
SteamPulse is a one-off catalog; competitors below are subscription or
breadth platforms.

- [GameDiscoverCo Plus](https://plus.gamediscover.co/) — $15/mo
  individual, $500/yr company. Weekly newsletter + data suite.
  SteamPulse does not compete on newsletter cadence; it competes on
  per-niche depth.
- [Gamalytic](https://gamalytic.com/pricing) — Starter $25/mo,
  Professional $75/mo. Breadth platform.
- [VGInsights](https://vginsights.com/) — indie plan ~$20/mo.
- [GG Insights](https://www.gginsights.io/) — freemium +
  lifetime-deal anchor.
- [Chris Zukowski, Wishlist & Visibility Masterclass](https://www.progamemarketing.com/p/visibility-and-wishlist-masterclass)
  — $400 course; reference for indie-dev willingness-to-pay on
  one-off infoproducts.
