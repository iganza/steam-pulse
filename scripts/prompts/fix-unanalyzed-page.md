# Fix the un-analyzed game page (trust + conversion hygiene)

*Drop-in prompt for Claude Code in the SteamPulse project repo.*

---

## Context

The SteamPulse site shows two tiers of per-game pages:

- **Full-report page** (example: https://d1mamturmn55fm.cloudfront.net/games/1086940/baldurs-gate-3-1086940) — an LLM has generated a deep analysis. This page is working as intended.
- **Un-analyzed page** (example: https://d1mamturmn55fm.cloudfront.net/games/105600/terraria-105600) — the game has computed-data signals (Boxleiter revenue estimate, owner estimate, sentiment percentile, tags) but no LLM report yet. **This is the page this task fixes.**

The un-analyzed page has genuine value vs. SteamDB (revenue + owner estimates, contextualized sentiment, methodology transparency). However, it fumbles trust in three specific ways that need to be corrected before the site is publicly marketed.

## Why this matters

An un-finished-looking free tier undermines paid-conversion on the same visit. If a dev hits an un-analyzed page via SEO, their trust signal is formed in ~8 seconds — empty chart widgets and a weak CTA both damage that. These are small changes with outsized funnel impact.

## Goals (measurable)

After this work, an un-analyzed page should:

1. Have **zero empty chart / section placeholders.** Either render real data, render a tasteful "not enough data for this game yet" inline message, or remove the section.
2. Present **data freshness as a confident statement**, not a defensive one.
3. Convert visits to **email signups** (not just outbound clicks to Steam).
4. Keep the visitor **on-site** by surfacing at least 3 related analyzed games when available.
5. Preserve the brand voice: cited, peer-to-peer, no "AI-powered," no "unlock."

## The four specific changes

### Change 1 — Kill the empty chart placeholders

**Current state (verified in code):** `SentimentTimeline` already returns `null` below 2 data points and `PlaytimeChart` already returns `null` below 50 reviews — so today the section simply disappears. The issue is the silent disappearance, not a blank widget.

**Required behavior:**
- For **Sentiment History**: if you have ≥3 longitudinal data points, render the chart. Below 3 points, render an inline stub that keeps the section header visible:
  > *"Sentiment history: first crawl {date}. Tracking weekly going forward — chart appears at 3+ data points."*
  Keep the section header so returning visitors see it populate over time.
- For **Playtime Sentiment**: keep current behavior (section hides below 50 reviews). Most games don't have sufficient data; don't pretend.

**Acceptance:** no page state renders a blank, loading, or empty chart component. Sentiment History always shows either a chart or a one-line informative stub.

### Change 2 — Reframe data freshness

**Current state:** "Crawled 30d ago" — reads as defensive (is 30d stale?).

**Required behavior:** Replace with a confident, informative sentence directly beneath the Steam Facts block:

> *"Data current as of {date_crawled}. We re-crawl reviews and metadata every {N} days."*

- Use a hardcoded cadence constant (`CRAWL_CADENCE_DAYS = 14`) in the frontend. We don't have the actual cadence surfaced today and the simplest thing is a single owned number matching operator intent.
- If the crawl is more than 90 days old, render in an amber/warn color with the line: *"Refresh queued — this page will update within {N} days."*
- If less than 30 days old, no emphasis — plain text.

**Acceptance:** no visitor should wonder whether the data is fresh. The cadence is owned, not apologized for.

### Change 3 — Replace the weak CTA with an email waitlist

**Current state (verified in code):** `RequestAnalysis.tsx` already captures email → `POST /api/reports/request-analysis` → `analysis_requests` table, and already returns a request count. The UX is just too thin: a teal button + inline input, no context, no social proof, no reason to care.

**Required behavior:**

**Redesign `RequestAnalysis.tsx` in place** into a full waitlist card. Same API contract, same DB table (`analysis_requests`). Copy:

> **Get the full SteamPulse report on {game_title} when it's ready.**
>
> A SteamPulse report covers player sentiment clusters, wishlist signals, retention friction points, and competitive context — cited, ~5,000 words.
>
> **{N} devs waiting** · usually ready within 2 weeks of hitting ~20 requests
>
> [ email input ] [ Notify me ]
>
> *No spam. One email when the report is ready. Unsubscribe anytime.*

Technical notes:
- Keep the existing `analysis_requests(appid, email, created_at)` table — no migration. (The shipped table name is `analysis_requests`, not `game_report_requests`.)
- The "N devs waiting" counter is already returned by the existing API; just render it. Show "Be the first to request this analysis." when zero.
- On submit: card replaces itself with *"You're on the list. We'll email you when {game_title}'s report is ready."*
- Fire `track('report_waitlist_signup', { appid })` via a new no-op `frontend/lib/track.ts` hook (`console.log` in dev, no-op in prod). A real analytics provider can be plugged into the hook later; call sites land now.

**Keep** the outbound Steam store link — but demote it to a secondary text link, not the primary CTA. (It already exists in the page footer; just don't re-promote it in the CTA card area.)

**Acceptance:** the primary CTA on an un-analyzed page is the email waitlist card. Email submits call `track()`. The counter shows real demand.

### Change 4 — Surface related analyzed games

**Current state:** no cross-link from an un-analyzed game to analyzed neighbors.

**Required behavior:** add a "More games like this" section below the waitlist card. Show up to 6 analyzed games ranked by tag overlap with the current game, descending. Each card links to the analyzed game's full report page.

Logic:
- New SQL function `game_tag_overlap(target_appid, limit_n)` in a new migration (`0051_game_tag_overlap_fn.sql`), computing a weighted shared-tag count against `game_tags`, filtered to `appid` present in `reports`.
- Repository method `find_related_analyzed(appid, limit=6)` joins the overlap result to `games` + `reports`, selecting `appid, slug, name, header_image, positive_pct, report_json->>'one_liner'`.
- If fewer than 3 analyzed games share tags, fall back to "Recent SteamPulse reports" — latest 6 rows from `reports` joined to `games`.
- Each card: game title, sentiment percentile chip, one-line `one_liner` from the report JSON (no schema change; extracted via `report_json->>'one_liner'`). If the JSON is missing `one_liner`, omit the line silently.

**Acceptance:** every un-analyzed page has a path to at least 3 full reports on-site. No dead ends.

## Voice + tone guardrails (apply to all copy changes)

- **Do NOT use:** "AI-powered," "AI-generated," "AI-suggested," "unlock," "revolutionize," "game-changer," "intelligent," "insights" (overused).
- **DO use:** "research," "analysis," "synthesis," "cited," "data-backed," "LLM-synthesized" (only when technical transparency is required).
- **Tone:** peer-to-peer, cited, understated. The site is built by a Steam dev for Steam devs. No vendor-to-customer register.

## Non-goals / don't touch

- Do not change the layout or styling of the full-report page (BG3 example). That page is working.
- Do not refactor the Boxleiter methodology link or the revenue/owner estimate components — they're correct.
- Do not add any new Steam data fields. This task is about trust + conversion on the existing data.
- Do not build the analysis queue processing logic (that's a separate task). Only capture the email + show demand.
- Do not change routing. `/games/[appid]/[slug]` stays exactly as-is.

## Verification

After the changes, visit both example URLs in a clean browser session and verify:

1. **Terraria page** (un-analyzed):
   - No empty chart widgets render
   - Data freshness sentence is present and correct
   - Email waitlist card is the primary CTA
   - "More games like this" section shows at least 3 analyzed games
   - Submitting an email adds a row to `game_report_requests`
   - Analytics event fires on submit

2. **Baldur's Gate 3 page** (analyzed): unchanged. No regression.

3. **Visual pass on mobile** (375px width): all new components render cleanly, no overflow.

## Rollout

Pre-launch — just ship the new path. No feature flag, no dual-path fallback. The un-analyzed page has zero users today.

---

## Why each change matters (for the PR description)

- **Empty charts:** biggest trust-killer on the page. "Broken" reads worse than "not yet available."
- **Freshness reframe:** subtle; moves the page from defensive to informative.
- **Email waitlist:** turns every un-analyzed page into a conversion surface. Replaces a weak outbound click with a measurable owned-audience signal.
- **Related analyzed games:** keeps visitors on-site, increases pages-per-session, and showcases the full-report tier as the paid-conversion funnel.
