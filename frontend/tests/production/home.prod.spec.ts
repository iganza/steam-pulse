import { test, expect } from '@playwright/test'
import { collectConsoleErrors, assertNoVisibleGarbage, assertPageLoadsOk } from './fixtures/helpers'

test.describe('Home page — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
    await page.goto('/')
  })

  test.afterEach(async ({ page }) => {
    await assertNoVisibleGarbage(page)
    consoleCheck.check()
  })

  test('page loads without errors', async ({ page }) => {
    await assertPageLoadsOk(page)
  })

  test('hero search input is visible', async ({ page }) => {
    await expect(page.getByPlaceholder(/search.*steam games/i)).toBeVisible()
  })

  test('page heading is present', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /discover steam games/i })).toBeVisible()
  })

  test('navbar is visible with navigation landmark', async ({ page }) => {
    await expect(page.getByRole('navigation', { name: /main navigation/i })).toBeVisible()
  })

  test('Browse by Tag section renders with tags', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /browse by tag/i })).toBeVisible()
    // At least one tag link should be visible in the tag browser
    const tagLinks = page.locator('a[href^="/tag/"], a[href^="/genre/"]')
    expect(await tagLinks.count()).toBeGreaterThan(0)
  })

  test('search navigates to /search with query param', async ({ page }) => {
    const input = page.getByPlaceholder(/search.*steam games/i)
    await input.fill('portal')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/search\?q=portal/)
  })
})
