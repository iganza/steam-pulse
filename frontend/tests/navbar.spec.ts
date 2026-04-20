import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('Navbar', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
  })

  test('is present on home page', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('navigation', { name: /main navigation/i })).toBeVisible()
  })

  test('is present on search page', async ({ page }) => {
    await page.goto('/search')
    await expect(page.getByRole('navigation', { name: /main navigation/i })).toBeVisible()
  })

  test('is present on game report page', async ({ page }) => {
    await page.goto('/games/440/team-fortress-2')
    await expect(page.getByRole('navigation', { name: /main navigation/i })).toBeVisible()
  })

  test('logo links to home', async ({ page }) => {
    await page.goto('/search')
    await page.getByRole('link', { name: /steampulse/i }).first().click()
    await expect(page).toHaveURL('/')
  })

  test('Browse dropdown opens and shows genres', async ({ page, isMobile }) => {
    test.skip(isMobile, 'Browse dropdown is desktop-only — mobile uses hamburger menu')
    await page.goto('/')
    await page.getByRole('button', { name: /browse/i }).click()
    // Genres load async via browser fetch — wait for dropdown link
    await expect(page.getByRole('link', { name: /^Action/ }).first()).toBeVisible()
  })

  test('About link navigates to /about', async ({ page, isMobile }) => {
    test.skip(isMobile, 'Desktop-only nav link')
    await page.goto('/')
    await page.getByRole('link', { name: /^about$/i }).click()
    await expect(page).toHaveURL('/about')
  })

  test('mobile hamburger menu opens on small viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/')
    const hamburger = page.locator('nav button').last()
    await hamburger.click()
    await expect(page.getByRole('link', { name: /reports/i })).toBeVisible()
  })
})
