# Launch Seed Strategy — Minimum Spend, Maximum Signal

## Context

SteamPulse has ~100k games in the DB, of which ~6,000 have 500+ reviews.
Analyzing all 6,000 up-front costs ~$2,040 (Anthropic API, ~$0.34/game).
This is wasteful at launch — long-tail games get almost no organic search traffic.

## Decision: Analyze Top 200–300 Games Only at Launch (~$70–100)

The top 200–300 games by review count cover ~80% of all Steam-related Google search
traffic. These are the "sure things": CS2, Elden Ring, Stardew Valley, Baldur's Gate 3,
etc. Anything below that threshold has negligible search volume at launch.

Run the pre-analysis seed targeting games with the highest `review_count_all` in the DB:

```bash
poetry run python scripts/sp.py queue analysis --top 300 --env production
```

Everything else gets a "Request Analysis" page (see below).

## Feature: "Request Analysis" Page

For any game that hasn't been analyzed yet, instead of a 404, show a page that:

1. Displays the game's metadata (name, tags, cover art, review count from Steam)
2. Shows: *"We haven't analyzed [Game Name] yet."*
3. Has a simple email capture form: *"Leave your email — we'll notify you when it's ready."*
4. Shows social proof: *"X people have requested this analysis"*

### Implementation notes

- New DB table: `analysis_requests (appid, email, requested_at)` — one row per request
- New API endpoint: `POST /api/request-analysis` — stores email + appid, returns request count
- Frontend: `/games/[slug]` checks if report exists; if not, renders `RequestAnalysisPage`
  component instead of the report
- Auto-trigger threshold: when a game accumulates ≥ 5 requests, add it to the analysis
  queue automatically (Step Functions trigger)
- Email notification: when analysis completes, send Resend email to all requesters for
  that appid, then delete their rows (or mark notified)

### Auto-trigger logic (in ingest/report completion handler)

```python
# After report is saved, check if any pending requests exist
pending = await request_repo.get_pending_emails(appid)
if pending:
    await notify_requesters(pending, game_name, slug)
    await request_repo.mark_notified(appid)
```

## Prioritization Logic (lower threshold over time)

| Phase | Trigger threshold | Rationale |
|---|---|---|
| Launch | 5 requests | Conservative — don't spend until clear demand |
| After first 50 analyses | 3 requests | Building momentum |
| After first $200 revenue | 1 request | On-demand for anyone |

## Why This Approach

- **Email list** is the most valuable launch asset — request flow captures it organically
- **Demand signal** — only spend $0.34 when someone actually wants it
- **Social proof** — "47 people have requested this" creates urgency and credibility
- **Re-engagement** — email notification brings users back to the site
- **Deferred cost** — the $1,900 remaining seed cost is funded by revenue, not up-front

## What to Build (in order)

1. `analysis_requests` table + migration
2. `AnalysisRequestRepository` — `upsert_request`, `get_count`, `get_pending_emails`, `mark_notified`
3. `POST /api/request-analysis` endpoint (rate-limit: 1 per IP per appid)
4. Frontend `RequestAnalysisPage` component for unanalyzed games
5. Auto-trigger: ingest handler checks request count after queuing, fires Step Functions if ≥ threshold
6. Email notification via Resend when report completes
