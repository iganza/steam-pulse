# Fix Tags: Replace Steam Categories with Player Tags from SteamSpy

## Problem

The `tags` / `game_tags` tables contain **Steam feature categories** (Single-player,
Co-op, Steam Cloud, VR Supported) — not player-applied tags (Roguelike, Metroidvania,
FPS, Soulslike). This happened because `crawl_service.py` merges genres + categories
into `tag_items` and writes them all to the tags table.

Player tags are what users expect when they visit `/tag/roguelike`. Without them, the
tag system is useless for game discovery.

## Current State

**Three data sources from Steam — two stored correctly, one wrong:**

| Source                 | Examples                          | Where stored                                     | Status               |
|------------------------|-----------------------------------|--------------------------------------------------|----------------------|
| Steam genres           | Action, RPG, Strategy             | `genres` + `game_genres`                         | ✅ Correct           |
| Steam categories       | Single-player, Co-op, Steam Cloud | `game_categories` ✅ AND `tags` + `game_tags` ❌ | Duplicated into tags |
| Player tags (SteamSpy) | Roguelike, FPS, Soulslike         | **Nowhere**                                      | ❌ Missing           |

**What the tag tables currently hold (159k games, 60 "tags"):**
All 60 rows are feature flags: Single-player (151k), Family Sharing (138k),
Steam Achievements (73k), etc. Zero player tags exist.

**Categories already have their own proper table** — `game_categories(appid,
category_id, category_name)` stores the same data correctly. The duplication
into `tags` is pure waste.

## Goal State

- `tags` / `game_tags` → **Player tags only** (from SteamSpy API)
- `genres` / `game_genres` → Steam genres (unchanged)
- `game_categories` → Steam feature flags (unchanged, already correct)
- `crawl_service.py` → Stop writing categories into the tags table
- New backfill script → Populate player tags from SteamSpy for existing games

---

## What to Build

### 1. Fix `crawl_service.py` — Stop Polluting Tags

**File:** `src/library-layer/library_layer/services/crawl_service.py`

Current code (lines 362–370):
```python
tag_items = genres + categories          # ← BUG: categories pollute tags
self._tag_repo.upsert_tags(
    [
        {"appid": appid, "name": item.get("description") or "", "votes": 0}
        for item in tag_items
        if item.get("description")
    ]
)
self._tag_repo.upsert_genres(appid, genres)
self._tag_repo.upsert_categories(appid, categories)
```

**Fix:** Remove the `tag_items` merge and `upsert_tags()` call entirely. Genres
and categories already have their own dedicated upsert methods. The tags table
should only be written to by the SteamSpy backfill (or a future SteamSpy call
in the crawl pipeline).

New code:
```python
self._tag_repo.upsert_genres(appid, genres)
self._tag_repo.upsert_categories(appid, categories)
```

That's it — just delete the 7 lines that build `tag_items` and call `upsert_tags()`.

### 2. Add SteamSpy Source to `steam_source.py`

**File:** `src/library-layer/library_layer/steam_source.py`

Add a new constant and method:

```python
STEAMSPY_API_URL = "https://steamspy.com/api.php"
```

Add method to `DirectSteamSource`:

```python
def get_steamspy_data(self, appid: int) -> dict:
    """Fetch full SteamSpy data for a game.

    Returns the raw SteamSpy response dict, or {} on error.
    Caller extracts tags, owners, playtime, etc. as needed.

    SteamSpy rate limit: ~4 req/sec. Caller must handle pacing.
    """
    self._jitter()
    try:
        resp = self._get_with_retry(
            STEAMSPY_API_URL,
            request="appdetails",
            appid=str(appid),
        )
        return resp.json()
    except Exception:
        logger.warning("SteamSpy fetch failed for %s", appid)
        return {}
```

**Full SteamSpy response format** for `request=appdetails&appid=440`:
```json
{
  "appid": 440,
  "name": "Team Fortress 2",
  "developer": "Valve",
  "publisher": "Valve",
  "score_rank": "",
  "positive": 384000,
  "negative": 35000,
  "userscore": 0,
  "owners": "50,000,000 .. 100,000,000",
  "average_forever": 12847,
  "average_2weeks": 234,
  "median_forever": 312,
  "median_2weeks": 18,
  "price": "0",
  "initialprice": "0",
  "discount": "0",
  "ccu": 68423,
  "languages": "English, French, ...",
  "genre": "Action, Free to Play",
  "tags": {"Free to Play": 62968, "Hero Shooter": 61037, ...}
}
```

Skip `name`, `developer`, `publisher`, `genre` when storing — those are
authoritative from Steam's own API. Store everything else.

### 3. Add `task: "tags"` to the Spoke Architecture

The backfill must run in the cloud via the existing spoke fan-out, not just
locally. This means adding a third task type (`"tags"`) alongside the existing
`"metadata"` and `"reviews"` tasks.

**Existing spoke pattern (for reference):**
- Primary handler receives SQS messages → dispatches to spoke Lambdas
  via async `lambda.invoke()` with `task` field routing
- Spoke handler routes on `task` → calls SteamSpy → uploads result to S3
- Ingest handler reads S3 payload → upserts to DB

#### 3a. New Pydantic Models

**File:** `src/lambda-functions/lambda_functions/crawler/models.py`
(or wherever `MetadataSpokeRequest`, `ReviewSpokeRequest` etc. live)

```python
class TagsSpokeRequest(BaseModel):
    appid: int
    task: Literal["tags"] = "tags"

class TagsSpokeResult(BaseModel):
    appid: int
    task: Literal["tags"] = "tags"
    success: bool
    s3_key: str | None = None
    count: int = 0          # number of tags found
    spoke_region: str
    error: str | None = None
```

#### 3b. Spoke Handler — Process `task: "tags"`

**File:** wherever the spoke handler routes on `task` (e.g. `spoke_handler.py`)

Add a new branch in the task dispatcher:

```python
case "tags":
    time.sleep(0.3)  # SteamSpy rate limit: ~4 req/sec globally
    raw = steam_source.get_steamspy_data(appid)   # new method from step 2
    if not raw:
        return TagsSpokeResult(appid=appid, success=True, count=0, spoke_region=region)

    # Extract tags for game_tags table
    tags_dict: dict = raw.get("tags") or {}
    tags = [{"name": k, "votes": int(v)} for k, v in tags_dict.items()]

    # Store full payload (minus overlapping Steam fields) in steamspy_data
    steamspy_payload = {k: raw[k] for k in (
        "score_rank", "positive", "negative", "userscore", "owners",
        "average_forever", "average_2weeks", "median_forever", "median_2weeks",
        "price", "initialprice", "discount", "ccu", "languages",
    ) if k in raw}

    result_data = {"tags": tags, "steamspy": steamspy_payload}
    key = f"spoke-results/{region}/tags/{appid}.json.gz"
    s3.put_object(Bucket=bucket, Key=key, Body=gzip.compress(json.dumps(result_data).encode()))
    return TagsSpokeResult(appid=appid, success=True, s3_key=key,
                           count=len(tags), spoke_region=region)
```

#### 3c. Ingest Handler — Process `task: "tags"` Results

**File:** `src/lambda-functions/lambda_functions/crawler/ingest_handler.py`

Add `_handle_tags()`:

```python
def _handle_tags(msg: TagsSpokeResult) -> None:
    if not msg.success or not msg.s3_key:
        return
    response = _s3.get_object(Bucket=_assets_bucket_name, Key=msg.s3_key)
    data = json.loads(gzip.decompress(response["Body"].read()))

    # Upsert player tags into tags/game_tags
    tags = data.get("tags") or []
    if tags:
        _tag_repo.upsert_tags(
            [{"appid": msg.appid, "name": t["name"], "votes": t["votes"]} for t in tags]
        )

    # Upsert SteamSpy metrics into steamspy_data
    steamspy = data.get("steamspy") or {}
    if steamspy:
        _steamspy_repo.upsert(msg.appid, steamspy)

    _s3.delete_object(Bucket=_assets_bucket_name, Key=msg.s3_key)
```

And add routing in `_ingest_record()`:
```python
elif task == "tags":
    msg = TagsSpokeResult.model_validate(body)
    _handle_tags(msg)
```

#### 3d. Direct Invocation Support

**File:** `src/lambda-functions/lambda_functions/crawler/handler.py`

Add a new direct invocation request model:

```python
class BackfillTagsRequest(BaseModel):
    action: Literal["backfill_tags"] = "backfill_tags"
    limit: int | None = None         # cap number of games (for testing)
```

Add to the discriminated union adapter and match block:

```python
case BackfillTagsRequest():
    appids = _get_backfill_appids(req.limit)
    for appid in appids:
        _dispatch_tags_to_spoke(appid)
    return {"queued": len(appids)}
```

**`_get_backfill_appids(limit)`** query — all games:

```sql
SELECT g.appid FROM games g
WHERE g.type = 'game'
ORDER BY g.review_count DESC
```

Apply `LIMIT` if provided (for testing smaller batches).

**`_dispatch_tags_to_spoke(appid)`** — same pattern as `_dispatch_to_spoke()`
but creates a `TagsSpokeRequest` instead. Uses `appid % len(_spoke_targets)`
for deterministic spoke selection.

**SteamSpy rate limit consideration:** SteamSpy allows ~4 req/sec globally.
With multiple spokes, add a 300ms sleep in the spoke handler for tag fetches
to avoid hitting the limit. Since tags are a one-time backfill (not latency
sensitive), this is acceptable.

### 4. Local CLI Script for Testing + Cloud Trigger

**File:** `scripts/backfill_player_tags.py`

This script works in two modes:

**Mode 1 — Local execution** (test single games, small batches):
```bash
# Test a single game locally
poetry run python scripts/backfill_player_tags.py --appids 440

# Test a few games
poetry run python scripts/backfill_player_tags.py --appids 440,570,730

# Dry run — fetch from SteamSpy but don't write to DB
poetry run python scripts/backfill_player_tags.py --appids 440 --dry-run

# Clear existing polluted tags first (only needed once)
poetry run python scripts/backfill_player_tags.py --clear
```

**Mode 2 — Cloud execution** (invoke the crawler Lambda to fan out via spokes):
```bash
# Backfill all ~159k games via spoke fan-out
poetry run python scripts/backfill_player_tags.py --cloud

# Test with a small batch first
poetry run python scripts/backfill_player_tags.py --cloud --limit 100

# Equivalent to:
aws lambda invoke --function-name <crawler-fn> \
    --payload '{"action": "backfill_tags"}' /dev/stdout
```

**Implementation details for local mode:**

- Use `DATABASE_URL` from env or `.env` file
- Use `httpx` (sync) to call SteamSpy directly
- Use `TagRepository.upsert_tags()` for DB writes
- Rate limit: `time.sleep(0.25)` between calls (4/sec), with random jitter ±50ms
- Batch commit: every 50 games
- `--resume` flag: skip appids that already have rows in `game_tags`
- Progress: `f"[{i}/{total}] {appid} {game_name}: {len(tags)} tags"`
- On Ctrl+C: commit current batch, print summary, exit cleanly

**Implementation details for cloud mode:**

- Uses `boto3` to invoke the crawler Lambda with `BackfillTagsRequest` payload
- Resolves Lambda function name from SSM param (same as deploy script)
- Prints: "Queued {n} games for tag backfill via spoke fan-out"
- Work is distributed across spokes automatically

### 5. Wire into Future Crawls

Update the spoke metadata handler to also call `get_steamspy_data()` during the
normal metadata crawl, so new games and re-crawls get full SteamSpy data automatically.
Conditional on `review_count >= 50` to avoid API calls for empty shells.

### 6. Migration — New `steamspy_data` Table + Clean Up Tags

**File:** `src/lambda-functions/migrations/0011_steamspy_data.sql`

```sql
-- New table for SteamSpy enrichment data.
-- One row per appid, upserted on each backfill/crawl.
CREATE TABLE IF NOT EXISTS steamspy_data (
    appid             INTEGER PRIMARY KEY REFERENCES games(appid),
    score_rank        TEXT,
    positive          INTEGER,
    negative          INTEGER,
    userscore         INTEGER,
    owners            TEXT,            -- range string: "2,000,000 .. 5,000,000"
    average_forever   INTEGER,         -- minutes
    average_2weeks    INTEGER,         -- minutes
    median_forever    INTEGER,         -- minutes
    median_2weeks     INTEGER,         -- minutes
    price             INTEGER,         -- cents (current)
    initialprice      INTEGER,         -- cents (original)
    discount          INTEGER,         -- percentage
    ccu               INTEGER,         -- peak concurrent users
    languages         TEXT,
    upserted_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Remove category-polluted data from tags table.
-- Tags will be repopulated by SteamSpy backfill.
-- game_categories table is unaffected.
TRUNCATE game_tags;
DELETE FROM tags;
```

---

## Files to Create / Modify

| File | Action |
|---|---|
| `src/library-layer/library_layer/services/crawl_service.py` | Remove `tag_items` merge + `upsert_tags()` call (lines 362–368). Add SteamSpy fetch to spoke metadata handler (step 5). |
| `src/library-layer/library_layer/steam_source.py` | Add `STEAMSPY_API_URL` + `get_steamspy_data()` method |
| `src/library-layer/library_layer/repositories/steamspy_repo.py` | Create — `SteamspyRepository.upsert(appid, data)` |
| `src/lambda-functions/lambda_functions/crawler/models.py` | Add `TagsSpokeRequest`, `TagsSpokeResult`, `BackfillTagsRequest` |
| `src/lambda-functions/lambda_functions/crawler/handler.py` | Add `backfill_tags` direct invocation + `_dispatch_tags_to_spoke()` |
| `src/lambda-functions/lambda_functions/crawler/spoke_handler.py` | Add `task: "tags"` branch |
| `src/lambda-functions/lambda_functions/crawler/ingest_handler.py` | Add `_handle_tags()` + `SteamspyRepository` + routing |
| `scripts/backfill_player_tags.py` | Create — local CLI + cloud invoke script |
| `src/lambda-functions/migrations/0011_steamspy_data.sql` | Create — new table + truncate tag pollution |

## Constraints

- Do NOT modify the `tags` or `game_tags` table schemas — they already have the
  right shape (name, slug, votes). Only the *data* is wrong.
- Do NOT touch `genres`, `game_genres`, or `game_categories` — they are correct.
- Do NOT add SteamSpy as a dependency — it's a plain HTTP API, use existing `httpx`.
- The backfill script uses `psycopg2` directly (like other scripts in `scripts/`)
  and reads `DATABASE_URL` from env or `.env` file.
- `poetry run pytest -v` must pass after changes.
- `poetry run ruff check . && poetry run ruff format .` must be clean.

## Testing

- Verify `crawl_service.py` no longer writes to tags table during crawl.
- Run backfill script locally: `poetry run python scripts/backfill_player_tags.py --appids 440`
- Check tags: `SELECT t.name, gt.votes FROM tags t JOIN game_tags gt ON t.id = gt.tag_id WHERE gt.appid = 440 ORDER BY gt.votes DESC;` — should show Hero Shooter, FPS, etc.
- Check steamspy_data: `SELECT owners, average_forever, ccu FROM steamspy_data WHERE appid = 440;`
- Visit `/tag/fps` locally to verify it returns games.
- Existing tests must still pass.

## Execution Order

1. Apply migration 0011 (or `--clear` flag in script) to wipe polluted tags
2. Fix `crawl_service.py` to stop the bleeding
3. Test locally: `poetry run python scripts/backfill_player_tags.py --appids 440`
4. Verify: `SELECT t.name, gt.votes FROM tags t JOIN game_tags gt ON t.id = gt.tag_id WHERE gt.appid = 440 ORDER BY gt.votes DESC;`
5. Deploy to staging (includes migration, spoke handler changes, new models)
6. Cloud backfill: `poetry run python scripts/backfill_player_tags.py --cloud`
7. Monitor spoke logs, verify tags populate in staging DB
