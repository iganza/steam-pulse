# Fix "Just Added" — Use Steam Page Creation Date

## Problem

The "Just Added" lens on `/new-releases` shows 159,305 games for "This Month" and
"This Quarter". Root cause: `discovered_at` in `app_catalog` reflects when WE first
crawled the game into our DB — during the initial bulk seed, all ~159k games got
`discovered_at = NOW()` simultaneously, so every window count returns the full catalog.

## What "Just Added" Should Show

Coming-soon games that recently appeared on the Steam store — i.e., newly announced
games. Steam's `IStoreService/GetAppList/v1/` returns a `last_modified` Unix timestamp
per app. For new games, this is effectively the date their store page was created.

## Fix

### 1. Migration — add `steam_page_updated_at` to `app_catalog`

```sql
ALTER TABLE app_catalog ADD COLUMN IF NOT EXISTS steam_page_updated_at TIMESTAMPTZ;
```

New migration file: `src/lambda-functions/migrations/NNNN_steam_page_updated_at.py`

### 2. `catalog_service.py` — capture `last_modified` from API response

File: `src/library-layer/library_layer/services/catalog_service.py`

Line ~158 currently discards `last_modified`:
```python
# BEFORE
apps.extend({"appid": a["appid"], "name": a.get("name", "")} for a in batch)

# AFTER
from datetime import timezone
apps.extend({
    "appid": a["appid"],
    "name": a.get("name", ""),
    "steam_page_updated_at": (
        datetime.fromtimestamp(a["last_modified"], tz=timezone.utc)
        if a.get("last_modified") else None
    ),
} for a in batch)
```

### 3. Catalog repo — store it on upsert

File: `src/library-layer/library_layer/repositories/catalog_repo.py`

In the `upsert_apps` method (or equivalent), include `steam_page_updated_at` in the
INSERT/ON CONFLICT DO UPDATE. Only update it if the incoming value is non-NULL and
newer than the stored value (don't overwrite a good value with NULL).

```sql
steam_page_updated_at = CASE
    WHEN EXCLUDED.steam_page_updated_at IS NOT NULL
     AND (app_catalog.steam_page_updated_at IS NULL
          OR EXCLUDED.steam_page_updated_at > app_catalog.steam_page_updated_at)
    THEN EXCLUDED.steam_page_updated_at
    ELSE app_catalog.steam_page_updated_at
END
```

### 4. `mv_new_releases` matview — use `steam_page_updated_at` for "Just Added"

File: `src/library-layer/library_layer/schema.py`

The matview WHERE clause currently includes all recently-discovered games via:
```sql
OR (ac.discovered_at >= NOW() - INTERVAL '90 days')
```

Replace with:
```sql
OR (ac.steam_page_updated_at >= NOW() - INTERVAL '90 days')
```

Also expose `steam_page_updated_at` as a column in the matview SELECT (alongside
`discovered_at` which can stay for other purposes).

### 5. `new_releases_repo.py` — "Just Added" queries use `steam_page_updated_at`

File: `src/library-layer/library_layer/repositories/new_releases_repo.py`

The `get_added_since` and `count_added_since` methods currently filter on
`discovered_at`. Change both to filter on `steam_page_updated_at` instead.

Also update the ORDER BY in the feed query: `ORDER BY steam_page_updated_at DESC`.

### 6. `new_releases_service.py` — "Just Added" = coming-soon only

File: `src/library-layer/library_layer/services/new_releases_service.py`

The "Just Added" lens should only show `coming_soon = TRUE` games (newly announced,
not yet released). Add this filter to both the feed and the count queries.

Rationale: released games already appear in the "Released" lens. "Just Added" should
exclusively surface newly announced/coming-soon titles — games that just got a Steam
page but haven't launched yet.

## What NOT to Change

- `discovered_at` stays in `app_catalog` — it's still useful for internal housekeeping
- The "Released" and "Coming Soon" lenses are unaffected
- Frontend `NewReleasesClient.tsx` needs no changes — the API response shape is the same

## Verification

After deploying:
1. "This Month" and "This Quarter" counts on the "Just Added" tab should be small
   (only recently-announced games, not the full catalog)
2. The feed should show only `coming_soon = TRUE` games sorted by Steam page update date
3. Run `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_new_releases` after migration
