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
    const input = page.getByPlaceholder(/search.*steam games/i)
    await input.fill('hollow knight')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/search\?q=hollow/)
  })

  test('page heading is present', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /steam, decoded/i })).toBeVisible()
  })

  test('proof bar shows game count', async ({ page }) => {
    await expect(page.getByText(/games tracked/i)).toBeVisible()
  })

  test('intelligence cards section is visible', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /what you get/i })).toBeVisible()
  })

  test('for developers section is visible', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /built for the people who make games/i })).toBeVisible()
  })

  test('footer CTA is visible', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /free to explore/i })).toBeVisible()
  })

  test('showcase tabs switch content', async ({ page }) => {
    const tablist = page.getByRole('tablist', { name: /showcase/i })
    await expect(tablist).toBeVisible()
    const tabs = tablist.getByRole('tab')
    const count = await tabs.count()
    expect(count).toBeGreaterThanOrEqual(2)
    // Click second tab and verify it becomes selected
    await tabs.nth(1).click()
    await expect(tabs.nth(1)).toHaveAttribute('aria-selected', 'true')
    await expect(tabs.nth(0)).toHaveAttribute('aria-selected', 'false')
  })

  test('navbar Browse dropdown opens and shows genres', async ({ page, isMobile }) => {
    test.skip(isMobile, 'Browse dropdown is desktop-only — mobile uses hamburger menu')
    await page.getByRole('button', { name: /browse/i }).click()
    // Scope to the dropdown link to avoid strict-mode hits from genre grid
    await expect(page.getByRole('link', { name: /^Action/ }).first()).toBeVisible()
  })

  test('clicking a browse genre navigates to genre page', async ({ page, isMobile }) => {
    test.skip(isMobile, 'Browse dropdown is desktop-only — mobile uses hamburger menu')
    await page.getByRole('button', { name: /browse/i }).click()
    await page.getByRole('link', { name: /^Action/ }).first().click()
    await expect(page).toHaveURL(/\/genre\/action/)
  })

  test('navbar is visible', async ({ page }) => {
    await expect(page.getByRole('navigation', { name: /main navigation/i })).toBeVisible()
  })

  test('no paywall or unlock buttons present', async ({ page }) => {
    await expect(page.getByText(/unlock/i)).not.toBeVisible()
    await expect(page.getByText(/\$7/)).not.toBeVisible()
    await expect(page.getByText(/\$15/)).not.toBeVisible()
  })

  test('Browse by Tag section shows grouped categories', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /browse by tag/i })).toBeVisible()
    // At least one category header should be visible (Genre is expanded by default)
    await expect(page.getByText('Genre')).toBeVisible()
  })

  test('Browse by Tag search filters tags', async ({ page }) => {
    const search = page.getByPlaceholder(/search tags/i)
    await expect(search).toBeVisible()
    await search.fill('Action')
    await expect(page.getByRole('link', { name: /^Action/ }).first()).toBeVisible()
  })
})
