# Product Ideas — Running Brainstorm

Living doc for product/feature ideas that come out of informal conversation
during development. NOT a spec. NOT a roadmap. Ideas here are captured for
later triage — they have not been scoped, sized, or committed to.

When an idea here gets picked up for real work, move it into its own spec file
under `scripts/prompts/` with a proper design + file manifest, and either
delete the entry here or leave a one-line pointer ("→ topics-tab.md").

---

## Texture Report Page (Game Detail)

The narrative `GameReport` we render today is only about a third of what
Phases 1-3 actually produce. The `chunk_summaries` and `merged_summaries`
tables contain structured topic data (with verbatim quotes, playtime,
helpful votes, per-topic sentiment) that no current UI surfaces. A
"textured report page" that lights all of that up would be a visually
distinct, shareable artifact with strong SEO and cross-linking potential.

### Zero-new-LLM ideas (repository + endpoint + component only)

- **Topic heatmap / chip cloud.** Pull merged `topics`, color by
  `sentiment`, size by `mention_count`. Click a chip → drawer.
- **Topic drawer with verbatim voices.** Each topic's 3 quotes with
  `[[steam:<id>]]` deep links, reviewer playtime, helpful votes,
  voted_up/down. The signature move.
- **Player journey / churn-trigger timeline.** Render `churn_triggers`
  as a horizontal timeline with ranked `dev_priorities` adjacent. Dev
  audience eats this.
- **Store-page reality-check card.** Render `store_page_alignment` as
  three columns: promises delivered ✅ / broken ⚠️ / hidden strengths 💎.
  No other Steam-analysis site does this.
- **Sentiment by playtime bucket × topic overlay.** Overlay topic-level
  `avg_playtime_hours` on the existing playtime-sentiment chart —
  "10+ hour players mostly complained about X; <2 hour players mostly
  complained about Y." The churn-cliff story in one chart.
- **Wishlist vs friction split.** `player_wishlist` beside
  `gameplay_friction`, color-coded. Pairs with the churn-trigger timeline.
- **Competitive context strip.** `competitive_context` entries as
  horizontally-scrolling cards, cross-linked to that game's report on
  our site if present. SEO win.
- **Topic category donut.** Single-glance health read across all 9
  categories. Already computable from `chunk_summaries.summary_json` via
  a jsonb aggregate.
- **Signal-strength gauges** for `content_depth`, `refund_signals`,
  `community_health`, `monetization_sentiment`. Little dials per section.
- **Playable quote carousel.** Auto-rotating verbatim quotes per topic,
  like a testimonial strip. Pure component work.

### One-small-LLM-call ideas

- **3-paragraph "what this game is really like" narrative.** Single
  cinematic paragraph from the merged_summary, ~300 words, cached per
  pipeline version. Read-aloud voice distinct from the structured
  `GameReport`.
- **Per-topic 1-sentence meta-summary.** Parallel pass over topics to
  re-narrate each one across its merged quotes, giving each chip a
  consistent voice. Could defer until Topics tab is up.

### Suggested staging

1. **Topics tab on the existing game page.** `GET /api/games/{appid}/topics`
   reading from `merged_summaries` + `chunk_summaries`. Chip cloud → drawer.
   Immediate "whoa" factor, no new LLM calls, self-contained PR.
2. **Texture pass on the report route.** Churn-trigger timeline,
   wishlist/friction split, signal gauges. Component work over existing
   `report_json` fields.
3. **Competitive context cross-linking + SEO.** The card strip.
   Biggest SEO lift once there's a population of reports to link to.

---

## Chunk-Level Drill-Down (Pro feature candidate)

From the (textured) report page, a "dig deeper" link that takes Pro users
into the raw Phase 1 artifact layer — every `chunk_summaries` row rendered
as a scannable list. We already store everything; nothing to extract from
the LLM twice.

### What exists in `chunk_summaries` we can mine

Per chunk (so, typically 40 per game @ 2000 reviews / 50 per chunk):

- `chunk_index`, `review_count`, `created_at`, `model_id`, `prompt_version`
  — provenance the Pro user trusts.
- `batch_stats` — positive/negative split for that slice, avg playtime,
  high-playtime count, early-access count, free-key count, date range.
  This is a **50-review mini-Steam-Review for that slice**.
- `topics` — full list of `TopicSignal` objects (category, sentiment,
  mention_count, confidence, summary, quotes, avg_playtime_hours,
  avg_helpful_votes). Every topic the LLM pulled out of just those 50
  reviews.
- `competitor_refs` and `notable_quotes` for that chunk.

Across all chunks for a game, joined in aggregate:

- **Topic trajectory over time** — each chunk carries `date_range_start /
  date_range_end` from `batch_stats`. Plot a topic's mention_count across
  chunks ordered by date to see "refund complaints surged in February".
- **Topic co-occurrence matrix** — which topics show up in the SAME
  chunks? Strong co-occurrence between `matchmaking latency` and
  `refund_signals` is a different story from two isolated signals.
- **Topic sentiment drift** — a single topic's sentiment across chunks.
  "Base building" starts positive, turns mixed after a patch — the
  matview flow can catch this with the per-chunk date range.
- **Outlier chunk detection** — a chunk where sentiment diverges sharply
  from the game-wide average is likely a patch window or a review-bomb
  event. Flag it, show the date range, let the user jump in.
- **Quote provenance explorer** — every quote has `steam_review_id`,
  `voted_up`, `playtime_hours`, `votes_helpful`. A sortable/filterable
  table of ALL quotes across all chunks is a data-mining playground for
  a dev who wants to read the raw voice by hand.

### Product shape ideas

- **Chunk list view (free-ish).** A table of chunks: `chunk_index`,
  date range, positive/negative split, top 3 topics, a "view" arrow.
  Could be free — it's just the batch_stats projected into a grid.
- **Chunk detail drawer (Pro).** Click a chunk → show all its topics +
  quotes + competitor refs. Basically the `_dump_chunk_phase` org dump
  rendered as HTML. This is where "dig deeper" pays off for a paying
  customer.
- **Topic trajectory chart (Pro).** Pick a topic → line chart of its
  mention_count over chunks ordered by date range. Simple line chart,
  huge insight.
- **Raw quote explorer (Pro).** All quotes across all chunks, filterable
  by category / sentiment / playtime bucket / votes_helpful. The
  power-user view.
- **"Patch impact" detector (Pro).** Given a known patch date, split the
  chunk set before/after and diff the top topics and their sentiment.
  "After the 1.4 patch, `matchmaking latency` mentions dropped 40% but
  `balance complaints` rose 25%." Huge for devs evaluating their own
  game or studying a competitor.

### Why this is a good Pro hook

- **Zero additional LLM cost** — every drill-down view reads from data
  Phase 1 already produced and persisted.
- **Clear value gradient** — the narrative report (free) summarizes;
  the chunk drill-down (Pro) lets you read the community's voice
  directly, sorted by provenance. That's a natural "show me the
  receipts" upgrade.
- **Defensible** — no other Steam-analysis site exposes this level of
  structure. Steam's own review UI is a flat unsortable timeline.
- **Lead-gen friendly** — the chunk list (free) teases that there are
  40 of these per game; clicking any one of them promos the Pro upgrade.

### Prerequisites

- `TopicRepository` (already in the Data-Layer Ideas section below).
  Probably extend to include `chunk_list(appid)`, `chunk_detail(chunk_id)`,
  `topic_trajectory(appid, topic)`, `quote_search(appid, filters)`.
- Auth / Pro-tier gating — not yet built. This idea parks until the
  auth story lands (tracked separately).

---

## Cross-Game Queries / Matviews

Once topic data is populated across many games, several cross-game
aggregates become interesting:

- **Top 50 games with the most `technical_issues` topics per 1000
  reviews.** Matview candidate (`mv_topic_category_counts`).
- **Most-mentioned competitors across the catalog** — which games get
  name-dropped in reviews of OTHER games most often? Network graph.
- **Shared churn triggers by genre** — do "grind wall" complaints cluster
  in ARPGs? Do "matchmaking latency" complaints cluster in competitive
  multiplayer? Genre-level insights page.
- **Store-page alignment stats by developer / publisher.** "This publisher's
  store pages have an average of 2.3 broken promises per game." Brutal but
  interesting.

All of these follow the project's "read path = matview or denormalized
column" rule in CLAUDE.md — not live queries against `chunk_summaries` at
request time.

---

## Data-Layer Ideas

- **TopicRepository.** New repository class over `chunk_summaries` and
  `merged_summaries` exposing `category_counts(appid)`, `top_topics(appid,
  limit, category=None)`, `topic_quotes(appid, topic)`. Prep work for
  the Topics tab UI — no new storage, just repository methods reading
  the JSONB.
- **`GameReport` split.** Move LLM-owned fields off the pydantic model
  shared with persistence, so server-owned fields (`appid`,
  `pipeline_version`, bookkeeping) don't leak into the LLM schema.
  Flagged during PR #67 review — deferred, not urgent.
  
## Added Notes

Absolutely — the three-phase pipeline extracts remarkably structured signal. The TopicSignal objects with category, sentiment, mention counts, confidence
  levels, playtime context, and verbatim quotes are essentially a quantified voice-of-the-player dataset. That's gold for:

  - Devs: prioritized bug/friction lists with player effort context, churn trigger timing, wishlist items ranked by demand
  - Marketing: audience archetypes, competitive positioning quotes, sentiment trends to time campaigns around
  - Publishers: portfolio-level views across genres — which friction patterns repeat, which design choices correlate with positive sentiment
  - Investors/analysts: revenue estimate × sentiment trend × content depth as a signal for game health

  The Pro section you have planned is the right place for this. Cross-analysis across genres/tags/developers is where the real differentiation lives — nobody
   else has structured, LLM-extracted topic signals at catalog scale that you can slice by genre, price tier, or player archetype.

---

## Capture Process

If you think of something here, drop it in as a bullet or a short
section. No need to structure it. The triage step is:

1. Read this file at the start of a planning session.
2. Pick one. Write it up properly under `scripts/prompts/<name>.md` with
   file manifest + tests + acceptance criteria.
3. Delete the brainstorm entry or replace with a pointer.


