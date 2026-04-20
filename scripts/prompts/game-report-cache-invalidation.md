# Cache-Until-Changed for Game Report Pages

## Context

Game report pages at `/games/[appid]/[slug]` hit Postgres on essentially every load, even when the underlying report hasn't changed. The page *looks* cached (24 h ISR) but three separate problems leak through:

1. **Cache-window mismatch**: page ISR is 24 h (`revalidate = 86400`) but the inner `getGameReport` fetch is tagged `revalidate: 3600`. Every time ISR revalidates, the fetch is already stale, so it re-hits the API → DB.
2. **Uncached client-side fetches**: `GameReportClient.tsx:148,158` calls `getReviewStats` and `getBenchmarks` from `useEffect` on every mount. `getBenchmarks` has no `revalidate` at all → `no-store` → DB hit every view.
3. **No invalidation wiring**: the analyzer already publishes a `ReportReadyEvent` to SNS after every report upsert, and there's a `cache_invalidation_queue` already subscribed to it — but nothing calls `revalidateTag` in the Next.js app. So even if TTLs were aligned, a newly re-analyzed report wouldn't bust the cache.

**Goal**: reports *unchanged* → served from Next.js data cache / CloudFront edge without touching the API or DB. Reports *changed* (re-analysis ran) → the relevant cache entries invalidate and the next visit serves fresh data. Background regeneration, zero user-visible blocking.

**Scope**: game report pages only. Genre/tag/developer/publisher pages use the same pattern and can follow as a copy-paste migration later. Homepage + catalog (short-TTL feeds) are intentionally not in scope.

## Best-practice foundation (from research)

- **Next.js 15/16 flipped the default**: `fetch()` is no longer cached by default — must opt in via `next: { revalidate, tags }` or `"use cache"`. Docs: [Next.js caching](https://nextjs.org/docs/app/getting-started/caching-and-revalidating), [ISR guide](https://nextjs.org/docs/app/guides/incremental-static-regeneration).
- **Canonical pattern for "cache-until-changed"**: long `revalidate` (hours/days) + `tags` on every fetch + `revalidateTag(tag, 'max')` from a Route Handler when the writer updates the data. `'max'` gives stale-while-revalidate semantics — stale served immediately while fresh fetches in the background. Single-arg form `revalidateTag(tag)` is deprecated in v16.
- **CloudFront already correctly configured**: `/api/*` uses `CACHING_DISABLED` (API stays authoritative, our Next.js data cache handles it), and HTML `default_ttl=0` lets OpenNext's `Cache-Control: s-maxage=<revalidate>, stale-while-revalidate` drive CloudFront behavior. No CDK changes needed.
- **The plumbing exists already**: `ReportReadyEvent` is published to `content_events_topic` after every report upsert at `src/lambda-functions/lambda_functions/analysis/handler.py:152`. `cache_invalidation_queue` already has the `report-ready` filter subscription at `infra/stacks/messaging_stack.py:228-238`. But that queue is single-consumer (matview refresh) — we need a **new** queue on the same topic for frontend revalidation.

## Design

### 1. Frontend — long TTL + shared tag + server-side fetching

**`frontend/app/games/[appid]/[slug]/page.tsx`**
- Change `export const revalidate = 86400` → `export const revalidate = 31536000` (1 year). We rely fully on tag invalidation; time-based expiry is just a safety net.
- In the server component, fetch `getGameReport`, `getReviewStats`, `getBenchmarks` together via `Promise.all` and pass all three as props to `<GameReportClient>`.
- Keep `generateMetadata` as-is — it already calls `getGameReport` which dedupes via Next.js's per-request memoization.

**`frontend/app/games/[appid]/[slug]/GameReportClient.tsx`**
- Delete the `useEffect`/`useState` that drive `reviewStats` + `benchmarks` (lines ~130-168). Accept them as props instead.
- Also remove `statsLoading` — server-rendered data is already available on first paint.
- Stay a client component (interactive chart UI), but fully hydrates from server-rendered data.

**`frontend/lib/api.ts`**
- `getGameReport` (line 100): change `next: { revalidate: 3600, tags: [`report-${appid}`] }` → `next: { revalidate: 31536000, tags: [`game-${appid}`] }`.
- `getReviewStats` (line 210): change `next: { revalidate: 3600 }` → `next: { revalidate: 31536000, tags: [`game-${appid}`] }`.
- `getBenchmarks` (line 216): add `next: { revalidate: 31536000, tags: [`game-${appid}`] }`.
- Single shared tag `game-${appid}` (not three separate tags) so one `revalidateTag` call invalidates all three fetches in one shot. Simpler webhook payload, fewer edge cases.

### 2. Revalidation endpoint

**New file**: `frontend/app/api/revalidate/route.ts`
```ts
import { revalidateTag } from 'next/cache';
import type { NextRequest } from 'next/server';

export async function POST(req: NextRequest) {
  if (req.headers.get('x-revalidate-token') !== process.env.REVALIDATE_TOKEN) {
    return Response.json({ ok: false, error: 'unauthorized' }, { status: 401 });
  }
  const { appid } = await req.json();
  if (!appid || typeof appid !== 'number') {
    return Response.json({ ok: false, error: 'bad_appid' }, { status: 400 });
  }
  revalidateTag(`game-${appid}`, 'max');
  return Response.json({ ok: true, appid, now: Date.now() });
}
```

**Env**: `REVALIDATE_TOKEN` — shared secret. Source-of-truth is SSM param `/steampulse/{env}/frontend/revalidate-token`; frontend reads at build/runtime via existing env-injection pattern; Lambda reads at cold start.

### 3. Invalidation Lambda

**New Lambda**: `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py`
- Consumes SQS messages from a new `frontend_revalidation_queue` (batch size 10).
- For each record: parse the SNS-wrapped `ReportReadyEvent`, extract `appid`, POST to `https://<domain>/api/revalidate` with header `x-revalidate-token: <token>` and body `{"appid": <int>}`.
- Idempotent by construction — calling `revalidateTag` twice is cheap. SQS visibility timeout + DLQ handle retries.
- Read domain from env var `FRONTEND_BASE_URL`, token from env/SSM.

**New SQS queue** in `infra/stacks/messaging_stack.py`:
- `self.frontend_revalidation_queue` with DLQ, subscribed to `content_events_topic` with filter `{"event_type": ["report-ready"]}` — mirror the existing `cache_invalidation_queue` subscription at line 228-238.
- SSM export the queue ARN for the compute stack to read.

**Wire consumer** in `infra/stacks/compute_stack.py`:
- New `aws_lambda_python_alpha.PythonFunction` (follow existing Lambda patterns), `SqsEventSource(frontend_revalidation_queue, batch_size=10)`.
- Env: `FRONTEND_BASE_URL`, `REVALIDATE_TOKEN_PARAM` (SSM param name). Grant SSM read.

### 4. CDK / CloudFront — no changes needed

- `/api/*` = `CACHING_DISABLED` (delivery_stack.py:113-118): correct. API stays authoritative; Next.js data cache does the caching.
- HTML cache policy `default_ttl=0, max_ttl=365d` (delivery_stack.py:74-91): correct. OpenNext emits `Cache-Control: s-maxage=31536000, stale-while-revalidate=...` which CloudFront respects.
- `invalidate-cdn.sh`: leave as manual escape hatch; not part of the automated flow.

## Critical files

**Edit:**
- `frontend/app/games/[appid]/[slug]/page.tsx` — bump `revalidate` to 1y, fetch all three per-game APIs in parallel, pass as props
- `frontend/app/games/[appid]/[slug]/GameReportClient.tsx` — drop useEffect/useState for stats+benchmarks, accept as props
- `frontend/lib/api.ts` — unify `tags: ['game-${appid}']` + `revalidate: 31536000` on `getGameReport`, `getReviewStats`, `getBenchmarks`
- `infra/stacks/messaging_stack.py` — add `frontend_revalidation_queue` + SNS subscription
- `infra/stacks/compute_stack.py` — add Lambda + SQS event source

**Create:**
- `frontend/app/api/revalidate/route.ts` — POST handler, verifies token, calls `revalidateTag`
- `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py` — SQS consumer → HTTP POST to /api/revalidate
- `src/lambda-functions/lambda_functions/revalidate_frontend/__init__.py` + `pyproject.toml` following existing lambda package structure

**Reference (no edits):**
- `src/lambda-functions/lambda_functions/analysis/handler.py:152-160` — event publish is already correct; nothing to change
- `src/library-layer/library_layer/events.py:106-110` — `ReportReadyEvent` shape
- `scripts/invalidate-cdn.sh` — manual CDN flush, keep as escape hatch

## Verification

**Local**:
1. `cd frontend && pnpm build && pnpm start` with `NEXT_PRIVATE_DEBUG_CACHE=1` in `.env.local`.
2. Visit `/games/<appid>/<slug>` twice. Second visit's response should include `x-nextjs-cache: HIT` (or `STALE` during background regen); server logs should show no fetch on the second visit.
3. `curl -X POST http://localhost:3000/api/revalidate -H 'x-revalidate-token: <token>' -d '{"appid": <n>}'` → `{ok: true}`.
4. Next visit's response should show `x-nextjs-cache: REVALIDATED`, then HIT thereafter.
5. Confirm `getBenchmarks` no longer runs on client: DevTools → Network → filter `benchmarks` → no request on navigation.

**Staging**:
1. Deploy both CDK + frontend. Confirm SQS queue + Lambda exist (`aws sqs list-queues`, `aws lambda list-functions`).
2. Pick a known appid, hit the page twice, confirm second visit is fast (<100 ms TTFB, no API log entry).
3. Trigger a re-analysis for that appid via the Step Functions console or CLI.
4. Watch CloudWatch logs for the new `revalidate_frontend` Lambda — should fire within ~seconds of the `ReportReadyEvent`.
5. Hit the page again; confirm fresh data renders and `x-nextjs-cache: REVALIDATED` on the first post-invalidation visit.

**Rollback**: revert the `revalidate` bumps and `tags` changes in `frontend/lib/api.ts` + `page.tsx` — page falls back to the previous 24 h/1 h TTL behavior. Lambda can stay deployed idle. `invalidate-cdn.sh` remains available as a manual cache flush.

## Explicitly out of scope

- Genre / tag / developer / publisher detail pages (same pattern applies; do as a follow-up)
- Homepage, catalog, new-releases, discovery feeds (short-TTL time-based caching stays; no tag/invalidation)
- CloudFront cache policy changes (not needed)
- ETag/If-None-Match on the API (not needed — Next.js data cache + tag invalidation covers the need without per-request validation)
- Retiring `invalidate-cdn.sh`

## Sources

- [Next.js revalidateTag docs (v16.2.4)](https://nextjs.org/docs/app/api-reference/functions/revalidateTag)
- [Next.js ISR guide](https://nextjs.org/docs/app/guides/incremental-static-regeneration)
- [Next.js caching & revalidating](https://nextjs.org/docs/app/getting-started/caching-and-revalidating)
- [Next.js 16 caching explained — DEV Community](https://dev.to/realacjoshua/nextjs-16-caching-explained-revalidation-tags-draft-mode-real-production-patterns-26dl)
- [OpenNext AWS caching](https://opennext.js.org/aws/inner_workings/caching)
- [`revalidate`'s `Cache-Control` values — vercel/next.js #35104](https://github.com/vercel/next.js/discussions/35104)
