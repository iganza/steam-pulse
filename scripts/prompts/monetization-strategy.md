# Monetization strategy — two-tier catalog model

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

The entire business for the first 12+ months.

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
PDF — $49. Ships [date]."* Stripe Checkout captures payment
immediately; the Stripe webhook writes a `report_purchases` row; the
delivery worker sees `reports.published_at > now()` and holds the
S3-URL email until ship date. Pre-orders are a deposit-based
commitment, not a free waitlist. If pre-orders are zero after two
weeks of traffic, the positioning or the product-shape is wrong; do
not commit 60 hours of editorial.

**Phase C** is the 60 hours of human editorial work. It fires only
if the Phase B → C demand gate fires — evaluated 2 weeks after the
pre-order block goes live:

- **≥ 3 pre-orders at any paid tier** → commit the 60 hours. Write the exec summary + benchmark deep-dives + strategic recs. Upload PDF assets. Flip `reports.published_at` to `now()`; the delivery worker sweeps the queue and emails every pre-order buyer their signed URL. Self-serve checkout delivers inline from that point onward.
- **1–2 pre-orders** → marginal but real. Ship Phase C with a tighter scope.
- **0 pre-orders** → do NOT write the PDF. Remove the `reports` row or extend `published_at` indefinitely. The free curated-preview page stays live as SEO. Talk to anyone who reached the page but didn't convert before iterating positioning.

### The product

Self-serve catalog of flagship PDF genre reports. One new report per
quarter. Each report is the whole-niche cross-cutting synthesis of a
single Steam genre: friction points, wishlist items, benchmark games,
churn timing, ranked dev priorities — all quote-backed.

### Free vs paid — what differentiates the tiers

The free `/genre/[slug]/` page is a **curated preview** with a named
human author; the paid PDF is the **full analysis**. They share an
underlying synthesiser run but are different artifacts:

- the free page proves the research is real and drives SEO + AI-citation traffic
- the paid PDF is the depth, the editorial, the dataset, the printable artifact

Curation on the free page is load-bearing for two reasons: Google's
March 2026 core update demotes mass-produced AI content without
human editing or named-expert attribution, and the
anti-cannibalisation rule is that AI assistants should be able to
*cite* but not *finish* the buyer's question from what's public.

| Artifact                     | What it is                                                                                                                                                                                                    | Price  |
|------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------|
| Free `/genre/[slug]/` page   | Curated preview: named-author byline, 200–300 word editorial intro, top-5 friction clusters with quotes + mention counts, top-3 wishlist items, 3 benchmark game cards with pull-quotes, churn stat + one-line editorial interpretation, 2-row dev priorities teaser, methodology footer | $0     |
| Indie PDF                    | Full synthesis (all 10 friction / all 10 wishlist / all 5 benchmark games with quotes + context), plus 3-page executive summary, 15–20 pages of hand-written benchmark game deep-dives, strategic recommendations chapter, full dev priorities table, expanded methodology, print-ready design, cover page | $49    |
| Studio PDF + CSV             | Indie + CSV dataset of every friction / wishlist / benchmark with source_appid columns for independent analysis + 1-year update access                                                                        | $149   |
| Publisher PDF + CSV + JSON   | Studio + raw JSON payload of the synthesis + team license (up to 10 seats)                                                                                                                                     | $499   |

What justifies the $49 — what's missing from the free page:

1. The other 5 friction clusters (items 6–10), each with full quote sets
2. The other 7 wishlist items (items 4–10)
3. The other 2 benchmark games plus 15–20 pages of hand-written deep-dives on all 5 (Slay the Spire / Balatro / Inscryption / Monster Train / Dicey Dungeons)
4. Full dev priorities table + strategic recommendations chapter
5. Executive summary + editorial sequencing + print-ready design

Deep-dives are not in the Phase-4 synthesiser output — they are
hand-written editorial. That's the structural difference: the free
page is a curated window onto the data; the PDF is the window plus
original human-written analysis no amount of reading the free page
produces.

### Pricing

| Product                       | Price  | Who it's for                                | Deliverable                                      |
|-------------------------------|--------|----------------------------------------------|---------------------------------------------------|
| Genre Report — Indie tier     | $49    | Solo devs, hobbyists, curious individuals    | 35-45 page PDF                                    |
| Genre Report — Studio tier    | $149   | Small teams (≤ 10 people)                    | PDF + CSV dataset + 1-year update access          |
| Genre Report — Publisher tier | $499   | Studios, publishers, fund managers, analysts | PDF + CSV + raw JSON + team license               |
| Per-game pages                | $0     | Everyone, indexed for SEO                    | Free forever                                      |
| Genre summary pages           | $0     | Everyone, indexed for SEO                    | Free forever                                      |

All three paid tiers are fully self-serve Stripe buttons. No contact
form, no manual invoicing, no email scoping. If a publisher needs
more than what's in the tier, they buy the tier and email; that's a
bonus, not a prerequisite.

### Why this pricing

- **$49** is the psychological floor for a 35-45 page research PDF. Below that it reads as "low effort"; above it needs a quality justification for solo devs.
- **$149** is 3× indie — the standard "I'm buying this with company money" anchor across adjacent infoproduct markets.
- **$499** captures studio/publisher willingness-to-pay without a sales motion. Comparables: GameDiscoverCo Company plan $500/yr; IndieWorldOrder reports $299–$999.
- **Free on-site content** is the SEO engine. Every per-game page is a long-tail landing page. Every genre summary page ranks for mid-tail queries. Reports are the conversion target.

### Architecture

- **Payment:** Stripe Checkout (one-off purchase session, not subscription). See `stripe-checkout-report-delivery.md`.
- **Delivery:** S3 signed URL emailed on successful webhook. Buyer clicks link, gets PDF/CSV/JSON. No account, no login, no portal.
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
| Dataset add-on ($99 CSV+JSON per report)       | 3+ buyer emails asking for raw data                                        |
| "Alert me when a new report drops" email list  | Monthly uniques > 3k                                                       |
| $49/yr All-Access Pass (catalog-wide)          | 5+ reports shipped AND 100+ unique buyers                                  |
| "Genre Audit" self-serve SKU ($79)             | Catalog MRR > $3k/mo for 3 consecutive months                              |
| Paid newsletter                                | Free list > 1k engaged subs AND ≥ 5 buyers asking                          |
| Course ($249 one-off)                          | Newsletter at 1k engaged subs AND ≥ 3 buyers explicitly asking             |
| Subscription / membership tier                 | ≥ 5 paying buyers explicitly asking for ongoing access                     |

## Verification — what "working" looks like

### Tier 1 launch signals (first 30 days after Report #1 ships)

- **First paid sale** lands on any tier — existence proof for the catalog model.
- **Stripe checkout conversion** from `/reports/[slug]` > 0.5%.
- **S3 signed-URL delivery** fires correctly on 100% of paid sales (webhook retry handled).
- **Plausible** shows ≥ 20 sessions/day by week 2 from SEO + one amplification event.
- **Lighthouse SEO** ≥ 90 on a random sample of per-game pages.

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
- [Chris Zukowski Wishlist & Visibility Masterclass](https://www.progamemarketing.com/p/visibility-and-wishlist-masterclass) — $400 course; reference for indie-dev willingness-to-pay on one-off infoproducts.
