# Steam Deck Compatibility Integration — Implementation Prompt

## Goal

Add Steam Deck compatibility data to the SteamPulse platform. Fetch the
compatibility category during the metadata crawl, store it in the games table,
expose it via the API, and display it on game report pages.

---

## Data Source

Steam provides a **free, unauthenticated JSON endpoint** for Deck compatibility:

```
GET https://store.steampowered.com/saleaction/ajaxgetdeckappcompatibilityreport?nAppID={appid}
```

**Example response** (appid 440, Team Fortress 2):
```json
{
  "success": 1,
  "results": {
    "appid": 440,
    "resolved_category": 2,
    "resolved_items": [
      {"display_type": 3, "loc_token": "#SteamDeckVerified_TestResult_DefaultControllerConfigNotFullyFunctional"},
      {"display_type": 3, "loc_token": "#SteamDeckVerified_TestResult_ControllerGlyphsDoNotMatchDeckDevice"},
      {"display_type": 3, "loc_token": "#SteamDeckVerified_TestResult_InterfaceTextIsNotLegible"},
      {"display_type": 4, "loc_token": "#SteamDeckVerified_TestResult_DefaultConfigurationIsPerformant"},
      {"display_type": 1, "loc_token": "#SteamDeckVerified_TestResult_ExternalControllersNotSupportedPrimaryPlayer"}
    ]
  }
}
```

**Category values:**
- `0` = Unknown (not tested)
- `1` = Unsupported
- `2` = Playable
- `3` = Verified

**`display_type` values in `resolved_items`:**
- `1` = Unsupported (blocker)
- `2` = Verified (passes check)
- `3` = Playable (minor issue)
- `4` = Verified (passes check, alternate)

**`loc_token` patterns** — these are localization keys. Strip the prefix to get
a human-readable test name:
- `#SteamDeckVerified_TestResult_` prefix → e.g., "DefaultControllerConfigNotFullyFunctional"
- Convert camelCase to readable: "Default controller config not fully functional"

---

## Change 1 — Database Schema

Add two columns to the `games` table in `src/library-layer/library_layer/schema.py`:

```sql
-- In the CREATE TABLE games block, add after metacritic_score:
deck_compatibility   INTEGER,                 -- 0=unknown, 1=unsupported, 2=playable, 3=verified
deck_test_results    JSONB,                   -- raw resolved_items array from Steam
```

**Migration for existing data** — add to `create_all()` in schema.py using the
existing ALTER TABLE pattern:

```python
_add_column_if_missing(cur, "games", "deck_compatibility", "INTEGER")
_add_column_if_missing(cur, "games", "deck_test_results", "JSONB")
```

---

## Change 2 — Steam Client

Add a new method to `src/library-layer/library_layer/steam_source.py`:

```python
DECK_COMPAT_URL = "https://store.steampowered.com/saleaction/ajaxgetdeckappcompatibilityreport"

async def get_deck_compatibility(self, appid: int) -> dict:
    """Fetch Steam Deck compatibility report for an app.

    Returns dict with 'resolved_category' (int) and 'resolved_items' (list),
    or empty dict if unavailable.
    """
    await self._jitter()
    try:
        resp = await self._get_with_retry(DECK_COMPAT_URL, nAppID=str(appid))
        data = resp.json()
        if not data.get("success"):
            return {}
        results = data.get("results", {})
        return {
            "resolved_category": results.get("resolved_category", 0),
            "resolved_items": results.get("resolved_items", []),
        }
    except Exception:
        logger.debug("Deck compat unavailable for appid=%s", appid)
        return {}
```

**Important:** This endpoint is unauthenticated and free but rate limits
apply. The existing `_jitter()` delay and `_get_with_retry()` pattern should
be sufficient.

---

## Change 3 — Crawl Service

In `src/library-layer/library_layer/services/crawl_service.py`, within the
`crawl_app()` method, **after** the `get_app_details` and `get_review_summary`
calls but **before** the `game_repo.upsert()` call:

```python
# Fetch Steam Deck compatibility (non-blocking, best-effort)
deck_compat = await self._steam.get_deck_compatibility(appid)
```

Then add to the `game_data` dict:

```python
game_data["deck_compatibility"] = deck_compat.get("resolved_category", 0) if deck_compat else None
game_data["deck_test_results"] = json.dumps(deck_compat.get("resolved_items", [])) if deck_compat else None
```

**Failure handling:** If the Deck API fails, `deck_compat` is `{}` and both
fields are `None`. The crawl continues — Deck data is best-effort, never a
blocker.

---

## Change 4 — Game Repository

In `src/library-layer/library_layer/repositories/game_repo.py`, update the
`upsert()` method:

1. Add `deck_compatibility, deck_test_results` to the INSERT column list
2. Add `%(deck_compatibility)s, %(deck_test_results)s` to the VALUES list
3. Add to the ON CONFLICT DO UPDATE SET:
   ```sql
   deck_compatibility   = EXCLUDED.deck_compatibility,
   deck_test_results    = EXCLUDED.deck_test_results,
   ```

---

## Change 5 — Game Model

In `src/library-layer/library_layer/models/game.py`, add to the `Game` class:

```python
deck_compatibility: int | None = None
deck_test_results: list[dict] = []
```

Add a validator for `deck_test_results`:

```python
@field_validator("deck_test_results", mode="before")
@classmethod
def coerce_deck_results(cls, v: object) -> list[dict]:
    if v is None:
        return []
    if isinstance(v, str):
        import json
        return json.loads(v)
    return v  # type: ignore[return-value]
```

Add a computed property for display:

```python
@property
def deck_status(self) -> str:
    """Human-readable Steam Deck status."""
    return {0: "Unknown", 1: "Unsupported", 2: "Playable", 3: "Verified"}.get(
        self.deck_compatibility or 0, "Unknown"
    )
```

---

## Change 6 — API Response

The game detail API endpoint already serializes the Game model. The new fields
will automatically appear in responses. Verify that:

1. `GET /api/games/{slug}` returns `deck_compatibility` and `deck_test_results`
2. `GET /api/games` list endpoint includes `deck_compatibility` in each game

If the list endpoint uses a projection (SELECT specific columns), add the new
columns to it.

---

## Change 7 — Frontend Display

On the game report page, add a **Steam Deck badge** near the platform icons.

**Badge design:**
- Verified (3): Green badge with checkmark — "✅ Deck Verified"
- Playable (2): Yellow badge — "⚠️ Deck Playable"
- Unsupported (1): Red badge — "❌ Deck Unsupported"
- Unknown (0 or null): Gray badge — "❓ Deck Unknown"

**Test results tooltip/expandable:** On hover or click, show the resolved test
items as a list:
- Green (display_type 2 or 4): "✅ Default configuration is performant"
- Yellow (display_type 3): "⚠️ Controller glyphs do not match Deck device"
- Red (display_type 1): "❌ External controllers not supported"

**Loc token parsing:** Strip the `#SteamDeckVerified_TestResult_` prefix and
convert camelCase to space-separated words:

```javascript
function formatDeckTestResult(locToken) {
    const name = locToken.replace('#SteamDeckVerified_TestResult_', '');
    return name.replace(/([A-Z])/g, ' $1').trim();
}
```

---

## Change 8 — Filtering & Search

Add Steam Deck compatibility as a filter option to `game_repo.list_games()`:

```python
# New parameter
deck_status: str | None = None  # "verified", "playable", "unsupported", "unknown"

# SQL filter
if deck_status:
    deck_map = {"verified": 3, "playable": 2, "unsupported": 1, "unknown": 0}
    val = deck_map.get(deck_status)
    if val is not None:
        conditions.append("deck_compatibility = %s")
        params.append(val)
```

Expose this filter via the API query parameter: `GET /api/games?deck=verified`

---

## Tests

### Unit Tests (`tests/services/test_crawl_service.py`)

Add a test that verifies Deck compatibility data flows through the crawl:

```python
def test_crawl_app_stores_deck_compatibility(self, ...):
    """Deck compatibility should be stored when available."""
    # Mock steam_source.get_deck_compatibility to return {"resolved_category": 3, "resolved_items": [...]}
    # Run crawl_app(appid)
    # Assert game_repo.find_by_appid(appid).deck_compatibility == 3
    # Assert game_repo.find_by_appid(appid).deck_test_results is a non-empty list

def test_crawl_app_survives_deck_api_failure(self, ...):
    """Crawl should succeed even if Deck API returns empty."""
    # Mock steam_source.get_deck_compatibility to return {}
    # Run crawl_app(appid)
    # Assert game_repo.find_by_appid(appid).deck_compatibility is None
    # Assert game was still saved successfully
```

### Repository Tests (`tests/repositories/test_game_repo.py`)

```python
def test_upsert_with_deck_fields(self, game_repo):
    """Deck fields should be stored and retrieved."""
    game_data = _minimal_game_data(appid=1234)
    game_data["deck_compatibility"] = 3
    game_data["deck_test_results"] = json.dumps([{"display_type": 2, "loc_token": "test"}])
    game_repo.upsert(game_data)
    game = game_repo.find_by_appid(1234)
    assert game.deck_compatibility == 3
    assert len(game.deck_test_results) == 1

def test_list_games_filter_by_deck_status(self, game_repo):
    """Should filter games by Deck compatibility."""
    # Insert 3 games: verified, playable, unsupported
    # list_games(deck_status="verified") should return only 1
```

### API Tests

```python
def test_game_detail_includes_deck_fields(self, client):
    """Game detail endpoint should include Deck compatibility."""
    # Create game with deck_compatibility = 2
    resp = client.get("/api/games/test-game")
    assert resp.json()["deck_compatibility"] == 2
    assert resp.json()["deck_status"] == "Playable"  # if serialized via model
```

### Frontend Tests (Playwright)

```typescript
test('displays Deck Verified badge', async ({ page }) => {
    await mockAllApiRoutes(page);
    // Override game detail mock to include deck_compatibility: 3
    await page.goto('/games/test-game');
    await expect(page.locator('[data-testid="deck-badge"]')).toContainText('Verified');
});

test('displays Deck Playable badge with warning color', async ({ page }) => {
    // deck_compatibility: 2
    await page.goto('/games/test-game');
    const badge = page.locator('[data-testid="deck-badge"]');
    await expect(badge).toContainText('Playable');
});

test('hides Deck badge when unknown', async ({ page }) => {
    // deck_compatibility: 0 or null
    await page.goto('/games/test-game');
    await expect(page.locator('[data-testid="deck-badge"]')).toBeHidden();
});
```

---

## Implementation Order

1. Schema migration (add columns)
2. Game model (add fields + validator)
3. Game repo (update upsert SQL)
4. Steam client (new `get_deck_compatibility` method)
5. Crawl service (call Deck API, pass to game_data)
6. API filter (deck_status parameter)
7. Frontend badge display
8. Tests

## Verification

```bash
# Run schema migration
poetry run python -c "from library_layer.schema import create_all; ..."

# Test with a single game
poetry run python scripts/sp.py game crawl 440
# Verify: SELECT deck_compatibility, deck_test_results FROM games WHERE appid = 440;

# Run tests
poetry run pytest tests/ -k "deck" -v
```
