# Search Autocomplete: Fix Perceived Gap + Speed Up

## Context

On prod, typing in the header search shows a spinner, the spinner disappears, and *then* (after a visible gap) results appear. The autocomplete also feels slow overall.

Two root causes:

1. **Spurious watchdog in `frontend/components/layout/SearchAutocomplete.tsx:104-109`.** A 3-second `setTimeout` clears `suggestions` and flips `loading=false` even while the real request is still in flight. On a Lambda cold start (easily 3-8 s), the user sees: spinner (3 s) → empty dropdown → results pop in. `apiFetch` already sets `AbortSignal.timeout(8000)` browser-side (`frontend/lib/api.ts:37-45`), so the watchdog is redundant *and* harmful — it resolves into stale component state before the real abort fires.

2. **No client-side reuse, heavy payload, and no reachable edge cache.** Backspace/retype refetches the same prefix. The response includes fields the dropdown never renders (`estimated_owners`, `estimated_revenue_usd`, `deck_compatibility`, `crawled_at`, the `is_early_access` EXISTS subquery). CloudFront is `CACHING_DISABLED` for `/api/*` by design (`infra/stacks/delivery_stack.py:116`), so `s-maxage` at the API wouldn't reach an edge cache — we fix this at the client and payload layers instead. Any CloudFront behavior change belongs in the broader caching work tracked in `scripts/prompts/game-report-cache-invalidation.md`.

**Goal**: eliminate the "spinner off → empty → results" gap, and cut perceived latency for a given user's repeat prefixes to ~zero. Cross-user edge caching is explicitly out of scope here.

## Design

### 1. `frontend/components/layout/SearchAutocomplete.tsx`

Rewrite the fetch effect (lines 91-128):

- Delete the `setTimeout(..., 3000)` watchdog and its `clearTimeout` calls.
- Do **not** clear `suggestions` at the start of a new fetch. Keep the previous list visible behind the spinner so the dropdown never flashes empty on re-query. Only clear when `debouncedQuery.length < 2` (already handled at line 93).
- Add an in-memory LRU cache at the component top:
  ```ts
  const cacheRef = useRef<Map<string, Game[]>>(new Map());
  ```
  Key on `query.toLowerCase().trim()`. Before fetching, if the cache has the key, synchronously `setSuggestions` / `setOpen(res.games.length > 0)` / `setLoading(false)` and return without a network call. On successful response, `set` the entry; if `cacheRef.current.size > 20`, delete the oldest entry (Map iteration order = insertion order).
- Pass `signal` into `getGames(...)` — today the `AbortController` is created but never handed to `apiFetch`, so cancellation is a no-op.
- Update the call (line 111) to request the compact shape:
  ```ts
  getGames({ q: debouncedQuery, limit: 6, sort: "review_count", fields: "compact" }, signal)
  ```

### 2. `frontend/lib/api.ts`

- `getGames` (lines 111-152): add `fields?: "compact"` to the params type, propagate via `if (params?.fields) qs.set("fields", params.fields);`.
- Remove the inert `next: { revalidate: 3600 }` (line 150) — it has no effect on client-component fetches and is misleading.

### 3. `src/lambda-functions/lambda_functions/api/handler.py`

**`list_games` handler (lines 119-183):**
- Add a `fields: str | None = None` query parameter.
- When `fields == "compact"`, project each returned game dict down to `{appid, name, slug, header_image, review_count, positive_pct, review_score_desc}` before serializing. Do this in the handler, not the repo — one SQL path stays. Rationale: profile the edge-case SQL narrowing (the `EXISTS is_early_access` subquery at `src/library-layer/library_layer/repositories/game_repo.py:514`) only if it matters after the payload shrink; defer.
- Return `JSONResponse(content={"total": total, "games": games}, headers={"Cache-Control": "private, max-age=300"})`. This is a **browser** cache hint — `private` blocks any shared cache (CloudFront is already `CACHING_DISABLED` on `/api/*` anyway), `max-age=300` lets the same tab reuse a response within 5 min on back/forward / Next.js client routing. No edge-caching behavior.

## Sequencing

1. Backend (`handler.py`) first — adding `fields=compact` + `Cache-Control: private` is backward-compatible; existing callers that omit `fields` see identical responses.
2. Frontend (`api.ts` + `SearchAutocomplete.tsx`) together — watchdog removal, keep-stale, LRU cache, `fields=compact`, and threading `signal` are one coherent edit.

## Critical files

**Edit:**
- `/Users/iganza/dev/git/saas/steam-pulse/frontend/components/layout/SearchAutocomplete.tsx` — lines 80-128, 111
- `/Users/iganza/dev/git/saas/steam-pulse/frontend/lib/api.ts` — lines 111-152
- `/Users/iganza/dev/git/saas/steam-pulse/src/lambda-functions/lambda_functions/api/handler.py` — lines 119-183

**Reference (no changes):**
- `/Users/iganza/dev/git/saas/steam-pulse/src/library-layer/library_layer/repositories/game_repo.py:376-521` — `list_games` repo method; `ILIKE '%q%'` already uses the trigram GIN index from migration `0051_games_name_trgm_index.sql`.
- `/Users/iganza/dev/git/saas/steam-pulse/infra/stacks/delivery_stack.py:113-119` — `/api/*` = `CACHING_DISABLED`; confirms why `s-maxage` at the API is not a lever here.

## Verification

**Local — watchdog + stale-keep:**
1. `cd frontend && npm run dev`; DevTools → Network → throttle to Slow 3G.
2. Type `half`, wait for results, then type ` life`. Expect: previous 6 results stay visible with spinner overlaid in the icon; no empty flash; results replace in place.
3. Regression baseline on `main`: same steps show the dropdown collapse to empty at ~3 s, then results appear 1-5 s later.

**Local — LRU cache:**
1. Type `witcher`, wait for results, backspace to `witch`, retype `er`. Second render of `witcher` should be synchronous: no spinner, no request in DevTools Network.
2. Confirm cache bound: type 25 distinct 2+-char prefixes in a row; the 26th type of the 1st prefix should refetch (evicted).

**Local — `signal` threads through:**
1. Type `roguelike` character-by-character quickly. In DevTools Network, earlier requests should appear as `(canceled)` rather than completing.

**Local — browser cache header:**
1. `curl -sI "http://localhost:8000/api/games?q=elden&limit=6&sort=review_count&fields=compact"` (or whatever the local API URL is) should show `cache-control: private, max-age=300`.
2. In DevTools Network, re-issuing the same `/api/games?q=elden...` request via forward/back navigation within 5 min should show `(disk cache)` or `(memory cache)`.

## Out of scope

- Any CloudFront behavior change for `/api/games` or `/api/*` — defer to the broader caching decision tracked in `scripts/prompts/game-report-cache-invalidation.md`. That prompt owns `/api/*` policy.
- A dedicated `/api/search/suggest` endpoint — folded into `/api/games?fields=compact`.
- Switching the `ILIKE '%q%'` ranking to pg_trgm `similarity()` or to a tsvector/FTS search. The trigram GIN index already accelerates the current query; ranking changes are a separate UX call.
- Reducing the 300 ms debounce — the LRU cache already makes retype instant.
- `sessionStorage` / `localStorage` persistence of the LRU.
- Keyboard nav, a11y, analytics — unchanged.
- Repo-side SQL projection narrowing — the `EXISTS` subquery is the only real cost; defer until profiling after payload shrink shows it matters.
