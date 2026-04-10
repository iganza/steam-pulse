import { test, expect } from '@playwright/test'
import { collectConsoleErrors, assertNoVisibleGarbage, assertPageLoadsOk } from './fixtures/helpers'

test.describe('Search page — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
    await page.goto('/search')
  })

  test.afterEach(async ({ page }) => {
    await assertNoVisibleGarbage(page)
    consoleCheck.check()
  })

  test('page loads with game cards', async ({ page }) => {
    await assertPageLoadsOk(page)
    // Games load via client-side fetch — wait for at least one to appear
    const firstGame = page.locator('a[href^="/games/"]').first()
    await expect(firstGame).toBeVisible({ timeout: 15_000 })
  })

  test('result count is displayed', async ({ page }) => {
    await expect(page.getByText(/\d+.*games/i).first()).toBeVisible()
  })

  test('filter sidebar renders on desktop', async ({ page, isMobile }) => {
    test.skip(isMobile, 'Filter sidebar is desktop-only')
    await expect(page.getByText(/genre/i).first()).toBeVisible()
  })

  test('pagination is present', async ({ page }) => {
    await expect(page.getByRole('navigation', { name: /pagination/i })).toBeVisible()
  })

  test('clicking a game card navigates to game page', async ({ page }) => {
    const firstGame = page.locator('a[href^="/games/"]').first()
    await firstGame.click()
    await expect(page).toHaveURL(/\/games\/\d+\//)
  })

  test('text search returns relevant results', async ({ page }) => {
    await page.goto('/search?q=team+fortress')
    await expect(page.locator('a[href^="/games/"]').first()).toBeVisible({ timeout: 15_000 })
  })

  test('genre filter returns results', async ({ page }) => {
    await page.goto('/search?genre=action')
    await expect(page.locator('a[href^="/games/"]').first()).toBeVisible({ timeout: 15_000 })
  })
})
