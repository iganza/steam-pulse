# Homepage performance — ISR + discovery-feed matview

## Problem

The production homepage at `https://steampulse.io` takes a long time to
render on first paint. Three compounding causes:

1. **No page-level caching.** `frontend/app/page.tsx:330` has
   `export const dynamic = "force-dynamic"`, which overrides every
   `next: { revalidate: ... }` on the underlying `apiFetch` calls. Every
   visitor triggers a fresh SSR render.

2. **Discovery rows bypass the matview layer.** The homepage fires five
   `/api/games?sort=...` calls (Most Popular / Top Rated / Hidden Gems /
   New on Steam / Just Analyzed) with **no `genre` or `tag` filter**.
   `GameRepository.list_games()` (see `game_repo.py:397-427`) only takes
   the `_list_from_matview()` fast path when a genre or tag is present;
   unfiltered calls fall through to the slow path at `game_repo.py:496`
   — `SELECT ... FROM games ORDER BY <col> LIMIT 8` against the full
   base table, with a per-row `EXISTS` subquery on `game_genres` for the
   `is_early_access` flag. This violates the mandatory
   "materialized-view read path" rule in CLAUDE.md.

3. **Homepage does 17 parallel API calls per render.** Five discovery
   rows + genres + grouped tags + nine per-game showcase endpoints
   (3 games × {report, review-stats, audience-overlap}) + sentiment
   trend. The server-side timeout is set to 25s specifically to absorb
   chained Lambda cold starts — that's a smell. Under ISR (step 1
   below) these only fire during revalidation, not per visitor.

## Goal

Make the homepage fast to render and cheap to serve, without changing
what it displays. Order of fixes below is by ROI.

## What to do

### 1. Turn the homepage into an ISR page

In `frontend/app/page.tsx`:

- Remove `export const dynamic = "force-dynamic"`.
- Add `export const revalidate = 300` (5 minutes — homepage content
  doesn't change faster than the matview refresh cadence).

This alone should deliver most of the perceived speedup: CloudFront +
Next.js ISR will serve the rendered HTML from cache for every visitor
between revalidations. Individual `apiFetch` calls already carry sensible
`revalidate` values; they continue to work under ISR.

Verify: `curl -I https://steampulse.io/` shows a `x-nextjs-cache: HIT`
header on the second request, and TTFB drops below ~100ms on cached
responses.

### 2. Add a `mv_discovery_feeds` matview for unfiltered catalog rankings

The discovery rows are 5 fixed, catalog-wide, unfiltered top-N feeds.
They are the canonical case for a pre-computed read path.

**Migration:** `0047_discovery_feeds_matview.sql`

```sql
-- depends: 0046_denormalize_has_ea_reviews
--
-- Pre-computed top-N per feed kind for the homepage discovery rows.
-- Bounded: at most ~5 * N rows — tiny matview, refresh is instant.
-- Each feed is a SELECT against the games base table ranked by the
-- column the homepage sorts on, with the same filters the live
-- endpoint applies (e.g. min_reviews=200 for top_rated).

DROP MATERIALIZED VIEW IF EXISTS mv_discovery_feeds;

CREATE MATERIALIZED VIEW mv_discovery_feeds AS
    -- feed_kind = 'popular'
    SELECT 'popular'::text AS feed_kind,
           ROW_NUMBER() OVER (ORDER BY g.review_count DESC NULLS LAST) AS rank,
           g.appid, g.name, g.slug, g.developer, g.header_image,
           g.review_count, g.review_count_english, g.positive_pct,
           g.review_score_desc, g.price_usd, g.is_free, g.release_date,
           g.deck_compatibility, g.hidden_gem_score, g.last_analyzed,
           g.estimated_owners, g.estimated_revenue_usd,
           g.revenue_estimate_method,
           EXISTS (SELECT 1 FROM game_genres gg
                   WHERE gg.appid = g.appid AND gg.genre_id = 70) AS is_early_access
    FROM games g
    WHERE g.review_count IS NOT NULL
    ORDER BY g.review_count DESC NULLS LAST
    LIMIT 24

  UNION ALL
    -- feed_kind = 'top_rated' (min 200 reviews, matches homepage filter)
    SELECT 'top_rated', ROW_NUMBER() OVER (ORDER BY g.positive_pct DESC NULLS LAST),
           g.appid, ..., ...
    FROM games g
    WHERE g.review_count >= 200
    ORDER BY g.positive_pct DESC NULLS LAST
    LIMIT 24

  UNION ALL
    -- feed_kind = 'hidden_gem' — hidden_gem_score DESC
  UNION ALL
    -- feed_kind = 'new_release' — release_date DESC, excluding coming_soon
  UNION ALL
    -- feed_kind = 'just_analyzed' — last_analyzed DESC
;

-- Unique index required for REFRESH CONCURRENTLY.
CREATE UNIQUE INDEX mv_discovery_feeds_pk_idx
    ON mv_discovery_feeds (feed_kind, rank);

CREATE INDEX mv_discovery_feeds_kind_rank_idx
    ON mv_discovery_feeds (feed_kind, rank ASC);
```

Guidance:
- Top-24 per feed is enough slack for the "See all" link preview and any
  future slight variation in what the homepage shows. The page only
  renders 8 (or 6 for Just Analyzed) today.
- Mirror in `schema.py::MATERIALIZED_VIEWS` and add to the drop-before-
  rebuild list in `create_matviews()`.
- Register in `MATVIEW_NAMES` in `matview_repo.py`. The existing refresh
  Lambda picks it up automatically (6h EventBridge + SQS-triggered
  refreshes with 5-minute debounce).

**Repository:** extend `MatviewRepository` with

```python
def list_discovery_feed(self, kind: str, limit: int = 8) -> list[dict]:
    """Top-N games for a homepage discovery feed (pre-computed).

    kind: 'popular' | 'top_rated' | 'hidden_gem' | 'new_release' | 'just_analyzed'
    """
```

Pure `SELECT ... FROM mv_discovery_feeds WHERE feed_kind = %s ORDER BY
rank LIMIT %s`. No business logic, no filter composition.

**API surface:** one new endpoint or five — your call. Simplest path:

```
GET /api/discovery/{kind}   → { games: [...] }
```

with `Cache-Control: public, s-maxage=300, stale-while-revalidate=600`.
Each homepage row fetches its own feed via `getDiscoveryFeed(kind)`.
This keeps the change isolated from the existing `/api/games` endpoint,
which continues to serve the filtered browse paths.

**Do NOT** extend `/api/games` to route to the matview based on
absence-of-filter. That entangles the two code paths and makes the
matview's update contract harder to reason about.

## Non-goals

- Do not rewrite `/api/games` to read from the new matview. The
  filtered-browse paths (search, genre, tag, publisher, etc.) must keep
  their current behaviour.
- Do not introduce an in-memory cache layer. The matview is the cache.
- Do not alter the 3-showcase tab component UI. We're only changing how
  the data reaches it.

## Verification

1. **Lighthouse / WebPageTest** on `steampulse.io/` before and after.
   Expect TTFB to drop from multi-second to <200ms on ISR hits.
2. **CloudWatch Logs** for the API Lambda: the number of
   `/api/games?sort=...` calls from the homepage path drops to zero
   (replaced by `/api/discovery/*`). The base-table `ORDER BY` query
   disappears from the slow-log.
3. **EXPLAIN** on `SELECT * FROM mv_discovery_feeds WHERE feed_kind =
   'popular' ORDER BY rank LIMIT 8` — expect an index-only scan on
   `mv_discovery_feeds_pk_idx`.
4. **Smoke test:** add a case to `tests/smoke/` for the new endpoint(s).
5. **Playwright:** existing homepage E2E tests should pass unchanged —
   if they break, it's a regression in what's displayed, not what's
   expected.
6. `poetry run pytest -v` and `poetry run ruff check .`.

## Refresh cadence / cost

`mv_discovery_feeds` is ~120 rows (5 feeds × 24). Refresh cost is
negligible. It's registered in `MATVIEW_NAMES` and inherits the existing
6h EventBridge cadence + SQS-triggered refreshes with 5-min debounce —
no new refresh path required.
