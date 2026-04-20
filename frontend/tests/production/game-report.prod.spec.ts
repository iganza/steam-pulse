import { test, expect } from '@playwright/test'
import {
  collectConsoleErrors,
  assertNoVisibleGarbage,
  assertPageLoadsOk,
  KNOWN_GAME_PATHS,
  fetchApiJson,
  KNOWN_APPIDS,
} from './fixtures/helpers'

test.describe('Game page — always present', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
    await page.goto(KNOWN_GAME_PATHS.TF2)
  })

  test.afterEach(async ({ page }) => {
    await assertNoVisibleGarbage(page)
    consoleCheck.check()
  })

  test('page loads with game report heading', async ({ page }) => {
    await assertPageLoadsOk(page)
    // Game name is in the hero image; the page heading says "Game Report"
    // and the breadcrumbs contain the game name
    await expect(page.getByRole('heading').first()).toBeVisible()
    const title = await page.title()
    expect(title).toMatch(/team fortress 2/i)
  })

  test('Quick Stats grid renders', async ({ page }) => {
    await expect(page.getByText('Quick Stats').first()).toBeVisible()
  })

  test('breadcrumbs are present', async ({ page }) => {
    await expect(page.getByRole('navigation', { name: /breadcrumb/i })).toBeVisible()
    await expect(page.getByRole('link', { name: /home/i })).toBeVisible()
  })

  test('Steam Sentiment label is visible', async ({ page }) => {
    await expect(page.getByText('Steam Sentiment')).toBeVisible()
  })

  test('Steam review_score_desc chip renders', async ({ page }) => {
    await expect(page.getByText(/Steam ·/i)).toBeVisible()
  })

  test('tag chips are present and link to /tag/', async ({ page }) => {
    const anyTagLink = page.locator('a[href^="/tag/"]').first()
    await expect(anyTagLink).toBeVisible()
  })

  test('genre chips are present and link to /genre/', async ({ page }) => {
    const genreLink = page.locator('a[href^="/genre/"]').first()
    await expect(genreLink).toBeVisible()
  })

})

test.describe('Game page — with report (analyzed game)', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>
  let hasReport = false

  test.beforeAll(async ({ browser }) => {
    // Check if TF2 has a report before running these tests
    const page = await browser.newPage()
    await page.goto(KNOWN_GAME_PATHS.TF2)
    const resp = await fetchApiJson(page, `/api/games/${KNOWN_APPIDS.TF2}/report`)
    hasReport = resp.body?.status === 'available'
    await page.close()
  })

  test.beforeEach(async ({ page }) => {
    test.skip(!hasReport, 'TF2 report not available — skipping report-dependent tests')
    consoleCheck = collectConsoleErrors(page)
    await page.goto(KNOWN_GAME_PATHS.TF2)
  })

  test.afterEach(async ({ page }) => {
    if (hasReport) {
      await assertNoVisibleGarbage(page)
      consoleCheck.check()
    }
  })

  test('all report sections render', async ({ page }) => {
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

  test('crawl freshness text is present', async ({ page }) => {
    // toContainText (not toHaveText) so the optional "Refresh queued — …"
    // suffix that appears past 90d doesn't flake the assertion.
    await expect(page.getByTestId('steam-facts-crawled')).toContainText(
      /Data current as of .+\. We re-crawl reviews and metadata every 14 days\./,
    )
  })

  test('SteamPulse Analysis zone with analyzed freshness', async ({ page }) => {
    await expect(page.getByText(/SteamPulse Analysis/i)).toBeVisible()
    await expect(page.getByText(/Analyzed \d+[mhd] ago/)).toBeVisible()
  })

  test('sentiment timeline chart renders', async ({ page }) => {
    await expect(page.getByTestId('sentiment-timeline')).toBeVisible()
  })

  test('playtime chart renders', async ({ page }) => {
    await expect(page.getByTestId('playtime-chart')).toBeVisible()
  })

  test('score context sentence visible', async ({ page }) => {
    await expect(page.getByTestId('score-context')).toBeVisible()
  })

  test('review velocity card shows reviews/day', async ({ page }) => {
    await expect(page.getByText(/\/day/)).toBeVisible()
  })

  test('compare deep-link is present', async ({ page }) => {
    const link = page.getByTestId('game-compare-deeplink')
    await link.scrollIntoViewIfNeeded()
    await expect(link).toBeVisible({ timeout: 15_000 })
    await expect(link).toHaveAttribute('href', /\/compare\?appids=440/)
  })
})
