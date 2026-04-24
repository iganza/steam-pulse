# Monetization strategy — single-SKU catalog model

## Operating criterion — asynchronous transactions

Every surface, tier, or feature must support the full transaction
flow asynchronously: a buyer can discover, sign up, pay, and receive
value without operator real-time involvement. Stripe Checkout, S3
signed-URL delivery, recurring subscriptions, and scheduled email
all qualify. Live sales calls, custom-quoted proposals, and any
"hop on a call before you can buy" flow do not.

This document is the canonical strategic reference for pricing,
product boundaries, and which add-ons are in/out. Keep consistent
with `steam-pulse.org` (Active Launch Plan) and the
`project_business_model_2026.md` memory. When any of these three
disagree, `steam-pulse.org` is the source of truth.

## Tier 1 — Launch & Run

The entire business for the first 12+ months is **one SKU**: a $49
Genre Report (PDF + CSV bundled), one Stripe Checkout button, one
price, no tier selector, no persona naming.

### Why single-SKU

The previous model (Indie $49 / Studio $149 / Publisher $499) was a
SaaS convention grafted onto a one-off PDF. Pre-inventing $149 and
$499 tiers adds 3× the implementation surface (Stripe products, DB
CHECK constraints, license terms, per-tier email branching) before a
single $49 sale has validated the core price. Every relevant
comparable uses one price:

- GameDiscoverCo Plus: one individual sub + one company sub.
- Lenny's Newsletter: one $200/yr tier, 4–5% paid conversion.
- Stratechery: one $120/yr tier, 26k paid.
- Chris Zukowski: separate SKUs per product (courses at $49, $400), not tiers of the same product.
- Indie Hackers consensus: for infoproducts, one-off > subscription, and tier segmentation only works when feature differentiation is real (seats, API limits) — not fabricated.

Higher-priced SKUs remain on the roadmap but as Tier-2 gated
add-ons, only built once the numerical demand trigger fires.

### Launch sequence

Reports launch in three phases. Each phase gates the next.

| Phase | Window   | Ships                                                    | Revenue signal           |
|-------|----------|----------------------------------------------------------|--------------------------|
| **A** | Week 1   | Free `/genre/[slug]/` cross-genre synthesis page         | None (traffic only)      |
| **B** | Week 2–4 | Pre-order block on the synthesis page; Stripe Checkout   | Pre-orders               |
| **C** | Week 4–8 | Polished PDF; delivered to pre-order buyers + self-serve | First PDF revenue lands  |

**Phase A** ships the Phase-4 synthesiser output as a free,
SEO-indexed web page — the proof artifact. No payment, no email
capture.

**Phase B** adds a pre-order block on that same page: *"Get the full
PDF + dataset — $49. Ships [date]."* Stripe Checkout captures
payment immediately; the Stripe webhook writes a `report_purchases`
row; the delivery worker sees `reports.published_at > now()` and
holds the S3-URL email until ship date. Pre-orders are a
deposit-based commitment, not a free waitlist. If pre-orders are
zero after two weeks of traffic, the positioning or the
product-shape is wrong; do not commit 60 hours of editorial.

**Phase C** is the 60 hours of human editorial work. It fires only
if the Phase B → C demand gate fires — evaluated 2 weeks after the
pre-order block goes live:

- **≥ 3 pre-orders at $49** → commit the 60 hours. Write the exec summary + benchmark deep-dives + strategic recs. Upload PDF + CSV assets. Flip `reports.published_at` to `now()`; the delivery worker sweeps the queue and emails every pre-order buyer their signed URL. Self-serve checkout delivers inline from that point onward.
- **1–2 pre-orders** → marginal but real. Ship Phase C with a tighter scope.
- **0 pre-orders** → do NOT write the PDF. Remove the `reports` row or extend `published_at` indefinitely. The free curated-preview page stays live as SEO. Talk to anyone who reached the page but didn't convert before iterating positioning.

### The product

Self-serve catalog of flagship PDF genre reports. One new report per
quarter. Each report is the whole-niche cross-cutting synthesis of a
single Steam genre: friction points, wishlist items, benchmark games,
churn timing, ranked dev priorities — all quote-backed.

### Free vs paid — landscape vs plan

The free `/genre/[slug]/` page and the paid PDF answer **different
questions**, not the same question with more items behind a paywall.
The structural difference is what justifies $49 — not the count of
items 6-10.

- Free page = **landscape**. *"What does the data show?"* Top-N
  headlines, representative quotes, methodology, named author
  byline. Aggregated, factual, shareable.
- Paid PDF = **plan**. *"What should I do?"* Hand-written editorial
  on named competitor games. Ranked design moves with data
  citations. Dev priorities as a prioritised action sequence.
  Opinionated analyst output.

Curation on the free page is load-bearing for two reasons: Google's
March 2026 core update demotes mass-produced AI content without
human editing or named-expert attribution, and the
anti-cannibalisation rule is that AI assistants should be able to
*cite* but not *finish* the buyer's question from what's public.

| Artifact                     | What it is                                                                                                                                                                                                    | Price  |
|------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------|
| Free `/genre/[slug]/` page   | Landscape: named-author byline, ~200-word editorial intro, top-5 friction clusters with quotes + mention counts, top-3 wishlist items, 3 benchmark game cards with pull-quotes, methodology footer            | $0     |
| Genre Report PDF + CSV       | Plan: 15–20 pages of hand-written benchmark deep-dives on the 5 named competitors, strategic recommendations chapter (ranked design moves with citations), dev priorities as a prioritised plan, 3-page executive summary, full friction (6–10) and wishlist (4–10) lists, expanded methodology, print-ready design, cover page, CSV dataset with source_appid columns | $49    |

Notably **absent from the free page**: the churn interpretation and
the 2-row dev-priorities teaser. Both are the author's *opinion*,
which is the kind of value a buyer pays for. The free page is
data-and-quotes + a named voice; the PDF is the voice applied.

### What justifies the $49

The defensible sentence: *"The free page shows the landscape; the
PDF shows your next 8 design moves, with the data behind each."*

Concretely:

1. **Hand-written benchmark deep-dives** on Slay the Spire, Balatro, Inscryption, Monster Train, Dicey Dungeons — 15–20 pages of original editorial. Cannot be synthesized. Google rewards named-expert content.
2. **Strategic recommendations chapter** — ranked design moves with data citations. Opinionated analyst output, not synthesiser output.
3. **Dev priorities as a prioritised plan** — not a teaser list, but a full ranked sequence with reasoning.
4. **Executive summary + print-ready design** — the artifact-shape difference (PDF, not web page).
5. **CSV dataset** — bundled in; raw data for buyers who want to run their own numbers.

Items 1–3 are what a reader can't produce from the free page no
matter how carefully they read it. That's the structural
differentiation; 6–10 of the friction list is the floor, not the
ceiling, of what buyers get.

### Pricing

| Product                       | Price  | Deliverable                                        |
|-------------------------------|--------|----------------------------------------------------|
| Genre Report                  | $49    | 35–45 page PDF + CSV dataset                       |
| Per-game pages                | $0     | Free forever, SEO-indexed                          |
| Genre summary pages           | $0     | Free forever, SEO-indexed (curated preview)        |

One Stripe Checkout button per report. No contact form, no manual
invoicing, no email scoping, no tier selector.

### Why this pricing

- **$49** is the psychological floor for a 35–45 page research PDF. Below that it reads as "low effort"; above it needs a quality justification for solo devs.
- **Single tier** because willingness-to-pay segmentation for a one-off PDF is fictional at launch. Every comparable (GameDiscoverCo, Lenny's, Stratechery, Zukowski) uses one price per product. Three SaaS-style tiers triple the implementation surface without adding validated revenue.
- **CSV bundled in** because it's cheap to produce and high-perceived-value. Moving it out of a former $149 tier and into the base $49 eliminates one tier's reason to exist.
- **Free on-site content** is the SEO engine. Every per-game page is a long-tail landing page. Every genre summary page ranks for mid-tail queries. Reports are the conversion target.

### Architecture

- **Payment:** Stripe Checkout (one-off purchase session, not subscription). See `stripe-checkout-report-delivery.md`.
- **Delivery:** S3 signed URL emailed on successful webhook. Buyer clicks link, gets PDF + CSV. No account, no login, no portal.
- **Content engine:** cross-genre synthesiser matview (`cross-genre-synthesizer-matview.md`) — Phase-4 LLM produces structured first draft; human curates to final report.

### Operator load

- ~60 hours editorial for Report #1; ≤ 40 hours for Reports #2+.
- ~$200 LLM cost per report (analysis + synthesis + prompt iteration).
- ~2 hours one-time amplification per report (one Reddit, one Bluesky, one community share).

## Tier 2 — Gated add-ons

Every add-on has a specific numerical gate. Gates are evaluated
quarterly. Do not write the prompt or build the surface until the
corresponding gate fires.

| Add-on                                         | Gate                                                                       |
|------------------------------------------------|----------------------------------------------------------------------------|
| Genre Q&A add-on ($79, pre-synth data + LLM)   | 10+ buyers explicitly ask for Q&A over the dataset                         |
| 1-yr All-Access Pass ($149, same genre family) | 5+ reports shipped in the family AND 100+ unique buyers                    |
| White-label / team license ($499)              | 3+ publisher emails requesting white-label or team share                   |
| "Alert me when a new report drops" email list  | Monthly uniques > 3k                                                       |
| "Genre Audit" self-serve SKU ($79)             | Catalog MRR > $3k/mo for 3 consecutive months                              |
| Paid newsletter                                | Free list > 1k engaged subs AND ≥ 5 buyers asking                          |
| Course ($249 one-off)                          | Newsletter at 1k engaged subs AND ≥ 3 buyers explicitly asking             |
| Subscription / membership tier                 | ≥ 5 paying buyers explicitly asking for ongoing access                     |

A standalone dataset SKU ($99 CSV+JSON per report) was formerly
gated here; it's now N/A because CSV is bundled into the base $49.
It would only return if CSV were ever removed from the base SKU.

## Verification — what "working" looks like

### Tier 1 launch signals (first 30 days after Report #1 ships)

- **First paid sale** at $49 — existence proof for the catalog model.
- **Stripe checkout conversion** from `/reports/[slug]` > 0.5%.
- **S3 signed-URL delivery** fires correctly on 100% of paid sales (webhook retry handled).
- **Plausible** shows ≥ 20 sessions/day by week 2 from SEO + one amplification event.
- **Lighthouse SEO** ≥ 90 on a random sample of per-game pages.

### Narrative / copy check

- Marketing copy on `/reports/[slug]` reads as "landscape vs plan," not "top-5 free vs top-10 paid."
- No "$149" / "$499" / "Studio" / "Publisher" language anywhere in checkout, report card, or homepage copy.
- Free `/genre/[slug]/` page contains landscape bullets only (no churn interpretation, no dev-priorities teaser).

### Tier 2 gate triggers

Each gate is a numerical trigger. Do not start Tier 2 work unless
the corresponding gate has fired for the required window. "Close
enough" does not count.

## Market anchors

Reference only — SteamPulse is a one-off catalog; comparables below
are subscription or breadth platforms.

- [GameDiscoverCo Plus](https://plus.gamediscover.co/) — $15/mo individual, $500/yr company. SteamPulse competes on per-niche depth, not newsletter cadence.
- [Gamalytic](https://gamalytic.com/pricing) — Starter $25/mo, Professional $75/mo. Breadth platform.
- [VGInsights](https://vginsights.com/) — indie plan ~$20/mo.
- [GG Insights](https://www.gginsights.io/) — freemium + lifetime-deal anchor.
- [Lenny's Newsletter](https://www.lennysnewsletter.com/) — $200/yr, 18k paid subs, 4–5% conversion. Reference for one-tier + bundled upsells.
- [Stratechery](https://stratechery.com/) — $120/yr, 26k paid. Reference for one-tier research subscription at scale.
- [Chris Zukowski Wishlist & Visibility Masterclass](https://www.progamemarketing.com/p/visibility-and-wishlist-masterclass) — $400 course; reference for indie-dev willingness-to-pay on one-off infoproducts.
