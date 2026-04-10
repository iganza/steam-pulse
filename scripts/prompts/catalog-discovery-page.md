# Catalog Discovery Page — Browse Analyzed Games & Coming Soon Queue

## Problem

Users arriving at SteamPulse have no way to browse which games have been analyzed.
Without a discovery surface, the only path to a report is searching by name — which
requires already knowing what you're looking for. This kills organic exploration and
makes the site feel empty at launch when only 200–300 games have reports.

## Principle

Add a `/catalog` page as the primary discovery surface. It answers two questions:

1. **"What can I read right now?"** — all analyzed games, browsable and filterable
2. **"What's coming next?"** — queued games and top-requested games, with voting

## Page: `/catalog`

Two tabs:

### Tab 1 — "Available Reports"
- Paginated grid/list of all games that have a completed analysis report
- Each item: cover art, game name, sentiment score, hidden gem badge if applicable
- Sort options: Newest Analysis · Most Reviews · Highest Sentiment · Hidden Gems
- Filter by genre and/or tag (reuse existing filter components)
- Each item links directly to `/games/[appid]/[slug]`

### Tab 2 — "Coming Soon"
- Top N games currently in the analysis queue (show queue position)
- Below that: top-requested games sorted by request count, with their request count visible
- Each row has an inline "Request Analysis" / upvote button
- Communicates platform activity: *"CS2 is next · 47 people requested Palworld"*

## Nav & Homepage Integration

- Add "Catalog" link to the main nav — this is the primary discovery surface
- Homepage should have a visible "Browse All Reports →" CTA pointing to `/catalog`

## API Needs

- `GET /api/catalog?sort=&genre=&page=` — paginated list of games with reports
- `GET /api/queue` — games currently queued + top requested (with counts)

## What NOT to decide yet

- Exact nav position and label (Catalog / Browse / Library)
- Card vs list layout
- Pagination vs infinite scroll
- Whether Coming Soon tab is visible at launch or added later

These are UI details to resolve when implementing. The principle is: users need a
browsable index of what exists and what's coming, accessible from the main nav.
