# Monetization direction

Canonical, forward-looking source of truth for SteamPulse monetization. Anything else in the repo that contradicts this doc is stale.

## The model

Hierarchy of value:

| Tier | What it is | Price |
|---|---|---|
| Free | Per-game preview pages (top 3 strengths, top 3 complaints, basic metadata) | $0 |
| Free | Showcase per-game pages (full per-game report, fully visible) | $0 |
| Paid (primary) | Monthly subscription, all genre reports current and future | $19/mo or $190/yr |
| Paid (alternative) | Single genre report, one-time purchase | $79 |
| Add-ons | Tag Doctor, Page Doctor, Niche Scout, Concept Doctor, etc. | $9 to $29 each |

### Free, in detail

**Showcase per-game pages: full report visible.** Auto-curating rule: any game named as a *benchmark game* in a published genre report gets full visibility on its per-game page. No email gate. No teaser bar. Buyers landing on a showcase page see the same depth they'd get if they paid, for that game.

**Standard per-game preview pages: abbreviated, free.** Every other analyzed game shows: top 3 design strengths, top 3 player complaints (each with one representative quote), basic metadata (price, release date, tags, review count, score), and one upsell line pointing at the relevant genre report. Substantive enough to rank in Google. Not enough that a buyer feels finished.

### Paid (primary): $19/mo or $190/yr subscription

What subscribers get:
- Access to every published genre report (current and future) for the duration of subscription
- All revisions and editorial improvements as they ship
- Email alerts when a new genre report drops
- The annual rate ($190/yr vs $228 if billed monthly) saves ~17%

### Paid (alternative): $79 one-time per genre report

For buyers who only want one specific genre and don't see ongoing value, e.g. a publisher evaluating a single pitch, a studio with an in-flight game in one genre. One-time buyers get the version current at purchase plus 30 days of revisions; after 30 days they keep what they downloaded but stop receiving updates.

Iteration criterion: if 4-week one-time conversion exceeds 4%, raise to $99; if under 1%, drop to $59 or remove the SKU and rely on subscription.

### Add-on micro-tools at $9 to $29

Tag Doctor, Page Doctor, Niche Scout, Concept Doctor, Pricing Doctor, Review Doctor. Sharp, single-question tools. Sell standalone or bundle into a genre report or subscription as a "free with subscription" upgrade.

## Production model: auto-generated v1, editorially improved over time

The genre report's v1 ships as the Phase 4 `mv_genre_synthesis` output formatted as a PDF. The LLM synthesis output is the v1; editorial polish happens iteratively post-launch:

- **v1:** auto-generated synthesis from the LLM pipeline, cleaned up and formatted as a PDF with cover, table of contents, methodology footer.
- **v1.5, v2, ...:** operator adds executive summary, sequencing decisions, cross-references, framing, charts, benchmark deep-dives.
- **Subscribers** receive every revision automatically.
- **One-time buyers** get the version current at purchase plus 30 days of revisions.

The marginal cost of a new genre report is the LLM run (~$70 to $145) plus a few hours of formatting.

## Deferred (Tier 2, by gate)

| SKU | Gate to ship |
|---|---|
| Agency white-label / team license ($200/mo unlimited, multi-seat) | 3+ publisher or agency emails request team access |
| Per-game one-time unlock ($9 to $19) | ≥ 10 buyers explicitly ask AND the genre report SKU has clear traction |
| Pro tier (ongoing analysis updates, $50 to $99/mo) | 10+ published genre reports + recurring buyer demand |
| Toolkit / chat / project workspace | Sustained MRR ≥ $1k/mo for 3 consecutive months |
| Add-on micro-tools as paid SKUs | First genre report ships AND ≥ 3 buyers explicitly ask for the tool standalone |
| Course or paid newsletter | Subscriber list > 200 AND ≥ 5 buyers asking |

If a gate fires, the SKU earns the right to ship. Otherwise it does not exist in the codebase.

## Buyer

Two segments self-segment by SKU:

**Solo indie devs and small studios → subscription.** Researching multiple genres over time, comparing wedge options, ongoing competitive intelligence.

**Publishers, scouts, agency / marketing leads → one-time $79 per relevant genre.** Need decision-quality intelligence for a specific pitch or game; don't need ongoing access. Reachable via direct outreach more than SEO funnel.

## What this is NOT

- Not a per-game-unlock model. Per-game pages are free forever as funnel and proof-of-depth.
- Not a pre-order play. The PDF ships before the buy block goes live.
- Not a pre-launch editorial slog. v1 ships from auto-generated Phase 4 output; editorial polish is iterative.
- Not "the toolkit replaces everything." Toolkit is deferred until sustained MRR clears the gate.

## Showcase commitment

Once a game is in the showcase set (full report visible, free), it stays there. No quiet downgrades. The "showcase = benchmark games of published genre reports" rule is what protects against bait-and-switch and removes the temptation to twiddle visibility per game.

No email gates on showcase pages. No teaser bars.
