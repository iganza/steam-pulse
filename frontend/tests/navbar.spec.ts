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
    // Genres load async via browser fetch — wait for them
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
    // The mobile toggle is the last button in the nav (menu/X icon)
    const hamburger = page.locator('nav button').last()
    await hamburger.click()
    await expect(page.getByRole('link', { name: /trending/i })).toBeVisible()
  })
})
