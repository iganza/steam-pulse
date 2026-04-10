# Production Read-Only Playwright Smoke Tests

## Goal

Run the Playwright E2E suite against production (steampulse.io) and staging to verify
every user-facing feature works with real data. All endpoints are read-only GET — zero
mutation risk. Catches regressions that mocked tests can't: missing data, broken API
responses, SSR hydration failures, console errors on real pages.

## Why separate from the mocked suite

The existing 16 spec files assert exact values from mock data ("Team Fortress 2",
review count 500000). Production tests assert structural presence + data sanity
("heading exists", "review count > 0", "no undefined/NaN in rendered text"). These are
fundamentally different assertion styles — dual-mode tests would be fragile and hard to
maintain.

## What to create

### Directory structure

```
frontend/
  playwright.production.config.ts       — separate config, no webServer, no mock server
  tests/
    production/
      fixtures/
        helpers.ts                      — shared constants, console error monitor, sanity helpers
      home.prod.spec.ts
      search.prod.spec.ts
      game-report.prod.spec.ts
      per-entity-analytics.prod.spec.ts
      genre-tag.prod.spec.ts
      developer.prod.spec.ts
      explore.prod.spec.ts
      new-releases.prod.spec.ts
      compare.prod.spec.ts
      builder.prod.spec.ts
      trends.prod.spec.ts
      navigation.prod.spec.ts
      seo.prod.spec.ts
      accessibility.prod.spec.ts
      api-sanity.prod.spec.ts
```

### `playwright.production.config.ts`

Separate Playwright config for production runs:

- `testDir: './tests/production'`, `testMatch: '**/*.prod.spec.ts'`
- `baseURL` from `PLAYWRIGHT_BASE_URL` — **fail if not set** (no localhost fallback)
- **No `webServer` block** — no mock server, no local Next.js build
- Chromium only by default; env var `PRODUCTION_ALL_BROWSERS=true` adds firefox + webkit + mobile-chrome
- `timeout: 30_000` per test, `expect.timeout: 10_000` (production network latency)
- `retries: 1` (network flakes)
- Reporter: `['html', { outputFolder: 'playwright-report-production', open: 'never' }]` + `['list']`
- `use.trace: 'on-first-retry'`, `use.screenshot: 'only-on-failure'`

### `tests/production/fixtures/helpers.ts`

**Constants:**
```typescript
export const KNOWN_APPIDS = { TF2: 440, DOTA2: 570, CS2: 730 } as const
export const KNOWN_GENRE_SLUG = 'action'
export const KNOWN_TAG_SLUG = 'multiplayer'
export const KNOWN_DEVELOPER_SLUG = 'valve'
```

These are Valve flagship titles — permanent on Steam, always analyzed in SteamPulse.

**Helper functions:**

- `collectConsoleErrors(page)` — attaches `page.on('console')` (severity=error) and
  `page.on('pageerror')` listeners. Returns `{ errors: string[], check: () => void }`.
  `check()` asserts `errors.length === 0`. Every test's `beforeEach` calls this;
  every `afterEach` calls `check()`.

- `assertNoVisibleGarbage(page)` — scans `body.innerText()` for literal `"undefined"`,
  `"NaN"`, `"[object Object]"`, rendered `"null"` (outside code blocks). Fails if found.

- `assertPageLoadsOk(page)` — `main` landmark visible, no error boundary
  (`[data-testid="error-boundary"]`), non-empty `<title>`.

- `assertListHasItems(locator, min=1)` — at least `min` child elements.

- `fetchApiJson(page, path)` — direct `fetch()` via `page.evaluate` against the
  production API base URL. Returns parsed JSON. Used by `api-sanity.prod.spec.ts`.

### `package.json` — add scripts

```json
"test:production": "PLAYWRIGHT_BASE_URL=https://steampulse.io npx playwright test --config playwright.production.config.ts",
"test:production:staging": "PLAYWRIGHT_BASE_URL=https://staging.steampulse.io npx playwright test --config playwright.production.config.ts",
"test:production:report": "npx playwright show-report playwright-report-production"
```

## Test coverage by file

Every test uses `beforeEach` → `collectConsoleErrors(page)` + navigate, `afterEach` →
`check()` + `assertNoVisibleGarbage(page)`.

### `home.prod.spec.ts` — `/`

- Hero search input visible
- Page heading present
- Navbar renders with navigation landmark
- Tag browser section renders with at least one tag
- Typing in search + Enter navigates to `/search?q=...`

### `search.prod.spec.ts` — `/search`

- Game cards appear (> 0)
- Result count text matches `/\d+.*games/i`
- Filter sidebar renders on desktop (genre labels visible)
- Pagination renders (production has enough games)
- Clicking a game card navigates to `/games/{appid}/...`
- `?q=team+fortress` returns results containing "Team Fortress"
- `?genre=action` filters work (returns results)

### `game-report.prod.spec.ts` — `/games/440/team-fortress-2`

- Heading contains "Team Fortress 2"
- All 10 report sections render: verdict, design strengths, gameplay friction,
  audience profile, player wishlist, churn triggers, developer priorities,
  competitive context, genre context, promise gap
- Steam Sentiment label visible
- Tag chips present, link to `/tag/`
- Genre chips present, link to `/genre/`
- Quick stats grid with review count > 0
- Crawl freshness text: `/Crawled \d+[mhd] ago/`
- SteamPulse Analysis zone with analyzed freshness

### `per-entity-analytics.prod.spec.ts` — `/games/440/...`

- Audience overlap shows at least one overlapping game
- Playtime sentiment section renders
- Review velocity trend present
- Top reviews section with at least one review body
- Benchmark ranks present (sentiment_rank, popularity_rank)

### `genre-tag.prod.spec.ts` — `/genre/action`, `/tag/multiplayer`

- Genre page: heading "Action", game cards appear, breadcrumbs
- Tag page: heading "Multiplayer", game cards appear, related tags section
- Game cards link to valid `/games/` URLs

### `developer.prod.spec.ts` — `/developer/valve`, `/publisher/valve`

- Headings contain "Valve"
- At least one game card visible

### `explore.prod.spec.ts` — `/explore`

- Page loads with heading
- Chart section headings render (release volume, sentiment distribution,
  genre share, review velocity, pricing trends, early access, platform,
  engagement depth, feature adoption)
- Granularity toggle buttons present

### `new-releases.prod.spec.ts` — `/new-releases`

- Three lens tabs (released, upcoming, added)
- Released lens: feed grid with at least one card
- Window pills visible (today/week/month/quarter)
- Switching lens updates URL
- Genre filter dropdown present

### `compare.prod.spec.ts` — `/compare?appids=440,730`

- Both game names visible (TF2, CS2)
- Metric rows render
- Leader highlighting present

### `builder.prod.spec.ts` — `/explore?lens=builder`

- Builder lens renders
- Metric chips present
- Chart renders (no empty state)

### `trends.prod.spec.ts` — `/explore?lens=trends`

- Trends segment caption visible
- Genre/tag filter controls present

### `navigation.prod.spec.ts` — multi-page flows

- Home → search → game report (type query, click result, verify game page)
- Game report → tag page (click tag chip)
- Game report → genre page (click genre chip)
- `/trending` loads with heading
- `/pro` loads with waitlist/pricing content

### `seo.prod.spec.ts` — various

- `GET /robots.txt` returns 200, contains "sitemap" and "Disallow"
- `GET /sitemap.xml` returns 200, contains `<urlset` and `steampulse.io`
- Home page: OG title containing "SteamPulse", canonical href
- Game page: OG image, canonical with `/games/440/`, JSON-LD `@type`
- Genre page: OG title containing "Action" and "SteamPulse"

### `accessibility.prod.spec.ts` — various

- All images have alt text (home page)
- `main` landmark visible (game report)
- Form inputs have accessible labels (search page)
- Pagination has navigation role
- Breadcrumb navigation present

### `api-sanity.prod.spec.ts` — direct API response shape validation

Uses `fetchApiJson()` helper, no page navigation:

- `GET /api/games` → `{ total: number > 0, games: array.length > 0 }`
- `GET /api/games/440/report` → `{ status: 'available', report: { game_name, one_liner, design_strengths, audience_profile, ... } }`
- `GET /api/genres` → array with at least 3 items, each `{ name, slug, game_count > 0 }`
- `GET /api/tags/top` → array with items
- `GET /api/games/440/review-stats` → `{ timeline: array, playtime_buckets: array }`
- `GET /api/games/440/benchmarks` → `{ sentiment_rank, popularity_rank, cohort_size }`
- `GET /api/new-releases/released` → `{ items: array, total: number }`
- `GET /health` → 200

## Data sanity principles

- Use **soft floors**: `review_count > 10000` for TF2, not exact numbers
- Lists: `length > 0`
- Timestamps: parseable as Date, between 2020 and now
- Prices: non-negative numbers
- No `"undefined"` or `"NaN"` in rendered text
- Console errors = test failure

## Running

```bash
# Against production
cd frontend && npm run test:production

# Against staging
cd frontend && npm run test:production:staging

# View HTML report
cd frontend && npm run test:production:report

# Full browser matrix
PRODUCTION_ALL_BROWSERS=true npm run test:production
```
