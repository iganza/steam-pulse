# Reports Page — Browse Analyzed Games & Coming Soon Queue

> **Status:** Implemented. Originally spec'd as `/catalog`, shipped as `/reports`.

## Problem

Users arriving at SteamPulse have no way to browse which games have been analyzed.
Without a discovery surface, the only path to a report is searching by name — which
requires already knowing what you're looking for. This kills organic exploration and
makes the site feel empty at launch when only 200–300 games have reports.

## Principle

Add a `/reports` page as the primary discovery surface. It answers two questions:

1. **"What can I read right now?"** — all analyzed games, browsable and filterable
2. **"What's coming next?"** — queued games and top-requested games, with voting

## Page: `/reports`

Two tabs:

### Tab 1 — "Available Reports"
- Paginated grid of all games that have a completed analysis report
- Each item: cover art, game name, sentiment score, hidden gem badge if applicable
- Sort options: Recently Analyzed · Most Reviews · Best on Steam · Hidden Gems
- Filter by genre and/or tag (reuse existing filter components)
- Each item links directly to `/games/[appid]/[slug]`

### Tab 2 — "Coming Soon"
- Games eligible for analysis (200+ reviews, no report yet) sorted by request count
- Each card has an inline "Request Analysis" button (email-based for anonymous users)
- Request count visible per game

## Nav Integration

- "Reports" link replaces "Hidden Gems" in the main nav
- Hidden Gems moved into the Browse dropdown footer

## API

- `GET /api/reports?sort=&genre=&tag=&page=&page_size=` — paginated list of games with reports
- `GET /api/reports/coming-soon?sort=&page=&page_size=` — analysis candidates with request counts
- `POST /api/reports/request-analysis` — submit {appid, email} to request analysis
- `GET /api/reports/request-count/{appid}` — get request count for a game

## Request Analysis

- Anonymous users enter their email to request analysis for a game
- Available on both the Coming Soon tab and individual game detail pages (when no report exists)
- `analysis_requests` table tracks (appid, email) pairs with UNIQUE constraint
- `mv_analysis_candidates` matview includes `request_count` for sorting
- Future: when auth is live, `user_id` column on `analysis_requests` will identify logged-in users
