# Split sitemap.xml into a sitemap index to escape the 6 MB Lambda response cap

## Problem

`https://steampulse.io/sitemap.xml` returns HTTP 502. CloudWatch on `FrontendFn`
shows the real cause:

```
LAMBDA_RUNTIME Failed to post handler success response. Http response code: 413.
{"errorMessage":"Exceeded maximum allowed payload size (6291556 bytes)",
 "errorType":"RequestEntityTooLarge"}
```

`frontend/app/sitemap.ts:36` returns a single `MetadataRoute.Sitemap` array.
With `min_reviews=50`, the `/api/games` listing currently returns ~39,856 games
(probed via `has_more` and 1k-page paginate). After developer dedup + genres +
top tags, the rendered XML serializes to well over 6 MB.

The bound at `MAX_URLS = 49000` (sitemaps.org spec) was the right ceiling for
URL count but not for byte count: AWS Lambda's response payload limit is a
hard 6 MB on synchronous invokes (Function URL included), and we cross it.

The publisher-pages prompt
(`scripts/prompts/completed/sitemap-publisher-pages.md` — search for "sitemap-
index split") explicitly flagged this as out-of-scope-but-coming. Catalog
growth has now forced the issue.

## Approach

Switch `frontend/app/sitemap.ts` to use Next.js 16's
[`generateSitemaps()`](https://nextjs.org/docs/app/api-reference/file-conventions/metadata/sitemap#generating-multiple-sitemaps)
so `/sitemap.xml` becomes a `<sitemapindex>` pointing at child sitemaps at
`/sitemap/0.xml`, `/sitemap/1.xml`, … . Each child is its own Lambda invocation
with its own 6 MB budget, and they parallelize.

Fixed chunk plan, sized for headroom:

- **Chunk 0** — static hubs (`/`, `/reports`, `/search`, `/about`) + all
  genres + top tags. Bounded and small.
- **Chunks 1..N** — game pages plus inline-deduped developer pages, 5,000
  games per chunk. At ~250 bytes per `<url>` entry that's ~1.3 MB per child,
  well under 6 MB even with developer entries doubling some chunks.

Use `fields: "compact"` on the per-chunk `getGames` call to halve the upstream
payload (641 KB → 285 KB per 1k page; we currently fetch full rows we don't
need for the sitemap).

Chunk count is fixed in code rather than probed dynamically: probing requires
a synchronous `has_more` walk that re-introduces the same cost we're fleeing.
Empty chunks past the end of the catalog return `<urlset></urlset>`, which is
valid XML and which Google ignores. Pick the chunk count to give ~25–50%
headroom over the current catalog (today: 8 chunks needed for games → use 12).

Cross-chunk developer dedup is not preserved: the same developer URL may
appear in 2–3 chunks. Google deduplicates by URL across the full index, so
this is correct behavior, just not minimal.

Single forward path. No flag. Pre-launch product per `feedback_no_pre_launch_flags`.

## Files to modify

### 1. `frontend/app/sitemap.ts`

Replace the single default-export with two exports:

```ts
const URLS_PER_GAME_CHUNK = 5000;
const GAME_CHUNK_COUNT = 12; // 60k capacity; today we need ~8
const TOTAL_CHUNKS = GAME_CHUNK_COUNT + 1; // +1 for the static/genres/tags chunk at id=0

export async function generateSitemaps() {
  return Array.from({ length: TOTAL_CHUNKS }, (_, id) => ({ id }));
}

export default async function sitemap(
  { id }: { id: number },
): Promise<MetadataRoute.Sitemap> {
  if (id === 0) return staticAndHubRoutes();
  return gameChunkRoutes(id - 1); // chunk 0 of games => sitemap id 1
}
```

`staticAndHubRoutes()` does the existing static + `getGenres()` + `getTopTags(100)`
work. `gameChunkRoutes(chunkIdx)` calls
`getGames({ sort: "review_count", min_reviews: MIN_REVIEWS, limit: URLS_PER_GAME_CHUNK,
offset: chunkIdx * URLS_PER_GAME_CHUNK, fields: "compact" })` and emits the
game + per-chunk-deduped developer entries the same way the current loop does.

Keep `revalidate = 3600`.

Keep the existing `gameLastModified()` helper. Note: `fields: "compact"` only
returns `appid/name/slug/header_image/review_count/positive_pct/review_score_desc`
(verified via `/api/games?fields=compact`). The compact response drops every
field `gameLastModified()` reads, so `lastModified` will be `undefined` on
game entries. That's an acceptable regression — the current data is mostly
stale-by-hours-anyway and the trade is required for the byte budget. Document
this in a one-line comment.

`game.developer` is also dropped by compact, which breaks the current dev
loop. Either:
- (a) Keep developer pages and switch back to full fields (re-eats payload),
- (b) Drop developer URLs from the sitemap and emit them once via a dedicated
  developers chunk, or
- (c) Add `developer/developer_slug` to the compact projection in the API.

Default to **(c)**: add `developer` and `developer_slug` to the `compact`
field set in the API listing endpoint (one extra column per row, cheap). Keep
the per-chunk dev dedup. This preserves the existing SEO surface without
re-bloating the payload.

### 2. API: extend `compact` projection

Find the `/api/games` handler that branches on `fields=compact` and add
`developer` + `developer_slug` (and `publisher_slug` if the publisher-pages
prompt has shipped) to the compact column list. One DB roundtrip cost is
unchanged.

### 3. `frontend/tests/seo.spec.ts:130` and `frontend/tests/production/seo.prod.spec.ts:36`

Both currently assert `body.toContain('<urlset')`. After this change,
`/sitemap.xml` returns `<sitemapindex>`. Loosen the assertion:

```ts
expect(body).toMatch(/<urlset|<sitemapindex/)
```

Add one new assertion that the index lists at least one child sitemap:

```ts
expect(body).toContain('https://steampulse.io/sitemap/')
```

(Adjust host for the local-dev test.)

### 4. `frontend/app/robots.ts:16`

No change. `https://steampulse.io/sitemap.xml` is still the published entry
point; it now resolves to the sitemap index. Google follows the index and
fetches each child.

## Out of scope

- Dynamic chunk-count probing. Hardcoded headroom is simpler and removes a
  cold-start cost; revisit when catalog crosses 50k games.
- Lowering `MIN_REVIEWS`. Current 50 is the trimmed SEO surface; lowering it
  here would just paper over the byte limit and re-trigger 413 sooner.
- Per-chunk `lastmod` on the index entries. Next.js's sitemap index emitter
  doesn't surface a clean per-id `lastmod`; the per-URL `lastmod` inside each
  child sitemap is what Google actually uses for crawl prioritisation.
- Publisher pages — covered by `scripts/prompts/completed/sitemap-publisher-pages.md`.
  If that prompt has merged, just include `publisher_slug` in the compact
  projection in step 2 and add a per-chunk publisher dedup mirroring the
  developer block.

## Verification

1. **Local rebuild** — `cd frontend && npm run build && npm run start`, then:
   - `curl http://localhost:3000/sitemap.xml | head -20` shows
     `<sitemapindex …>` with `<sitemap><loc>http://localhost:3000/sitemap/0.xml</loc></sitemap>` rows.
   - `curl http://localhost:3000/sitemap/0.xml | grep -c '<url>'` returns
     a count consistent with static + genres + top tags (~120ish).
   - `curl http://localhost:3000/sitemap/1.xml | grep -c '<url>'` returns
     ~5000–6000 (games + deduped devs).
   - `curl -s http://localhost:3000/sitemap/1.xml | wc -c` is comfortably
     below 6,291,456.
2. **Empty chunk handling** — `curl http://localhost:3000/sitemap/11.xml`
   (past current catalog end) returns a valid empty `<urlset></urlset>`, not
   an error.
3. **Production smoke** — post-deploy, `curl -s -o /dev/null -w '%{http_code}\n'
   https://steampulse.io/sitemap.xml` returns `200`. Same for at least one
   `https://steampulse.io/sitemap/N.xml`.
4. **CloudWatch** — tail `FrontendFnLogs`; no `RequestEntityTooLarge` after
   the next sitemap revalidation cycle (1 hour).
5. **Google Search Console** — submit `https://steampulse.io/sitemap.xml`;
   GSC parses it as an index and lists each child sitemap with its own URL
   count. Watch for "Couldn't fetch" errors over the next 24h.
