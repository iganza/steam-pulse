# game-page-canonical-slug-redirect

Make `/games/{appid}/{slug}` 308-redirect to the canonical slug when the URL slug doesn't match what the API considers the slug-of-record. Today the page renders any slug that arrives, and the canonical tag echoes whatever was in the URL, so two URLs for the same game can index simultaneously and dilute link equity.

## Why

Production verification (2026-04-30) on `d1mamturmn55fm.cloudfront.net`:

```
GET /api/games/3265700/report → "slug":"vampire-crawlers-the-turbo-wildcard-from-vampire-survivors-3265700"
GET /games/3265700/vampire-crawlers → 200 OK, page renders
```

The API knows the canonical slug. The page accepts the wrong one, renders happily, and the canonical tag at `frontend/app/games/[appid]/[slug]/page.tsx:21,192` is built from the URL slug rather than the API slug, so it points at the *wrong* URL. Same for the JSON-LD Article schema's `mainEntityOfPage` field at line 278.

Search engines mostly honor canonical tags, but a server-side 308 redirect is stronger and more immediate than letting Google sort out conflicting URLs over weeks of crawls. It also kills the canonical-tag bug as a side effect, since the only slug that ever reaches the renderer is the canonical one. The sitemap (`frontend/app/sitemap.ts:61`) already emits canonical URLs (`game.slug`), so this just enforces what the sitemap already promises.

Risk avoided: anyone sharing a stale-titled link (Steam title rename, partial slug, manual typo) currently produces a duplicate-content surface that competes with the canonical URL. Once the redirect is in place, every variant collapses to the one URL.

## Goal

After this prompt:
- A request to `/games/{appid}/{wrong-slug}` returns `308 Permanent Redirect` to `/games/{appid}/{canonical-slug}` whenever `wrong-slug !== canonical-slug` and the API knows a canonical slug for that appid.
- A request to the canonical URL renders the page, no redirect.
- Unknown appids continue to 404 via the existing `notFound()` paths.
- The `<link rel="canonical">` tag in both `generateMetadata` and the page render uses the API's canonical slug, not the URL slug. (Belt-and-suspenders: with the redirect in place this can only ever match the URL, but it's the right value to compute regardless.)
- The JSON-LD Article schema's `mainEntityOfPage` and the `canonicalUrl` constant both reference the canonical URL.
- No change to API responses, sitemap shape, or any other route.

## Scope

**In:**
- `frontend/app/games/[appid]/[slug]/page.tsx`: add a slug check + `permanentRedirect()` after the API fetch in the page default export. Update `canonicalUrl` calculations in both `generateMetadata` and the page default export to use the API slug (with safe fallback to the URL slug when the API didn't return one, e.g. unknown appid edge cases).
- A short comment explaining that the redirect is intentional and what it protects against.

**Out:**
- API changes. The API already returns `slug` in the response shape (`frontend/lib/api.ts:75`); no contract change needed.
- Sitemap. Already emits canonical URLs.
- Other dynamic routes (`/genre/[slug]`, `/tag/[slug]`, `/developer/[slug]`, `/publisher/[slug]`). Their slugs are themselves the canonical identifier; there's no separate canonical-of-record like games have (appid + slug). Out of scope; can be a follow-up if a similar mismatch surfaces.
- Migrating any in-the-wild bad links. The redirect handles them automatically as soon as it ships.
- Changing any redirect to a 301 vs 308. Next.js `permanentRedirect()` issues 308; Google treats 301 and 308 equivalently for permanent moves.
- Adding a redirect from `/games/{appid}` (no slug) to the canonical URL. The route doesn't exist; would need a separate `/games/[appid]/page.tsx` if added. Out of scope.
- Tests. The page is a Server Component; per project convention there are no unit tests for page-level redirect logic, and a Playwright check is a separate thread.
- No commits, pushes, or deploys. Operator handles those.

## Decisions

1. **Why 308 (`permanentRedirect`) and not 307 (`redirect`)?** The canonical slug is durable for a given appid (changes only on Steam title rename, which is rare). 308 tells search engines and clients "this is the new home, update your records." 307 would invite re-crawling the wrong URL forever.

2. **What if the API doesn't return a slug?** Fall back to the URL slug for the canonical tag calculation; do NOT redirect. Keeps the existing behavior for edge cases (unknown appid that still returns minimal `game_meta`, or transient API hiccup mid-render). The redirect should only fire when the API confidently returns a different canonical slug.

3. **Why not also redirect when the slug case differs?** The slugify step (`frontend/lib/format.ts:40`) already lowercases, so a mixed-case URL would normalize to the same string for comparison. If we ever introduced case-sensitive divergence, the equality check would still catch it. Not a real concern today.

4. **`generateMetadata` redirect?** Next.js documents `redirect()` as callable from `generateMetadata`, but the page default export runs in parallel and will issue the same redirect anyway. Doing it in one place (the default export) is simpler and avoids a duplicate fetch path; the metadata function just needs to compute the canonical URL correctly using the API slug it already fetches.

## Changes

### 1. `frontend/app/games/[appid]/[slug]/page.tsx`

Add the import:

```typescript
import { notFound, permanentRedirect } from "next/navigation";
```

In the default export `GameReportPage`, after the `Promise.all` fetch and before any rendering, add the redirect check (right after the existing `if (reportData.game) { ... }` block where `g` is destructured):

```typescript
// Slug is canonicalized to whatever the API returns. Wrong/stale slugs
// 308 to the canonical URL so search engines see one URL per game.
const canonicalSlug = reportData.game?.slug;
if (canonicalSlug && canonicalSlug !== slug) {
  permanentRedirect(`/games/${appid}/${canonicalSlug}`);
}
```

Then update both `canonicalUrl` constants to prefer the API slug, with the URL slug as the fallback for the unknown-appid edge case:

```typescript
// generateMetadata (around line 21):
const reportData = await getGameReport(numericAppid);
const effectiveSlug = reportData.game?.slug ?? slug;
const canonicalUrl = `https://steampulse.io/games/${appid}/${effectiveSlug}`;
// ...rest unchanged

// Default export (around line 192):
const effectiveSlug = reportData?.game?.slug ?? slug;
const canonicalUrl = `https://steampulse.io/games/${appid}/${effectiveSlug}`;
```

Note: in `generateMetadata`, the existing code already calls `getGameReport` and stores the result as `reportData`; reuse it. In the default export, after the redirect check above, `reportData.game.slug` always equals the URL slug (because we'd have redirected otherwise), so `effectiveSlug` is just defensive.

### 2. (Optional consistency) Update Article JSON-LD's `mainEntityOfPage`

The Article schema at line 278 already uses `canonicalUrl`, so once the constant is fixed it's automatically right. No further change needed.

## Files Modified

| File | Change |
|------|--------|
| `frontend/app/games/[appid]/[slug]/page.tsx` | Import `permanentRedirect`; redirect on slug mismatch in default export; use API slug in `canonicalUrl` for both `generateMetadata` and the default export |

## Verification

After deploy (operator runs the deploy):

1. **Wrong slug 308s to canonical:**
   ```bash
   curl -sI 'https://d1mamturmn55fm.cloudfront.net/games/3265700/wrong-slug' \
     | grep -iE 'http|location'
   ```
   Expect `HTTP/2 308` and `location: /games/3265700/vampire-crawlers-the-turbo-wildcard-from-vampire-survivors-3265700`.

2. **Canonical slug renders 200, no redirect:**
   ```bash
   curl -sI 'https://d1mamturmn55fm.cloudfront.net/games/3265700/vampire-crawlers-the-turbo-wildcard-from-vampire-survivors-3265700' \
     | grep -iE 'http|x-cache'
   ```
   Expect `HTTP/2 200`.

3. **Canonical tag points at the canonical URL** (use a wrong slug to prove the redirect-then-render produces the right tag):
   ```bash
   curl -sL 'https://d1mamturmn55fm.cloudfront.net/games/3265700/wrong-slug' \
     | grep -oE '<link rel="canonical"[^>]*>' | head -1
   ```
   Expect the `href` to be the canonical URL, not `/games/3265700/wrong-slug`.

4. **Unknown appid still 404s:**
   ```bash
   curl -sI 'https://d1mamturmn55fm.cloudfront.net/games/999999999/anything' \
     | grep -iE 'http'
   ```
   Expect `HTTP/2 404`.

5. **Sitemap URLs all render 200 without redirect** (sample 5):
   ```bash
   curl -s https://d1mamturmn55fm.cloudfront.net/sitemap.xml \
     | grep -oE '<loc>https://[^<]+/games/[0-9]+/[^<]+</loc>' \
     | head -5 \
     | sed -E 's|.*<loc>https?://[^/]+(.*)</loc>|\1|' \
     | while read path; do
         echo -n "$path → "
         curl -sI "https://d1mamturmn55fm.cloudfront.net$path" | head -1
       done
   ```
   Every line should show `HTTP/2 200`. If any 308, the sitemap is emitting non-canonical URLs and there's a slug-generation bug separate from this fix.

6. **Search Console** (post-deploy, lagging signal): the "Duplicate without user-selected canonical" report should trend down over the next few crawls.

## What NOT To Do

- Do NOT use `redirect()` (307); use `permanentRedirect()` (308) so search engines update their index instead of re-crawling the wrong URL.
- Do NOT redirect in `generateMetadata`. The page default export's redirect runs anyway; doing it twice just risks a subtle race.
- Do NOT redirect when the API didn't return a slug (e.g. minimal-metadata fallback for unknown appid). Falls back to URL slug + canonical tag, same as today's behavior.
- Do NOT change the API contract. `slug` is already in the response.
- Do NOT touch `/genre`, `/tag`, `/developer`, `/publisher` routes in this prompt; those slugs are the canonical identifier themselves and don't have an appid-vs-slug split.
- Do NOT add a feature flag or env-var gate; pre-launch project, just ship the fix.
- Do NOT shorten or alter the page-level `revalidate = 31536000`. Redirects bypass ISR (Next.js evaluates the redirect at request time before serving the cached page), so the 1y page cache stays correct.
- Do NOT add a separate redirect for `/games/{appid}` (no slug); that route doesn't exist and creating it is a different prompt.

## Existing Code Reference

- `frontend/app/games/[appid]/[slug]/page.tsx:18` is where URL params are unpacked
- `frontend/app/games/[appid]/[slug]/page.tsx:21,192` is the `canonicalUrl` constants that need to use the API slug
- `frontend/app/games/[appid]/[slug]/page.tsx:24,130` is where `getGameReport` is called and `reportData.game.slug` becomes available
- `frontend/app/games/[appid]/[slug]/page.tsx:86,182` is the existing `notFound()` paths for unknown appids (untouched)
- `frontend/app/games/[appid]/[slug]/page.tsx:278` is the Article JSON-LD `mainEntityOfPage` (already references `canonicalUrl`, fixed transitively)
- `frontend/lib/api.ts:75` is the response-shape `slug?: string` field returned by `getGameReport`
- `frontend/app/sitemap.ts:61` is where the sitemap emits canonical URLs (`game.slug`); enforces this fix's contract
- `src/lambda-functions/lambda_functions/api/handler.py:289` is where the API serves `game.slug` in the report response
- `src/library-layer/library_layer/services/crawl_service.py:365` is where `slugify(name, appid)` produces the canonical slug at crawl time
- Next.js `permanentRedirect` docs: https://nextjs.org/docs/app/api-reference/functions/permanentRedirect (issues 308)
