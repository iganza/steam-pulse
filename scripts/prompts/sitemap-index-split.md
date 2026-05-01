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

Replace the multi-source `gameLastModified()` helper with a single-field
`parseTimestamp()` reading `game.last_analyzed`. That column is already
denormalized onto `games` (since migration 0017), already in the listing
endpoint's slow-path SELECT, and reflects when the LLM-rendered report on
the page last changed — the most user-visible content shift. The other
freshness columns the original helper read (`review_crawled_at`,
`tags_crawled_at`, `reviews_completed_at`, `meta_crawled_at`) live on
`app_catalog`, not `games`, so they aren't reachable from the listing
endpoint without a JOIN — `last_analyzed` is the right single source.

`game.developer` is also dropped by compact, which breaks the current dev
loop. Add `developer`, `developer_slug`, `publisher_slug`, and
`last_analyzed` to the compact field set in the API listing endpoint, and
add `g.developer_slug, g.publisher_slug` to the slow-path SELECT in
`GameRepository.list_games` (the matview fast-path is not hit by any
current `fields=compact` caller, so we don't touch the matview shape — see
"Out of scope"). The sitemap's developer-URL emit then prefers the
canonical `game.developer_slug`, falling back to `slugify(game.developer)`
from `frontend/lib/format.ts` if the slug is null. Keep the per-chunk dev
dedup. This preserves the existing SEO surface without re-bloating the
payload.

### 2. API: extend `compact` projection and slow-path SELECT

Find the `/api/games` handler that branches on `fields=compact` and add
`developer`, `developer_slug`, `publisher_slug`, and `last_analyzed` to the
compact column list. Then in `GameRepository.list_games` (slow path),
extend the SELECT to include `g.developer_slug, g.publisher_slug` — the
existing slow-path SELECT already returns `g.developer` and
`g.last_analyzed` but not the canonical slugs. One DB roundtrip cost is
unchanged.

The matview path (`_list_from_matview`) does not select these columns and
is not modified — current `fields=compact` callers (the sitemap, autocomplete)
all hit the slow path because the sitemap doesn't filter by genre/tag and
autocomplete sets `q` (which forces slow path). If a future caller passes
`fields=compact&genre=…` they would receive null `developer_slug`/`publisher_slug`;
fix at that point by rebuilding the matviews with those columns.

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
