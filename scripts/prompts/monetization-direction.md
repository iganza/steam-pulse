# Monetization

Single canonical source of truth for SteamPulse's monetization model and validation sequence. Anything in the repo that contradicts this is stale and should be brought into line.

## Model at a glance

Two-step funnel: free newsletter and free per-game pages build the audience; paid tiers convert the engaged 1-3%.

### Free (the funnel)

- Weekly newsletter on the wedge genre, hosted on Substack
- Per-game showcase pages (full per-game report visible, no email gate)
- Per-game preview pages (every other analyzed game: top 3 strengths, top 3 complaints, basic metadata, one upsell line pointing at the relevant genre report)
- One preview slice of the latest Phase 4 report on the site

### Paid (the SKUs)

| Tier | What | Price |
|---|---|---|
| Personal subscription | All published genre reports + every revision + Friday deep-dive newsletter + 3-5 rate-limited custom analyses/mo | $19/mo or $190/yr |
| One-time per genre | Single genre report + 30 days of revisions | $79 |
| Team license | 3-5 seats, all subscription content, invoicing | $500-1000/yr |

## Why this shape

The dominant shape for gaming-industry intelligence at this price point: GameDiscoverCo Plus ($15/mo or $150/yr personal, $500/yr company), MDM Pro ($9/mo personal + corporate seats $27-337/mo), Naavik Pro. Free newsletter as audience funnel, $9-15/mo personal tier converting the engaged 1-3% of free, corporate seats as the actual revenue driver. Pure-data SaaS dashboards (Gamalytic, VGInsights now Sensor Tower) trend toward enterprise pricing and acquisition by larger players, which is not the soft-launch path.

SteamPulse pricing is anchored to these comparables, with a slight premium ($19 vs $15) reflecting the deeper per-game and cross-cohort synthesis the Phase 3/4 pipeline produces.

## Validation sequence

The site is in soft launch with ~0 traffic, no email list, no community ties yet. Operator has committed to a weekly newsletter for 6-12 months as the primary acquisition channel. ICP (indie solo dev / studio / publisher analyst) is not yet validated. Run this sequence before scaling paid surface or building any subscriber-only toolkit.

### Phase A: Distribution infrastructure (week 1-2)

1. Stand up newsletter platform on Substack (lowest friction; has its own discovery network that helps a cold launch).
2. Wire email capture into the homepage and every per-game showcase page. Single CTA, no overlay, no email gate.
3. Write newsletter issue #1: condense the existing Phase 4 RDB synthesis into a 1500-2500 word readable post on Substack with a public URL.
4. Set up cross-linking between site and newsletter (canonical link, RSS).
5. Identify one primary seeding community (r/IndieDev, r/roguelikes, or the most active RDB-adjacent Discord).

### Phase B: Community presence (parallel with A, week 1-4)

1. Join 2-3 target communities (Discord servers + subreddits).
2. Lurk and helpfully answer questions for 2 weeks. No promotional posts in this window.
3. Build face recognition. People who have seen you help others will respond when you eventually post the artifact.
4. Inventory warm intros from the operator's existing network: "Do you know any roguelike-deckbuilder devs who'd benefit from this?" One warm intro outperforms 30 cold DMs.

### Phase C: Public artifact + ICP signal collection (week 3-6)

1. Post newsletter issue #1 in the primary community as a collaborative finding ("here's what I found across 141 RDB games, what am I missing?"), not a pitch.
2. Attach an opt-in CTA: "If your game's in this report, reply or fill this form to claim a free Phase 3 deep-dive."
3. Run 10-15 conversations with respondents using The Mom Test methodology. Never ask "would you pay?". Ask: what was the last thing you spent money on for your game, what do you do today when you want to understand competitor X, walk me through the last decision you made.
4. Track three signals per respondent:
   - Did they show up to the call?
   - Did the report change a decision they were going to make?
   - Did they offer money or refer a friend without prompting?
5. The ICP is whoever showed all three signals most often. Not whoever said the nicest things.

### Phase D: Concierge + pre-sale (week 6-10)

1. Manually generate up to 10 reports per week for the validated ICP at $79 each one-time. Operator runs the Phase 3 pipeline by hand for each buyer; collect payment via direct invoice or a pre-built Stripe payment link (no Checkout self-serve yet).
2. Track repeat purchase rate. Goal >20%. Below that, the model is wrong; iterate ICP or pricing before scaling.
3. Offer the same buyers a $19/mo founding-member tier for ongoing access.
4. Goal: 10 founding members committed before any paid-surface code ships.

### Phase E: Build paid surface (week 10+, gated on Phase D)

Only triggered if Phase D produced 10 founding members. Reuses the work already specced in `scripts/prompts/better-auth-setup.md`, `scripts/prompts/stripe-resend-setup.md`, and `scripts/prompts/rdb-launch-spec.md` (Section 5: Stripe + entitlement schema).

1. Better Auth + Stripe + Resend backend per the existing specs.
2. Genre page buy block + paid-mode rendering.
3. Migrate concierge customers to self-serve via magic-link onboarding.
4. Add team-seats SKU ($500-1000/yr) when 3+ studios/publishers ask.

### Phase F: Compounding catalog (week 12+)

- Weekly newsletter cadence locked. One issue every Friday.
- One new genre report every 6-8 weeks. Marginal cost: $70-145 LLM run + a few hours of formatting + ~$5/mo synthesiser refresh per niche. Each new report adds 3-5 showcase games automatically via the `benchmark_appids` rule.
- Quarterly evaluation of deferred-tier SKUs.

## Anti-patterns

1. Do not build a subscriber-only toolkit before the ICP is validated. Subscriber toolkit is deferred until sustained MRR ≥ $1k/mo for 3 months.
2. Do not target three ICPs simultaneously. Pick the path Phase C points to and ship one product for one buyer.
3. Do not price below $9/mo. Below that, churn from credit-card friction kills you and the customer signal is too weak to learn from.
4. Do not skip the newsletter. It is the only acquisition channel that has worked for every comparable in this category. Without it, CAC for a $19/mo SaaS is ~$50-200 from paid ads, upside-down on a 3-month median consumer-SaaS retention.
5. Do not make Phase 4 reports fully crawlable. Paywall the synthesis layer; keep per-game showcase pages public for SEO.
6. Do not cold-DM strangers as customer development. Use opt-in attraction (public artifact + CTA, warm intros, helpful presence in communities).
7. Do not ship paid surface (Stripe + Better Auth + buy buttons) before Phase D founding members are on the books.

## Production model

v1 of each genre report ships as the Phase 4 `mv_genre_synthesis` output formatted for delivery: PDF for buyers, HTML on the genre page for paid mode, condensed text for the newsletter. Editorial polish happens iteratively post-launch:

- v1: auto-generated synthesis from the LLM pipeline, formatted with cover, table of contents, methodology footer.
- v1.5+: executive summary, sequencing decisions, cross-references, framing, charts, benchmark deep-dives.
- Subscribers receive every revision automatically.
- One-time buyers get the version current at purchase plus 30 days of revisions; after 30 days they keep what they downloaded but stop receiving updates.

## Showcase commitment

Once a game is in the showcase set (full report visible, free), it stays there. No quiet downgrades. The rule: "showcase = benchmark games of published genre reports." This protects against bait-and-switch and removes the temptation to twiddle visibility per game. No email gates on showcase pages. No teaser bars.

## Deferred (gate-driven)

Every item below requires its gate to fire before any implementation work begins. Gates evaluated quarterly.

| SKU | Gate to ship |
|---|---|
| Subscriber-only toolkit / chat / project workspace | Sustained MRR ≥ $1k/mo for 3 consecutive months |
| Pro tier ($50-99/mo) | 10+ published genre reports AND recurring buyer demand |
| Per-game one-time unlock ($9-19) | ≥ 10 buyers explicitly ask AND any single genre has ≥ 10 sales |
| Add-on micro-tools as paid SKUs (Tag Doctor, Page Doctor, Niche Scout) | First genre report ships AND ≥ 3 buyers ask for the tool standalone |
| PDF/CSV export of any genre report | ≥ 3 buyers explicitly request offline/sharable export |
| Course / second paid newsletter | Free subscriber list > 200 AND ≥ 5 buyers asking |

If a gate fires, the SKU earns the right to ship. Otherwise it does not exist in the codebase.

## Sources

- [GameDiscoverCo Plus subscription](https://newsletter.gamediscover.co/p/gamediscoverco-plus-subscribe-today)
- [GameDiscoverCo about](https://newsletter.gamediscover.co/about)
- [How GameDiscoverCo launched a data product (Simon Owens)](https://simonowens.substack.com/p/how-the-gamediscoverco-newsletter)
- [MDM Pro pricing](https://mobiledevmemo.com/subscribe/)
- [Mobile Dev Memo about](https://mobiledevmemo.com/about/)
- [How To Market A Game (Chris Zukowski)](https://howtomarketagame.com/)
- [Pro Game Marketing courses](https://www.progamemarketing.com/)
- [Naavik](https://naavik.co/)
- [Gamalytic](https://gamalytic.com/)
- [Video Game Insights (Sensor Tower)](https://app.sensortower.com/vgi/)
- [Deconstructor of Fun](https://www.deconstructoroffun.com/)
- [GameDeveloper.com: DIY market research for indies](https://www.gamedeveloper.com/business/a-guide-to-diy-market-research-for-indie-developers)
