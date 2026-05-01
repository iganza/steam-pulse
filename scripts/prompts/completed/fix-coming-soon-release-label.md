# Fix: "Released" tile shows future dates for coming-soon games

## Problem

The game detail page shows "**RELEASED · Oct 31, 2028**" (or similar far-future date) for
games that haven't actually shipped yet.

Reproducer: https://d1mamturmn55fm.cloudfront.net/games/3851160/principal-panic-3851160

Local DB confirms the value:

```sql
SELECT appid, slug, release_date, release_date_raw, coming_soon FROM games WHERE appid = 3851160;

 appid    | slug                    | release_date | release_date_raw | coming_soon
 3851160  | principal-panic-3851160 | 2028-10-31   |                  | t
```

## Why this happens

Steam frequently sets `release_date.coming_soon=true` *with* a placeholder
`release_date.date` like `"Oct 31, 2028"` (Halloween) or `"Dec 31, 2030"` for indie
horror / announced titles. Our crawler parses the placeholder via `_parse_release_date`
(`src/library-layer/library_layer/services/crawl_service.py:602-611`) and stores it in
the `release_date DATE` column. The data is *technically correct* — that's what Steam
advertises — but the UI labels it "RELEASED" past-tense and emits it as JSON-LD
`datePublished`, both of which are wrong while `coming_soon=true`.

The DB and `Game` pydantic model already carry `coming_soon`
(`src/library-layer/library_layer/models/game.py:26`), but
`/api/games/{appid}/report` doesn't expose it, so the frontend has no signal to render
the tile correctly.

## Approach

Surface `coming_soon` from the API and use it as the source of truth in the game page:

- **QuickStats tile**: render label **"RELEASES"** (future-tense) when `comingSoon=true`,
  otherwise keep **"RELEASED"**. Continue showing the date itself either way — it's
  Steam's announced date and useful context.
- **JSON-LD `datePublished`**: omit entirely when `comingSoon=true`. A future
  `datePublished` is invalid on an "already-published" `VideoGame` schema item.

Single forward path, no flag.

## Files to modify

### 1. `src/lambda-functions/lambda_functions/api/handler.py` (~L276–310)
Add `"coming_soon": game.coming_soon` to the `game_meta` dict inside `get_game_report`,
adjacent to `release_date`.

### 2. `frontend/lib/api.ts` (~L73)
Add `coming_soon?: boolean;` to the `game` shape inside `getGameReport`'s return type,
next to `release_date?: string;`.

### 3. `frontend/app/games/[appid]/[slug]/page.tsx`
- L95–125: add `comingSoon?: boolean;` to the `gameData` shape.
- L148: after `if (g.release_date) gameData.releaseDate = g.release_date;` add
  `if (g.coming_soon != null) gameData.comingSoon = g.coming_soon;`.
- L219: change
  `...(gameData.releaseDate ? { "datePublished": gameData.releaseDate } : {}),`
  to also gate on `!gameData.comingSoon` — emit `datePublished` only when the release
  date exists *and* the game isn't coming-soon.
- L337: pass `comingSoon={gameData.comingSoon}` into `<GameReportClient />`.

### 4. `frontend/app/games/[appid]/[slug]/GameReportClient.tsx`
- L45 props interface: add `comingSoon?: boolean;`.
- L104 destructure: add `comingSoon,`.
- L243: pass `comingSoon={comingSoon}` into `<QuickStats />`.

### 5. `frontend/components/game/QuickStats.tsx`
- L25 `QuickStatsProps`: add `comingSoon?: boolean;`.
- L60 destructure: add `comingSoon,`.
- L132: switch the tile label from `<span ...>Released</span>` to
  `<span ...>{comingSoon ? "Releases" : "Released"}</span>`.

## Out of scope

- `_parse_release_date` and the DB value — Steam genuinely advertises this date;
  truncating or sentinel-rejecting it would lose information used by the Coming Soon
  feed and the benchmark cohort year. The fix is presentational, not ingestion-side.
- `mv_new_releases` / `find_recently_released` — already filter `coming_soon = FALSE`,
  so this game is not appearing in any "Recently Released" feed; the bug is local to
  its own game page tile.

## Verification

1. **Backend smoke** — local API:
   `curl http://localhost:<port>/api/games/3851160/report | jq .game.coming_soon` → `true`.
2. **Frontend visual** — `cd frontend && npm run dev`, open
   `/games/3851160/principal-panic-3851160`, confirm:
   - Tile reads **"RELEASES · Oct 31, 2028"** (not "RELEASED").
   - Page source has no `"datePublished":"2028-10-31"` inside the JSON-LD blob.
3. **Regression** — open any released game (`coming_soon=false`); tile still says
   **"RELEASED"** and JSON-LD still includes `datePublished`.
4. **Tests** — `frontend/tests/game-report.spec.ts` exercises this page via Playwright;
   run `npx playwright test game-report.spec.ts` and add a fixture/case for
   `coming_soon=true` if one isn't already present.
