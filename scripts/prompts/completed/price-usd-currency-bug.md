# Fix `price_usd` currency bug — force USD on Steam appdetails + backfill

## Context

Game detail pages show wildly wrong prices for many games — e.g. `Shogun Showdown` (appid 2084000) renders at **$8250**. The real US price is $14.99 (currently $7.49 on sale).

Investigation traced it to a missing `cc=us` parameter on Steam's `/api/appdetails` calls. Without `cc`, Steam geolocates by caller IP and returns `price_overview` in a non-USD currency. The crawler then blindly divides `price_overview.final` by 100 and writes the result to `games.price_usd` — no currency check.

**Evidence**:
- DB: `SELECT price_usd FROM games WHERE appid=2084000` → `8250.00`.
- Live: `appdetails?appids=2084000&cc=us` → `{"currency":"USD","final":749}` (correct $7.49).
- Live: `appdetails?appids=2084000&cc=cl` → `{"currency":"CLP","initial":830000}`. A prior crawl captured a close value (CLP 825 000 → /100 → **8250** stored as "USD").
- Systemic: prod scan finds many games with `price_usd > 100`, including:
  - 548650 Lightspeed Frontier → $16 000
  - 556680 INTRUDER - WAR AREAS → $17 000
  - 351170 Pixel: ru² → $10 500
  - 576230 Home Tech VR → $5 500
  - 542270 Project Alpha 002 → $3 300
- **Why it's intermittent**: which country Steam geolocates to depends on AWS egress IPs and Steam's CDN — some crawls land on USD, some don't. Games crawled during a non-USD window are wrong.

**Goal**: every game's `price_usd` column holds a value in US dollars, always. New crawls are correct by construction; existing bad rows are repaired.

## Root cause (specific file:line)

- `src/library-layer/library_layer/fetcher.py:113-114` — `_get_with_retry(APPDETAILS_URL, {"appids": str(appid), "l": "english"})` — no `cc`.
- `src/library-layer/library_layer/steam_source.py:252-259` — `self._get_with_retry(APP_DETAILS_URL, appids=str(appid), l="english")` — no `cc`.
- `src/library-layer/library_layer/services/crawl_service.py:334-338` — divides `price_info.get("final", 0) / 100.0` and stores as `price_usd` with **no check** that `price_overview.currency == "USD"`.
- `src/library-layer/library_layer/fetcher.py:129-131` — same division, same missing check.

## Design

### 1. Force USD on every appdetails call

- `steam_source.py:252` — `get_app_details(appid)` calls `self._get_with_retry(APP_DETAILS_URL, appids=str(appid), l="english", cc="us")`.
- `fetcher.py:113-114` — add `"cc": "us"` to the params dict.

This alone makes all future crawls correct.

### 2. Hard guard: refuse non-USD in `_write_game_data`

In `src/library-layer/library_layer/services/crawl_service.py`, right around line 334-338:

```python
price_info = details.get("price_overview") or {}
is_free: bool = bool(details.get("is_free", False))
price_usd: float | None = None
if price_info and not is_free:
    currency = price_info.get("currency")
    if currency != "USD":
        logger.warning(
            "appdetails returned non-USD price",
            extra={"appid": appid, "currency": currency, "final": price_info.get("final")},
        )
        # leave price_usd = None — better to have no price than a wrong one
    else:
        price_usd = price_info.get("final", 0) / 100.0
```

Apply the same check in `fetcher.py:129-131`. This is the safety net: even if `cc=us` stops working for some reason (Steam outage, param change, broken regional IP), we never again silently store a CLP value in `price_usd`.

### 3. Backfill — re-crawl affected rows

Any existing `price_usd` that came from a non-USD crawl is wrong. After the code fix ships, the tiered refresh schedule (`tiered-refresh-schedule.org`) will eventually self-heal every row — but only at tier cadence: S ≤ 2 days, A ≤ 7 days, **B ≤ 21 days, C ≤ 90 days**. Most of the broken rows we see are low-review long-tail titles (B/C), so waiting means weeks-to-months of visibly wrong prices on the site. The backfill compresses that into hours.

- Identify affected rows: `SELECT appid FROM games WHERE is_free = false AND price_usd > 100` is a rough but good proxy — no real Steam game in this catalog costs $100+. Save the list to a CSV.
- Re-queue those appids to the metadata-crawl SQS queue: `poetry run python scripts/sp.py queue metadata <appid...>`.
- After crawl completes (check `updated_at` / logs), re-verify with: `SELECT COUNT(*) FROM games WHERE price_usd > 100 AND is_free = false` — should be ~0 (true whale-priced games can exceed $100, but they are rare; a tight whitelist can stay).

Optional: a one-shot script `scripts/backfill_price_currency.py` that does the select → queue → wait → verify loop. Not strictly required — `sp.py queue metadata` is enough.

### 4. Test coverage

- `tests/services/test_crawl_service.py` — add fixture variant where `price_overview.currency != "USD"`; assert `price_usd` stored as `None` and a warning log is emitted.
- `tests/services/test_crawl_service.py` — add fixture variant where `price_overview.currency == "USD"`; assert `price_usd` stored as `final / 100` (existing happy-path coverage may already assert this — extend rather than duplicate).
- Smoke test against Steam: `curl -s 'https://store.steampowered.com/api/appdetails?appids=440&cc=us' | jq '."440".data.price_overview.currency'` → `"USD"`. Not a unit test, but worth running once locally.

## Critical files

**Edit**:
- `src/library-layer/library_layer/steam_source.py:252` — add `cc="us"` param.
- `src/library-layer/library_layer/fetcher.py:113-114` — add `"cc": "us"` to params dict.
- `src/library-layer/library_layer/fetcher.py:129-131` — assert `currency == "USD"`; else `price_usd = None` + warn.
- `src/library-layer/library_layer/services/crawl_service.py:334-338` — same currency guard.
- `tests/services/test_crawl_service.py` — add non-USD fixture test + happy-path assertion.

**Reference (no edits)**:
- `src/lambda-functions/migrations/0001_initial_schema.sql:19` — `price_usd NUMERIC(8,2)` column definition.
- `doc/steam-apis.org:74-163` — Steam API doc, price_overview schema.
- `frontend/app/games/[appid]/[slug]/GameReportClient.tsx:178` — display code; no changes needed, already correct (formats value as USD).
- `src/lambda-functions/lambda_functions/api/handler.py:265` — API response; no changes needed.

**Run (post-deploy, backfill)**:
- `poetry run python scripts/sp.py db --env production query "SELECT appid FROM games WHERE is_free = false AND price_usd > 100"` → CSV.
- `poetry run python scripts/sp.py queue metadata <appid...>` (or loop from the CSV).
- Re-verify after crawl completes.

## Verification

**Local**:
1. `poetry run pytest tests/services/test_crawl_service.py` — new test cases pass.
2. `curl -s 'https://store.steampowered.com/api/appdetails?appids=2084000&cc=us' | jq` — confirm `price_overview.currency == "USD"` and `final == 749` (or current value).
3. Run the crawler locally against appid 2084000 with live network; inspect resulting `price_usd` — expect ~$7.49 or ~$14.99.

**Staging**:
1. Deploy code. Queue metadata crawl for appid 2084000 (`sp.py queue metadata 2084000 --env staging`).
2. `sp.py db --env staging query "SELECT price_usd FROM games WHERE appid=2084000"` → should now be USD (single-digit, not $8 250).
3. CloudWatch: check for any `"appdetails returned non-USD price"` warnings — should be zero once `cc=us` is wired.

**Production**:
1. Deploy code.
2. Backfill affected rows (step 3 in Design).
3. Re-run `SELECT COUNT(*) FROM games WHERE is_free = false AND price_usd > 100` — should drop from many to ~0 (or only legit whale-priced SKUs).
4. Spot-check `Shogun Showdown` page — price should render as $7.49 (or whatever the US Steam price is at crawl time).

## Rollback

- The code changes are additive and self-contained: revert the three edits and crawls resume prior (broken) behavior.
- The backfill is not reversible (we overwrite `price_usd`) but the new values are *correct*, so rollback is unnecessary.

## Explicitly out of scope

- Storing non-USD prices (multi-currency support). We only care about USD.
- Storing both `initial` and `final` (discount-aware pricing). Current schema keeps a single `price_usd`; no change.
- Historical price tracking (`price_usd` over time). Separate feature; not driven by this bug.
- Frontend changes. Display code is correct; only the stored value is wrong.
- S3-archived raw appdetails blobs. We don't retroactively rewrite archives; the next crawl supersedes them.

## Sources

- Steam Web API docs — [appdetails endpoint](https://store.steampowered.com/api/appdetails) (undocumented; community reference e.g. [Steam Web API on SteamDB](https://steamdb.info/blog/steamdb-api/)).
- `ARCHITECTURE.org:249` — project-local notes on Steam endpoints.
- `doc/steam-apis.org:74-163` — project-local schema for `price_overview`.
