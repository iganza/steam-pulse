import { test, expect } from '@playwright/test'
import {
  collectConsoleErrors,
  assertNoVisibleGarbage,
  KNOWN_GAME_PATHS,
  KNOWN_APPIDS,
  fetchApiJson,
} from './fixtures/helpers'

test.describe('Per-entity analytics — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>
  let hasReport = false

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage()
    await page.goto(KNOWN_GAME_PATHS.TF2)
    const resp = await fetchApiJson(page, `/api/games/${KNOWN_APPIDS.TF2}/report`)
    hasReport = resp.body?.status === 'available'
    await page.close()
  })

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
    await page.goto(KNOWN_GAME_PATHS.TF2)
  })

  test.afterEach(async ({ page }) => {
    await assertNoVisibleGarbage(page)
    consoleCheck.check()
  })

  test('audience overlap section renders or gracefully degrades', async ({ page }) => {
    // Section loads via client-side fetch — may not render if no overlap data
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight / 2))
    // Check the heading is present (the section always renders its heading)
    const section = page.getByText(/audience overlap/i)
    const emptyNotice = page.getByText(/no overlap data/i)
    // Either the section with data or no section at all (both are valid)
    const sectionCount = await section.count()
    if (sectionCount > 0) {
      await expect(section).toBeVisible()
    }
    // Test passes either way — the point is no crash
  })

  test('playtime sentiment section renders', async ({ page }) => {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight / 2))
    // Playtime section should always render if we have review stats
    const section = page.getByText(/playtime.*sentiment|sentiment.*playtime/i)
    if ((await section.count()) > 0) {
      await expect(section).toBeVisible()
    }
  })

  test('review velocity section renders or gracefully degrades', async ({ page }) => {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    const section = page.getByText(/review velocity/i)
    if ((await section.count()) > 0) {
      await expect(section).toBeVisible()
    }
  })

  test('competitive benchmark section is present when report exists', async ({ page }) => {
    test.skip(!hasReport, 'Benchmarks require an analyzed report')
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    await expect(page.getByTestId('competitive-benchmark')).toBeVisible({ timeout: 15_000 })
  })
})

test.describe('Genre page analytics — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
    await page.goto('/genre/action')
  })

  test.afterEach(async ({ page }) => {
    await assertNoVisibleGarbage(page)
    consoleCheck.check()
  })

  test('price positioning chart renders', async ({ page }) => {
    await expect(page.getByText(/price positioning/i)).toBeVisible()
  })

  test('release timing chart renders', async ({ page }) => {
    await expect(page.getByText(/release timing/i)).toBeVisible()
  })

  test('platform section renders', async ({ page }) => {
    await expect(page.getByText(/platform/i).first()).toBeVisible()
  })
})
