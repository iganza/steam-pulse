# Revalidate Page HTML Alongside Tag (Close the Cache-Invalidation Loop)

## Context

After three rounds of cache-until-changed work
(`feature/game-report-cache-invalidation` → `feature/opennext-revalidation-pipeline` → `feature/pin-next-build-id`), production tests showed the loop still doesn't bust the rendered page HTML. Diagnosis: we only call `revalidateTag('game-${appid}', 'max')`. That marks the underlying `fetch()` cache entries stale, but **does not invalidate the page's HTML cache** for dynamic routes (`/games/[appid]/[slug]`) when `generateStaticParams` returns `[]`.

OpenNext pre-populates DynamoDB tag→path mappings only for routes whose paths are known at build time (the `dynamodb-cache.json` artifact). Dynamic routes are absent — confirmed locally:

```
$ jq -r '.[] | select(.path.S | contains("games/")) | .path.S' \
    frontend/.open-next/dynamodb-provider/dynamodb-cache.json
(empty — zero games/* entries)
```

So when `revalidateTag` runs, OpenNext finds nothing in the tag table linking the page path to the tag, and the page entry in S3 stays fresh.

The official Next.js 16 [`revalidatePath` docs](https://nextjs.org/docs/app/api-reference/functions/revalidatePath#building-revalidation-utilities) document the canonical pattern explicitly:

> **`revalidatePath` and `updateTag` are complementary primitives that are often used together** in utility functions to ensure comprehensive data consistency across your application.

We implemented half the pattern. This prompt adds the other half.

**Goal**: when a `report-ready` event fires, both the rendered page HTML *and* the underlying tagged fetches invalidate. After this lands, viewers see fresh content on the next visit; OpenNextRevalidationFn fires; the loop is closed.

**Non-goal**: changing the `'max'` semantics on `revalidateTag` (still want SWR for the shared-tag fetches). CloudFront edge invalidation (separate prompt: `game-report-cloudfront-invalidation.md`).

## Best-practice foundation

- **Specific path beats pattern form for our use case**. `revalidatePath('/games/[appid]/[slug]', 'page')` would over-invalidate (every report-ready busts every cached game page). `revalidatePath('/games/${appid}/${slug}')` busts exactly one. We have the slug in `ReportReadyEvent.game_name` and `games.slug` in the DB — trivial to thread through.
- **No `type` parameter needed for literal paths**. Per docs: "Use a literal path when you want to refresh a single page" — no `type` arg.
- **Order doesn't matter**. Both calls are sync state mutations on the cache layer; they compose.
- **Idempotent**. Re-firing the same revalidation is harmless — no double-invalidation cost.

## Design

### 1. Event payload — include `slug`

`src/library-layer/library_layer/events.py`:

```python
class ReportReadyEvent(BaseEvent):
    event_type: Literal["report-ready"] = "report-ready"
    appid: int
    game_name: str
    slug: str  # NEW — used by the frontend revalidator to call revalidatePath
    review_score_desc: str | None = None
```

`src/lambda-functions/lambda_functions/analysis/handler.py` (around line 152): include the game's slug in the publish call. The slug is already in the `games` row that the handler queried earlier (`game.slug`). Pull it from there:

```python
publish_event(
    _sns_client,
    _content_events_topic_arn,
    ReportReadyEvent(
        appid=req.appid,
        game_name=name,
        slug=game.slug,
        review_score_desc=game.review_score_desc,
    ),
)
```

### 2. Revalidate Lambda — pass slug through

`src/lambda-functions/lambda_functions/revalidate_frontend/handler.py`:

- `_extract_appid_and_slug(record)` returns `(appid, slug)` instead of just appid.
- `_post_revalidate(appid, slug)` POSTs `{"appid": appid, "slug": slug}`.
- All log lines / metrics keep the existing shape.

### 3. Route handler — call both `revalidatePath` and `revalidateTag`

`frontend/app/api/revalidate/route.ts`:

```ts
import { revalidatePath, revalidateTag } from "next/cache";
import type { NextRequest } from "next/server";

export async function POST(req: NextRequest) {
  const expectedToken = process.env.REVALIDATE_TOKEN;
  if (!expectedToken) { /* ... unchanged ... */ }
  if (req.headers.get("x-revalidate-token") !== expectedToken) { /* ... unchanged ... */ }

  let body: unknown;
  try { body = await req.json(); }
  catch { return Response.json({ ok: false, error: "bad_json" }, { status: 400 }); }

  const appid = (body as { appid?: unknown })?.appid;
  const slug = (body as { slug?: unknown })?.slug;
  if (typeof appid !== "number" || !Number.isInteger(appid) || appid <= 0) {
    return Response.json({ ok: false, error: "bad_appid" }, { status: 400 });
  }
  if (typeof slug !== "string" || slug.length === 0) {
    return Response.json({ ok: false, error: "bad_slug" }, { status: 400 });
  }

  // Bust the page HTML cache (OpenNext S3 entry) — the missing piece.
  revalidatePath(`/games/${appid}/${slug}`);
  // Bust the shared fetches under one tag — already wired pre-fix.
  revalidateTag(`game-${appid}`, "max");

  return Response.json({ ok: true, appid, slug, now: Date.now() });
}
```

### 4. Tests

- `tests/handlers/test_revalidate_frontend_handler.py` — extend the SNS-wrapped event factories to include `slug`; assert the POST body now contains both `appid` and `slug`. Add a "missing slug → batch failure" case.
- No new infra tests needed (no infra changes).

### 5. CDK / messaging — no changes

Event shape is additive; the SNS topic, SQS queue, and Lambda configuration all stay as-is. The Pydantic model handles deserialization of older messages with no slug? **No** — `slug` is required (no default). Once the new analysis handler ships, all new events have it. **In-flight events at deploy time** without `slug` will fail validation in `RevalidateFrontendFn` and land on the DLQ — acceptable, since the queue is empty under normal load.

If you want to be defensive about in-flight events, make `slug: str | None = None` on the model and have the route handler 400 on missing slug (already in the design). The Lambda would log + DLQ those records, which we'd manually drain. Keep `slug: str` (required) for the cleaner model — defer the resilience question.

## Critical files

**Edit:**
- `src/library-layer/library_layer/events.py` — add `slug: str` to `ReportReadyEvent`
- `src/lambda-functions/lambda_functions/analysis/handler.py` — include `slug=game.slug` in `ReportReadyEvent(...)`
- `src/lambda-functions/lambda_functions/revalidate_frontend/handler.py` — extract + forward slug
- `frontend/app/api/revalidate/route.ts` — call `revalidatePath` alongside `revalidateTag`; validate slug
- `tests/handlers/test_revalidate_frontend_handler.py` — update event factories + add slug-missing case

**Reference (no edits):**
- `frontend/.open-next/dynamodb-provider/dynamodb-cache.json` — confirms zero pre-populated entries for `/games/[appid]/[slug]` (the bug's root)
- `scripts/prompts/opennext-revalidation-pipeline.md` — prior PR that wired the OpenNext re-render queue (now actually exercised after this fix)

## Verification

**Local**:
```sh
poetry run pytest tests/handlers/test_revalidate_frontend_handler.py
poetry run pytest tests/infra/  # should still be green
cd frontend && node_modules/.bin/tsc --noEmit
node_modules/.bin/next build && node_modules/.bin/open-next build
```

**Production** (after deploy):
1. Hit `/games/3205380/omelet-you-cook-3205380` via the Function URL → MISS, then HIT.
2. Synthetic invoke `RevalidateFrontendFn` with an SNS-wrapped event including `slug: "omelet-you-cook-3205380"`.
3. Inspect DynamoDB cache table — `96bd8e8/game-3205380` tag entries should have `revalidatedAt = NOW`.
4. **Hit page again → expect `x-nextjs-cache: STALE`** (this is the new behavior — page entry is now bust). The hit also enqueues a re-render to `OpenNextRevalidationQueue`.
5. Tail `/steampulse/production/opennext-revalidation` → should see one invocation re-rendering the page.
6. Hit page a third time → `x-nextjs-cache: HIT` with the just-rendered fresh content.
7. Bonus end-to-end: trigger a real re-analysis via Step Functions for a known appid; confirm steps 4–6 happen automatically without manual intervention.

**Rollback**: revert the route handler to call only `revalidateTag`. The `slug` field on the event is harmless (extra field; consumers ignore it).

## Why this is the correct end state

- Follows the documented Next.js 16 pattern verbatim ("revalidatePath and revalidateTag are complementary primitives often used together").
- Precise — invalidates exactly one page per `report-ready`, not the whole catalog.
- Bisects the responsibility cleanly: `revalidatePath` busts the HTML; `revalidateTag` (with `'max'`) busts the underlying fetches with SWR semantics.
- Closes every gap we identified through testing: BUILD_ID alignment, OpenNext revalidation queue, page HTML invalidation. After this, the cache-until-changed promise is real.

## Out of scope

- CloudFront edge invalidation (separate prompt).
- Genre / tag / dev / pub pages (will follow the same `revalidatePath + revalidateTag` pattern when their data-cache work lands).
- DLQ-resilient handling of in-flight events without `slug` (defer; queue is normally empty).

## Sources

- [Next.js revalidatePath — Building revalidation utilities (v16)](https://nextjs.org/docs/app/api-reference/functions/revalidatePath#building-revalidation-utilities)
- [Next.js revalidateTag](https://nextjs.org/docs/app/api-reference/functions/revalidateTag)
- [OpenNext Tag Cache override](https://opennext.js.org/aws/config/overrides/tag_cache)
- [OpenNext caching internals](https://opennext.js.org/aws/inner_workings/caching)
