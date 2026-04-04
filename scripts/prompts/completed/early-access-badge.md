# Add Early Access Badge to Game Cards and Detail Pages

## Problem

~15,725 games in the catalog are in Early Access (Steam genre ID 70), but there's no
visual indicator anywhere in the UI. The data already exists in `game_genres` — we just
need to surface it.

## Approach

Use an `EXISTS` subquery to compute `is_early_access` at query time — no migration, no
new column, always accurate. The `game_genres(appid, genre_id)` PK index makes this cheap.

## What to Build

### 1. `game_repo.py` — Add `is_early_access` to `list_games()` SELECT

Add to the SELECT clause:
```sql
EXISTS(SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = 70) AS is_early_access
```

### 2. API handler — Add `is_early_access` to game report response

In `get_game_report()`, check if the game has genre 70 and include in `game_meta`:
```python
game_meta["is_early_access"] = 70 in {g.get("id") for g in _tag_repo.find_genres_for_game(appid)}
```
(Genres are already fetched on the line above — reuse the data.)

### 3. Frontend types — Add field

`frontend/lib/types.ts`: add `is_early_access?: boolean;` to Game interface.

### 4. GameCard — Add EA badge overlay

`frontend/components/game/GameCard.tsx`: add an "Early Access" badge on the card image,
similar to the Hidden Gem badge but positioned top-left with a distinct color (blue or
purple to match Steam's EA styling).

### 5. Game detail page — Add EA badge

`frontend/app/games/[appid]/[slug]/page.tsx`: pass `isEarlyAccess` prop to GameReportClient.
`frontend/app/games/[appid]/[slug]/GameReportClient.tsx`: add EA badge in the hero/badges
section alongside DeckCompatibilityBadge and HiddenGemBadge.

### 6. Tests — Update mock data

`frontend/tests/fixtures/mock-data.ts`: add `is_early_access: false` to mock games.

## Files to Modify

| File | Change |
|---|---|
| `src/library-layer/library_layer/repositories/game_repo.py` | Add EXISTS subquery to `list_games()` SELECT |
| `src/lambda-functions/lambda_functions/api/handler.py` | Add `is_early_access` to `game_meta` dict |
| `frontend/lib/types.ts` | Add `is_early_access?: boolean` to Game |
| `frontend/components/game/GameCard.tsx` | Add EA badge on card image |
| `frontend/app/games/[appid]/[slug]/page.tsx` | Extract + pass `isEarlyAccess` |
| `frontend/app/games/[appid]/[slug]/GameReportClient.tsx` | Add EA badge in hero section |
| `frontend/tests/fixtures/mock-data.ts` | Add field to mock games |

## Verification

- `GET /api/games/646570/report` (Slay the Spire 2) → `game.is_early_access: true`
- `GET /api/games?limit=5` → EA games have `is_early_access: true`
- Visual: EA badge appears on game cards and detail page
- `poetry run pytest -v` passes
