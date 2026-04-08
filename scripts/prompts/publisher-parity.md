# Add Publisher parity to Developer UI/analytics

## Context

The game detail UI currently surfaces a clickable **Developer** chip in `QuickStats.tsx` (lines 125-142) that links to `/developer/{slug}`, backed by a full stack: `developer_slug` DB column + index, `GameRepository.list_games(developer=...)` filter, `/api/developers/{slug}/analytics`, `analytics_repo.find_developer_portfolio()`, and the `/developer/[slug]` page with `DeveloperPortfolio` component.

**Publisher data already exists** in the schema (`publisher TEXT`, `publishers JSONB`) and on the `Game` / `GameSummary` models, but is entirely invisible to users — no chip, no page, no filter, no analytics endpoint. On Steam itself, SteamDB, and the Steam store, publisher is consistently shown alongside developer because they are often different entities (e.g. indie dev + large publisher) and publisher portfolios are a meaningful discovery/intelligence axis (catalog breadth, franchise ownership, release cadence).

**Goal:** achieve full parity between Publisher and Developer across DB, crawl, API, and UI so users can click a publisher chip and land on a publisher portfolio page.

Industry convention (Steam store, SteamDB, IsThereAnyDeal, PCGamingWiki): show developer and publisher as two distinct clickable entities, labelled clearly, with publisher second. When they match (self-published titles), collapse to a single chip to reduce redundancy.

## Scope

### 1. Database
- New migration `0031_add_publisher_slug.sql`:
  - `ALTER TABLE games ADD COLUMN IF NOT EXISTS publisher_slug TEXT;`
  - Backfill: `UPDATE games SET publisher_slug = ... WHERE publisher_slug IS NULL AND publisher IS NOT NULL;` (SQL expression mirroring `slugify()` output).
- Separate migration file `0032_index_publisher_slug.sql` with `-- transactional: false` for `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_games_publisher_slug ON games(publisher_slug);`
- Update `schema.py` `games` CREATE TABLE block to include `publisher_slug TEXT` (reference only).

### 2. Crawl
- `services/crawl_service.py` around lines 332-343: mirror developer_slug logic:
  - `"publisher_slug": slugify(pubs[0]) if pubs else None`
- Update `GameRepository` upsert SQL to write `publisher_slug`.

### 3. Models
- `models/game.py`: add `publisher_slug: str | None = None` to `Game` and `GameSummary`.

### 4. Repository
- `repositories/game_repo.py` (~L426): add `publisher: str | None = None` param to `list_games()`, add `g.publisher_slug = %s` condition. Ensure SELECT includes `publisher_slug`.
- `repositories/analytics_repo.py`: add `find_publisher_portfolio(publisher_slug: str) -> dict`. Since the developer version is ~100 lines, extract a shared private helper `_find_entity_portfolio(column: str, slug: str)` and have both public methods call it.

### 5. API
- `api/handler.py`:
  - ~L295: add `publisher: str | None = None` query param to the games list endpoint, thread through to repo.
  - ~L563: add `GET /api/publishers/{slug}/analytics` endpoint mirroring developer analytics.
  - ~L368: include `"publisher": game.publisher` in game report metadata response if not already present.

### 6. Frontend
- `lib/types.ts`: add `PublisherPortfolio`, `PublisherSummary`, `PublisherGame` interfaces (duplicated from developer types; don't genericize yet).
- `lib/api.ts`: add `getPublisherAnalytics(slug)`; extend `getGames` params with `publisher?: string`.
- `components/game/GameHero.tsx`: add a **Publisher** credit alongside the existing Developer credit as an inline text line under the title (*by Developer · published by Publisher*), linking to `/publisher/{slug}`. **Hide the publisher credit when `publisher_slug === developer_slug`** so self-published titles don't show redundant metadata. Pass `publisher` + `publisherSlug` down from parent (`app/games/[appid]/[slug]/page.tsx`). (Drift note: credits were originally scoped into `QuickStats.tsx` as a tile, but long studio names squished the grid — see "Added things we did" below.)
- `components/game/GameCard.tsx`: do NOT add publisher — keeps card compact.
- New page: `frontend/app/publisher/[slug]/page.tsx` — copy `app/developer/[slug]/page.tsx`, swap labels and API call.
- New component: `components/analytics/PublisherPortfolio.tsx` — copy `DeveloperPortfolio.tsx`, swap labels.

### 7. Search / filter
- **Out of scope.** Publisher is chip-only, reachable via game detail → chip → `/publisher/{slug}`. No changes to `/search` page or its filter component. This matches the current developer UX (developer is also not a search facet).

### 8. Tests
- New `frontend/tests/publisher.spec.ts` covering `/publisher/{slug}` page load, game listing, chip click-through from game detail, and self-published chip-hiding behavior.
- Python tests: add `find_publisher_portfolio` repo test mirroring the developer version; add API handler test for `/api/publishers/{slug}/analytics` and the new `publisher` query param on games list.

## Critical files

- `src/lambda-functions/migrations/0031_add_publisher_slug.sql` (new)
- `src/lambda-functions/migrations/0032_index_publisher_slug.sql` (new, non-transactional)
- `src/library-layer/library_layer/schema.py`
- `src/library-layer/library_layer/services/crawl_service.py` (~L340)
- `src/library-layer/library_layer/models/game.py`
- `src/library-layer/library_layer/repositories/game_repo.py` (~L426, upsert)
- `src/library-layer/library_layer/repositories/analytics_repo.py` (~L349)
- `src/lambda-functions/lambda_functions/api/handler.py` (~L295, L368, L563)
- `frontend/lib/api.ts`, `frontend/lib/types.ts`
- `frontend/components/game/GameHero.tsx` (credit line under title)
- `frontend/app/publisher/[slug]/page.tsx` (new)
- `frontend/components/analytics/PublisherPortfolio.tsx` (new)
- `frontend/tests/publisher.spec.ts` (new)

## Reuse

- `library_layer/utils/slugify.py` — already used by developer_slug
- Shared `_find_entity_portfolio` helper in `analytics_repo.py` to avoid duplicating ~100 lines
- `TILE_CLASS` / `TILE_STYLE` constants in QuickStats
- `DeveloperPortfolio` layout copied into `PublisherPortfolio`

## Verification

1. **Local DB**: `bash scripts/dev/start-local.sh && bash scripts/dev/migrate.sh` — confirm migrations apply idempotently; `\d games` shows `publisher_slug` + index.
2. **Unit tests**: `poetry run pytest tests/repositories/test_game_repo.py tests/repositories/test_analytics_repo.py tests/test_api.py -v`.
3. **Lint**: `poetry run ruff check . && poetry run ruff format --check .`.
4. **API smoke**: `./scripts/dev/run-api.sh` then
   - `curl 'http://localhost:8000/api/games?publisher=valve'`
   - `curl 'http://localhost:8000/api/publishers/valve/analytics'`
5. **Crawl smoke**: `poetry run python main.py --appid 440 --dry-run` — confirm `publisher_slug` populated.
6. **Frontend**: `cd frontend && npm run dev` — visit a game where developer ≠ publisher (e.g. a Devolver Digital title), confirm both chips render and link correctly; visit a self-published title (Valve) and confirm only the Developer chip shows. Visit `/publisher/{slug}` and confirm portfolio renders.
7. **E2E**: `cd frontend && npm run test:e2e -- publisher`.

## Resolved decisions

- **Publisher chip hidden when `publisher_slug === developer_slug`** — matches Steam store; avoids redundancy on self-published titles.
- **No search facet** — publisher is chip-only, mirrors current developer UX.

## Added things we did (beyond the original plan)

Tracked here so follow-up PRs know what drifted from the initial spec.

- **Developer/Publisher moved out of `QuickStats` into `GameHero`** as an inline credits line (*by Developer · published by Publisher*), matching Steam/SteamDB/IGDB convention. Rationale: with 6+ tiles in `QuickStats`, long studio names were squishing the grid. Keeping the tile grid numeric-only (Reviews / Released / Price / Velocity / Analyzed) makes it resilient to long names and visually cleaner. Publisher is still hidden when it matches developer.
- **`SteamFactsCard` header cleanup**: removed the inner `👍 Steam Facts` title from the card. On unanalyzed pages the outer `<SectionLabel>Steam Facts</SectionLabel>` already labels the block, so the inner header was a duplicate. The card now only shows the `Crawled <time>` freshness stamp.
- **`scoreContextSentence()` de-duplication**: dropped the leading `"Very Positive — "` / `"Overwhelmingly Positive — "` prefixes from each context string. `<ScoreBar />` already renders `review_score_desc` (Steam's own label), so the sentence repeated it. The sentences now start directly with the context ("Fewer than 5%…", "This puts the game in the top 30%…").
- **`game-report.spec.ts`**: updated the "Steam Facts zone" test — it no longer asserts the inner `Steam Facts` text (removed), only the `steam-facts-crawled` freshness stamp.
