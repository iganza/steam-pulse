# SteamPulse — Playwright E2E Test Suite

## Overview

Add a full Playwright end-to-end test suite to the SteamPulse frontend. This covers regression testing for all pages, user flows, component behaviour, and API integration. Tests must not be included in any production build or deployment artifact.

**Tech stack context:**
- Next.js 16 App Router, React 19, TypeScript 5, TailwindCSS 4
- No existing test infrastructure — install everything from scratch
- Backend is FastAPI; all API calls must be mocked in tests (no live backend required)
- Deployment: Railway (frontend), AWS Lambda (API). Tests run locally and in CI.

---

## Part 1: Install and Configure Playwright

### Installation

```bash
cd frontend
npm init playwright@latest
```

Select:
- TypeScript
- `tests/` as the test directory
- **No** GitHub Actions file (we'll write our own)
- Install Playwright browsers

Then install the extra dependency needed for API mocking:
```bash
npm install --save-dev @playwright/test
```

### `playwright.config.ts`

```typescript
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['html', { open: 'never' }],
    ['list'],
  ],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
    {
      name: 'mobile-chrome',
      use: { ...devices['Pixel 5'] },
    },
  ],
  webServer: {
    command: 'npm run build && npm run start',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
```

Key points:
- `PLAYWRIGHT_BASE_URL` env var allows pointing tests at staging or prod (`https://staging.steampulse.io`)
- `webServer` auto-starts the Next.js production build for local runs
- Retries on CI (flake tolerance)
- Four browser projects: Chromium, Firefox, WebKit, Pixel 5 mobile

### Add test scripts to `package.json`

```json
{
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "test:e2e": "playwright test",
    "test:e2e:ui": "playwright test --ui",
    "test:e2e:headed": "playwright test --headed",
    "test:e2e:report": "playwright show-report"
  }
}
```

### `.gitignore` additions (append to existing)

```
# Playwright
/frontend/test-results/
/frontend/playwright-report/
/frontend/blob-report/
/frontend/.playwright/
```

### Exclude from Next.js build

In `next.config.ts`, ensure the `tests/` directory is excluded from the TypeScript compilation and build:

```typescript
const nextConfig = {
  // ...existing config...
  experimental: {
    // ensure test files are never bundled
  },
}
```

Also add to `tsconfig.json` — in the `exclude` array:
```json
{
  "exclude": ["node_modules", "tests", "playwright.config.ts"]
}
```

---

## Part 2: Test Fixtures and Mock Data

Create `tests/fixtures/` with shared mock data used across all tests.

### `tests/fixtures/mock-data.ts`

```typescript
export const MOCK_GAME_ANALYZED = {
  appid: 440,
  name: 'Team Fortress 2',
  slug: 'team-fortress-2',
  developer: 'Valve',
  header_image: 'https://cdn.akamai.steamstatic.com/steam/apps/440/header.jpg',
  review_count: 142389,
  positive_pct: 0.967,
  hidden_gem_score: 12,
  sentiment_score: 87,
  price_usd: null,
  is_free: true,
  genres: ['Action', 'Free to Play'],
  tags: ['FPS', 'Multiplayer', 'Shooter', 'Team-Based'],
  release_date: '2007-10-10',
  short_desc: 'Nine distinct classes provide a broad range of tactical abilities and personalities.',
}

export const MOCK_GAME_UNANALYZED = {
  appid: 9999999,
  name: 'Obscure Indie Game',
  slug: 'obscure-indie-game',
  developer: 'Small Studio',
  header_image: 'https://cdn.akamai.steamstatic.com/steam/apps/9999999/header.jpg',
  review_count: 42,
  positive_pct: 0.80,
  hidden_gem_score: null,
  sentiment_score: null,
  price_usd: 9.99,
  is_free: false,
  genres: ['Indie', 'Adventure'],
  tags: ['Indie', 'Adventure', 'Singleplayer'],
  release_date: '2024-06-01',
  short_desc: 'A small indie adventure game.',
}

export const MOCK_REPORT = {
  game_name: 'Team Fortress 2',
  appid: 440,
  total_reviews_analyzed: 142389,
  overall_sentiment: 'Overwhelmingly Positive',
  sentiment_score: 87,
  sentiment_trend: 'stable',
  sentiment_trend_note: 'Sentiment has remained consistent over the past 6 months.',
  one_liner: 'A timeless class-based shooter that rewards teamwork and creativity.',
  audience_profile: {
    primary: 'Competitive FPS fans',
    secondary: 'Casual players',
    playtime_range: '100–500 hours',
    tone: 'Enthusiastic long-term fans',
  },
  design_strengths: ['Class diversity', 'Team dynamics', 'Free-to-play accessibility'],
  gameplay_friction: ['Matchmaking quality', 'Bot problem in casual mode'],
  player_wishlist: ['Better anti-cheat', 'New maps', 'Ranked mode improvements'],
  churn_triggers: ['Toxic players', 'Unbalanced teams'],
  dev_priorities: [
    { priority: 'Bot/cheat mitigation', impact: 'high', frequency: 0.34 },
    { priority: 'Matchmaking improvements', impact: 'medium', frequency: 0.21 },
  ],
  competitive_context: [
    { name: 'Overwatch 2', appid: 2357570, similarity: 'high' },
  ],
  genre_context: 'Dominates the class-based shooter genre. No direct competitor matches its longevity.',
  hidden_gem_score: 12,
  last_analyzed: '2025-03-01T00:00:00Z',
}

export const MOCK_GENRES = [
  { id: 1, name: 'Action', slug: 'action', game_count: 12400, analyzed_count: 980 },
  { id: 2, name: 'Indie', slug: 'indie', game_count: 28000, analyzed_count: 1200 },
  { id: 3, name: 'RPG', slug: 'rpg', game_count: 8200, analyzed_count: 740 },
  { id: 4, name: 'Strategy', slug: 'strategy', game_count: 6100, analyzed_count: 510 },
]

export const MOCK_TAGS = [
  { id: 1, name: 'Multiplayer', slug: 'multiplayer', game_count: 8900 },
  { id: 2, name: 'Singleplayer', slug: 'singleplayer', game_count: 42000 },
  { id: 3, name: 'Roguelike', slug: 'roguelike', game_count: 3100 },
  { id: 4, name: 'Open World', slug: 'open-world', game_count: 2200 },
]

export const MOCK_GAMES_LIST = {
  total: 2,
  games: [MOCK_GAME_ANALYZED, MOCK_GAME_UNANALYZED],
}
```

### `tests/fixtures/api-mock.ts`

Create a reusable fixture that mocks all FastAPI routes. Every test uses this — no test should hit a real backend.

```typescript
import { Page } from '@playwright/test'
import {
  MOCK_GAMES_LIST, MOCK_GENRES, MOCK_TAGS,
  MOCK_REPORT, MOCK_GAME_ANALYZED, MOCK_GAME_UNANALYZED,
} from './mock-data'

export async function mockAllApiRoutes(page: Page) {
  // Games list
  await page.route('**/api/games**', route =>
    route.fulfill({ json: MOCK_GAMES_LIST })
  )

  // Full report for analyzed game
  await page.route(`**/api/games/440/report`, route =>
    route.fulfill({
      json: {
        status: 'available',
        report: MOCK_REPORT,
        game: {
          short_desc: MOCK_GAME_ANALYZED.short_desc,
          developer: MOCK_GAME_ANALYZED.developer,
          release_date: MOCK_GAME_ANALYZED.release_date,
          price_usd: null,
          is_free: true,
        },
      },
    })
  )

  // No report for unanalyzed game
  await page.route(`**/api/games/9999999/report`, route =>
    route.fulfill({
      json: {
        status: 'not_available',
        review_count: 42,
        threshold: 500,
        game: {
          short_desc: MOCK_GAME_UNANALYZED.short_desc,
          developer: MOCK_GAME_UNANALYZED.developer,
          release_date: MOCK_GAME_UNANALYZED.release_date,
          price_usd: 9.99,
          is_free: false,
        },
      },
    })
  )

  // Genres
  await page.route('**/api/genres**', route =>
    route.fulfill({ json: MOCK_GENRES })
  )

  // Tags
  await page.route('**/api/tags/**', route =>
    route.fulfill({ json: MOCK_TAGS })
  )

  // Preview (fallback)
  await page.route('**/api/preview', route =>
    route.fulfill({
      json: {
        game_name: MOCK_GAME_ANALYZED.name,
        overall_sentiment: 'Overwhelmingly Positive',
        sentiment_score: 87,
        one_liner: MOCK_REPORT.one_liner,
      },
    })
  )
}
```

---

## Part 3: Test Files

### `tests/home.spec.ts`

Test the home page — search hero, discovery rows, genre grid, tag cloud, navigation.

```typescript
import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('Home page', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/')
  })

  test('renders search hero with placeholder', async ({ page }) => {
    const input = page.getByPlaceholder(/search.*steam games/i)
    await expect(input).toBeVisible()
  })

  test('typing in search navigates to /search with q param', async ({ page }) => {
    await page.getByPlaceholder(/search.*steam games/i).fill('hollow knight')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/search\?q=hollow\+knight|\/search\?q=hollow%20knight/)
  })

  test('discovery rows are present', async ({ page }) => {
    await expect(page.getByText(/most popular/i)).toBeVisible()
    await expect(page.getByText(/hidden gems/i)).toBeVisible()
    await expect(page.getByText(/new on steam/i)).toBeVisible()
  })

  test('genre grid renders genre cards', async ({ page }) => {
    await expect(page.getByText('Action')).toBeVisible()
    await expect(page.getByText('Indie')).toBeVisible()
  })

  test('clicking a genre card navigates to genre page', async ({ page }) => {
    await page.getByText('Action').first().click()
    await expect(page).toHaveURL(/\/genre\/action/)
  })

  test('tag cloud is present', async ({ page }) => {
    await expect(page.getByText('Multiplayer')).toBeVisible()
  })

  test('navbar is visible', async ({ page }) => {
    await expect(page.getByRole('navigation')).toBeVisible()
  })

  test('no paywall or unlock buttons present', async ({ page }) => {
    await expect(page.getByText(/unlock/i)).not.toBeVisible()
    await expect(page.getByText(/\$7/)).not.toBeVisible()
    await expect(page.getByText(/\$15/)).not.toBeVisible()
  })
})
```

### `tests/navbar.spec.ts`

Test the persistent navigation bar across pages.

```typescript
import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('Navbar', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
  })

  test('is present on home page', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('navigation')).toBeVisible()
  })

  test('is present on search page', async ({ page }) => {
    await page.goto('/search')
    await expect(page.getByRole('navigation')).toBeVisible()
  })

  test('is present on game report page', async ({ page }) => {
    await page.goto('/games/440/team-fortress-2')
    await expect(page.getByRole('navigation')).toBeVisible()
  })

  test('logo links to home', async ({ page }) => {
    await page.goto('/search')
    await page.getByRole('link', { name: /steampulse/i }).first().click()
    await expect(page).toHaveURL('/')
  })

  test('Browse dropdown opens and shows genres', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /browse/i }).click()
    await expect(page.getByText('Action')).toBeVisible()
  })

  test('"For Developers" links to /pro', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('link', { name: /for developers/i }).click()
    await expect(page).toHaveURL('/pro')
  })

  test('mobile hamburger menu opens on small viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/')
    const hamburger = page.getByRole('button', { name: /menu|hamburger|open/i })
    await hamburger.click()
    await expect(page.getByRole('link', { name: /trending/i })).toBeVisible()
  })
})
```

### `tests/search.spec.ts`

Test the search and filter page — the most complex page.

```typescript
import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('Search page', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/search')
  })

  test('shows game cards in grid by default', async ({ page }) => {
    await expect(page.getByText('Team Fortress 2')).toBeVisible()
  })

  test('shows result count', async ({ page }) => {
    await expect(page.getByText(/\d+ games/i)).toBeVisible()
  })

  test('filter sidebar is present', async ({ page }) => {
    await expect(page.getByText(/genre/i)).toBeVisible()
    await expect(page.getByText(/sentiment/i)).toBeVisible()
  })

  test('searching by text updates URL', async ({ page }) => {
    await page.getByRole('textbox', { name: /search/i }).fill('hollow knight')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/q=hollow/)
  })

  test('selecting a genre filter updates URL', async ({ page }) => {
    await page.getByLabel('Action').check()
    await expect(page).toHaveURL(/genre=action/)
  })

  test('active filter chip appears after selecting genre', async ({ page }) => {
    await page.getByLabel('Action').check()
    await expect(page.getByText(/action.*×|× action/i)).toBeVisible()
  })

  test('"Clear all filters" resets filters', async ({ page }) => {
    await page.getByLabel('Action').check()
    await page.getByRole('button', { name: /clear all/i }).click()
    await expect(page).not.toHaveURL(/genre=action/)
  })

  test('switching to list view shows table', async ({ page }) => {
    await page.getByRole('button', { name: /list view|table/i }).click()
    await expect(page.getByRole('table')).toBeVisible()
  })

  test('list view preference is remembered on reload', async ({ page }) => {
    await page.getByRole('button', { name: /list view|table/i }).click()
    await page.reload()
    await expect(page.getByRole('table')).toBeVisible()
  })

  test('clicking a game card navigates to game report', async ({ page }) => {
    await page.getByText('Team Fortress 2').first().click()
    await expect(page).toHaveURL(/\/games\/440\//)
  })

  test('empty state shown when no results', async ({ page }) => {
    await page.route('**/api/games**', route =>
      route.fulfill({ json: { total: 0, games: [] } })
    )
    await page.goto('/search?q=xyznonexistent')
    await expect(page.getByText(/no games match/i)).toBeVisible()
    await expect(page.getByRole('button', { name: /clear filters/i })).toBeVisible()
  })

  test('pagination controls are present', async ({ page }) => {
    await expect(page.getByRole('navigation', { name: /pagination/i })).toBeVisible()
  })

  test('URL state survives browser back/forward', async ({ page }) => {
    await page.getByLabel('Action').check()
    await page.getByText('Team Fortress 2').first().click()
    await page.goBack()
    await expect(page).toHaveURL(/genre=action/)
  })
})
```

### `tests/game-report.spec.ts`

Test the game report page for both analyzed and unanalyzed games.

```typescript
import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('Game report page — analyzed game', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/440/team-fortress-2')
  })

  test('renders game name in hero', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Team Fortress 2' })).toBeVisible()
  })

  test('renders About section with short description', async ({ page }) => {
    await expect(page.getByText(/nine distinct classes/i)).toBeVisible()
  })

  test('renders all 12 report sections', async ({ page }) => {
    const sections = [
      /the verdict/i,
      /design strengths/i,
      /gameplay friction/i,
      /audience profile/i,
      /player wishlist/i,
      /churn triggers/i,
      /developer priorities/i,
      /competitive context/i,
      /genre context/i,
    ]
    for (const section of sections) {
      await expect(page.getByText(section)).toBeVisible()
    }
  })

  test('no blur overlay or lock icons', async ({ page }) => {
    await expect(page.locator('.premium-blur-content')).not.toBeAttached()
    await expect(page.locator('.premium-overlay')).not.toBeAttached()
  })

  test('no unlock or pricing CTAs', async ({ page }) => {
    await expect(page.getByText(/unlock/i)).not.toBeVisible()
    await expect(page.getByText(/\$7/)).not.toBeVisible()
  })

  test('sentiment score is shown', async ({ page }) => {
    await expect(page.getByText('87')).toBeVisible()
  })

  test('tag chips are rendered and link to /tag/', async ({ page }) => {
    const tagLink = page.getByRole('link', { name: /fps|multiplayer|shooter/i }).first()
    await expect(tagLink).toBeVisible()
    await expect(tagLink).toHaveAttribute('href', /\/tag\//)
  })

  test('developer Pro CTA is present at bottom', async ({ page }) => {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    await expect(page.getByText(/genre intelligence.*pro|pro.*genre intelligence/i)).toBeVisible()
  })

  test('breadcrumbs are present', async ({ page }) => {
    await expect(page.getByRole('navigation', { name: /breadcrumb/i })).toBeVisible()
    await expect(page.getByRole('link', { name: /home/i })).toBeVisible()
  })

  test('"Related Games" rows are present', async ({ page }) => {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    await expect(page.getByText(/more in|you might also like/i)).toBeVisible()
  })
})

test.describe('Game report page — unanalyzed game', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/9999999/obscure-indie-game')
  })

  test('shows metadata without analysis sections', async ({ page }) => {
    await expect(page.getByText('Obscure Indie Game')).toBeVisible()
    await expect(page.getByText(/the verdict/i)).not.toBeVisible()
  })

  test('shows review count progress bar toward threshold', async ({ page }) => {
    await expect(page.getByText(/42|reviews needed|threshold/i)).toBeVisible()
  })

  test('shows "analysis not yet available" message', async ({ page }) => {
    await expect(page.getByText(/analysis.*available|not yet analyzed/i)).toBeVisible()
  })

  test('short description is shown', async ({ page }) => {
    await expect(page.getByText(/small indie adventure/i)).toBeVisible()
  })
})
```

### `tests/genre-tag-developer.spec.ts`

Test genre, tag, and developer index pages.

```typescript
import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('Genre page', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/genre/action')
  })

  test('renders genre name as heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /action/i })).toBeVisible()
  })

  test('shows game count', async ({ page }) => {
    await expect(page.getByText(/\d+ games/i)).toBeVisible()
  })

  test('shows game cards', async ({ page }) => {
    await expect(page.getByText('Team Fortress 2')).toBeVisible()
  })

  test('breadcrumbs include genre', async ({ page }) => {
    await expect(page.getByText(/home/i)).toBeVisible()
    await expect(page.getByText(/action/i)).toBeVisible()
  })
})

test.describe('Tag page', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/tag/multiplayer')
  })

  test('renders tag name as heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /multiplayer/i })).toBeVisible()
  })

  test('shows related tags', async ({ page }) => {
    await expect(page.getByText(/singleplayer|roguelike/i)).toBeVisible()
  })
})

test.describe('Developer page', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/developer/valve')
  })

  test('renders developer name', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /valve/i })).toBeVisible()
  })

  test('shows developer games', async ({ page }) => {
    await expect(page.getByText('Team Fortress 2')).toBeVisible()
  })

  test('shows Pro CTA for developer intelligence', async ({ page }) => {
    await expect(page.getByText(/developer intelligence.*pro|competitive analysis/i)).toBeVisible()
  })
})
```

### `tests/navigation-flows.spec.ts`

Test complete user journeys across multiple pages.

```typescript
import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('User journeys', () => {
  test('home → search → game report', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/')
    await page.getByPlaceholder(/search.*steam games/i).fill('team fortress')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/search/)
    await page.getByText('Team Fortress 2').first().click()
    await expect(page).toHaveURL(/\/games\/440\//)
    await expect(page.getByRole('heading', { name: 'Team Fortress 2' })).toBeVisible()
  })

  test('home → browse genre → game report', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/')
    await page.getByText('Action').first().click()
    await expect(page).toHaveURL(/\/genre\/action/)
    await page.getByText('Team Fortress 2').first().click()
    await expect(page).toHaveURL(/\/games\/440\//)
  })

  test('game report tag chip → tag page', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/440/team-fortress-2')
    await page.getByRole('link', { name: /fps|multiplayer/i }).first().click()
    await expect(page).toHaveURL(/\/tag\//)
  })

  test('game report genre chip → genre page', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/440/team-fortress-2')
    await page.getByRole('link', { name: /action/i }).first().click()
    await expect(page).toHaveURL(/\/genre\/action/)
  })

  test('/trending page loads', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/trending')
    await expect(page.getByRole('heading', { name: /trending/i })).toBeVisible()
  })

  test('/new-releases page loads with tabs', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/new-releases')
    await expect(page.getByRole('tab', { name: /new on steam/i })).toBeVisible()
    await expect(page.getByRole('tab', { name: /just analyzed/i })).toBeVisible()
  })

  test('/pro page loads as stub', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/pro')
    await expect(page.getByText(/coming soon|pro features|developers/i)).toBeVisible()
  })
})
```

### `tests/accessibility.spec.ts`

Basic accessibility checks — no full axe audit, but critical patterns.

```typescript
import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('Accessibility basics', () => {
  test('all images have alt text', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/')
    const imagesWithoutAlt = await page.$$eval(
      'img:not([alt])',
      imgs => imgs.length
    )
    expect(imagesWithoutAlt).toBe(0)
  })

  test('game report page has a main landmark', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/440/team-fortress-2')
    await expect(page.getByRole('main')).toBeVisible()
  })

  test('search page filter checkboxes have labels', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/search')
    const unlabelledCheckboxes = await page.$$eval(
      'input[type="checkbox"]:not([aria-label]):not([id])',
      inputs => inputs.filter(i => !document.querySelector(`label[for="${i.id}"]`)).length
    )
    expect(unlabelledCheckboxes).toBe(0)
  })

  test('pagination has navigation role', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/search')
    await expect(page.getByRole('navigation', { name: /pagination/i })).toBeVisible()
  })
})
```

---

## Part 4: CI Integration

### `.github/workflows/e2e.yml`

Create this file. It runs on every PR and push to `main`/`staging`:

```yaml
name: E2E Tests

on:
  push:
    branches: [main, staging]
  pull_request:
    branches: [main, staging]

jobs:
  test:
    timeout-minutes: 30
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        working-directory: frontend
        run: npm ci

      - name: Install Playwright browsers
        working-directory: frontend
        run: npx playwright install --with-deps chromium

      - name: Build Next.js
        working-directory: frontend
        run: npm run build
        env:
          NEXT_PUBLIC_API_URL: ''

      - name: Run Playwright tests
        working-directory: frontend
        run: npx playwright test --project=chromium

      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: playwright-report
          path: frontend/playwright-report/
          retention-days: 7
```

Notes:
- Only runs Chromium in CI (fast). Full browser matrix runs locally.
- Uploads HTML report as an artifact on failure — downloadable from GitHub Actions.
- `NEXT_PUBLIC_API_URL` is left blank so all API calls are relative (then mocked by Playwright's route interceptor).

---

## Part 5: Running Against Staging / Production

Because `playwright.config.ts` reads `PLAYWRIGHT_BASE_URL`, you can point tests at any environment:

```bash
# Run against local dev server
npm run test:e2e

# Run against staging
PLAYWRIGHT_BASE_URL=https://staging.steampulse.io npm run test:e2e

# Run against production (read-only tests only — flag WIP tests)
PLAYWRIGHT_BASE_URL=https://steampulse.io npm run test:e2e
```

**Important:** When running against staging/prod, API mocks are NOT used (real network). The tests must still pass because they test rendered HTML, not mock data. Most tests will work as-is — they search for structural elements (headings, nav, sections) that exist regardless of which games are returned. Any test that checks for specific game names (e.g. "Team Fortress 2") should be tagged `@mock-only` and skipped in non-local runs.

Add this pattern to tests that should only run with mocks:
```typescript
test.skip(!!process.env.PLAYWRIGHT_BASE_URL, 'Skipped in remote environment — requires mock data')
```

---

## Definition of Done

- [ ] `playwright.config.ts` created with 4 browser projects + `webServer` config
- [ ] `package.json` has `test:e2e`, `test:e2e:ui`, `test:e2e:headed`, `test:e2e:report` scripts
- [ ] `tests/` excluded from `tsconfig.json` and Next.js build
- [ ] `tests/fixtures/mock-data.ts` with `MOCK_GAME_ANALYZED`, `MOCK_GAME_UNANALYZED`, `MOCK_REPORT`, `MOCK_GENRES`, `MOCK_TAGS`
- [ ] `tests/fixtures/api-mock.ts` with `mockAllApiRoutes()` covering all 6 API endpoints
- [ ] `tests/home.spec.ts` — 9 tests
- [ ] `tests/navbar.spec.ts` — 7 tests
- [ ] `tests/search.spec.ts` — 12 tests (including empty state, list/grid toggle, URL persistence)
- [ ] `tests/game-report.spec.ts` — analyzed + unanalyzed game cases
- [ ] `tests/genre-tag-developer.spec.ts` — genre, tag, developer pages
- [ ] `tests/navigation-flows.spec.ts` — 7 full user journeys
- [ ] `tests/accessibility.spec.ts` — basic a11y checks
- [ ] `.github/workflows/e2e.yml` runs on PR to main/staging
- [ ] `npx playwright test` passes locally with `npm run build && npm run start`
- [ ] `tests/` and `playwright-report/` in `.gitignore`
