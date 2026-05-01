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
so the children at `/sitemap/0.xml`, `/sitemap/1.xml`, … are each their own
Lambda invocation with a fresh 6 MB budget. They parallelize.

**Gotcha — Next.js 16 does not auto-generate the `<sitemapindex>` at
`/sitemap.xml`.** When `generateSitemaps()` is exported, the framework
only registers `/sitemap/[__metadata_id__]` (the children); `/sitemap.xml`
is left unrouted and 404s. The current docs do not actually claim
auto-generation; the missing index is tracked in
[vercel/next.js#77304](https://github.com/vercel/next.js/issues/77304),
open since March 2025 and unresolved in 16.x. Fix: provide our own index
at a non-conflicting Route Handler path (`app/sitemap-index/route.ts`)
emitting the `<sitemapindex>` XML, then add a `next.config.ts` rewrite
mapping `/sitemap.xml -> /sitemap-index`. A directory at `app/sitemap.xml/`
won't work; its existence breaks the `[__metadata_id__]` route registration
in `sitemap.ts` and `next build` errors with `Cannot find module for
page: /sitemap/[__metadata_id__]` (verified locally).

**Gotcha — `id` is `Promise<string>` in Next.js v16.0.0+.** The pre-v16
docs example used `{ id }: { id: number }` and did arithmetic on `id`
directly. In v16+ the prop is a Promise that must be awaited, and the
resolved value is a string. Code that destructures and coerces with
`Number(id)` will silently produce `NaN` and route every chunk to
`gameChunkRoutes(NaN)`, rendering empty `<urlset></urlset>` bodies for
all children. Always `await props.id` first, then `Number()`.

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

// Next.js v16.0.0 changed `id` to `Promise<string>` (see Version History on
// https://nextjs.org/docs/app/api-reference/file-conventions/metadata/sitemap).
// Pre-v16 examples that destructure `{ id }: { id: number }` and do arithmetic
// directly will silently break: `Number(Promise) === NaN`, every chunk routes
// to `gameChunkRoutes(NaN)` and renders an empty <urlset> (110 bytes).
export default async function sitemap(
  props: { id: Promise<string> },
): Promise<MetadataRoute.Sitemap> {
  const sitemapId = Number(await props.id);
  if (sitemapId === 0) return staticAndHubRoutes();
  return gameChunkRoutes(sitemapId - 1);
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

### 2. API: extend `compact` projection, slow-path SELECT, and limit cap

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

**Also raise the `limit` cap on the listing endpoint from `le=1000` to
`le=5000`.** The sitemap chunk size is 5000 games per child, and the API
default cap rejected the request with HTTP 422; the empty `<urlset>`
chunks in production were caused by this in addition to the v16
`Promise<string>` bug. With the compact projection, 5000 rows is ~2 MB
(≈400 bytes per row), well within the 6 MB Lambda response budget.
Existing callers of the listing endpoint pass smaller limits and are
unaffected.

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
point; the `next.config.ts` rewrite maps it to `/sitemap-index`, which
emits the `<sitemapindex>` XML pointing at each child. Google follows the
index and fetches each child.

### 5. `frontend/app/sitemap-index/route.ts` (new) and `frontend/app/sitemap-config.ts` (new)

Add a Route Handler that emits the `<sitemapindex>` XML for `TOTAL_CHUNKS`
children. Extract `BASE_URL`, `GAME_CHUNK_COUNT`, and `TOTAL_CHUNKS` to a
small `sitemap-config.ts` module so both `sitemap.ts` and the index
handler share the same constants without coupling. The handler uses
`export const dynamic = "force-static"` since the index URL list only
changes between deploys (when `GAME_CHUNK_COUNT` is bumped).

### 6. `frontend/next.config.ts`

Add `{ source: "/sitemap.xml", destination: "/sitemap-index" }` to the
`rewrites()` return array. Place it after the dev `/api/:path*` rewrite
so it doesn't get shadowed.

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
   - `curl -i http://localhost:3000/sitemap.xml` returns 200 (not 404) and
     `<sitemapindex …>` with `<sitemap><loc>https://steampulse.io/sitemap/0.xml</loc></sitemap>`
     rows. The 404 mode is the canary for the Next.js auto-index gotcha; if
     this fails, the rewrite or the `app/sitemap-index/route.ts` handler is
     misconfigured.
   - `curl -s http://localhost:3000/sitemap/0.xml | grep -c '<url>'` returns
     a count consistent with static + genres + top tags (~120ish). **A
     count of 0 (or `wc -c` returning ~110 bytes for the whole file) is
     the canary for the v16 `id`-Promise gotcha** — every chunk is empty
     because `Number(Promise)` is `NaN`. Confirm the default export
     awaits `props.id` rather than destructuring it.
   - `curl -s http://localhost:3000/sitemap/1.xml | grep -c '<url>'` returns
     ~8000 (5000 games + ~3000 deduped developers). **A count of 0 with
     `/sitemap/0.xml` populated is the canary for the API `limit` cap
     gotcha** — `getGames({limit: 5000})` is rejected with HTTP 422 if
     the API still has the old `le=1000` validation. Verify by curling
     `/api/games?limit=5000&fields=compact` directly and checking it
     returns 200 + ~2 MB, not 422.
   - `curl -s http://localhost:3000/sitemap/1.xml | wc -c` is comfortably
     below 6,291,456 (typically ~1.1 MB).
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
