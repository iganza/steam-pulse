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

  test('shows game count or result info', async ({ page }) => {
    await expect(page.getByText(/games/i).first()).toBeVisible()
  })

  test('shows game cards', async ({ page }) => {
    await expect(page.getByText('Team Fortress 2').first()).toBeVisible()
  })

  test('breadcrumbs include home', async ({ page }) => {
    // Breadcrumbs are rendered server-side as a nav with aria-label
    await expect(page.getByRole('navigation', { name: /breadcrumb/i })).toBeVisible()
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

  test('shows related tags section', async ({ page }) => {
    // Related Tags section heading is always rendered
    await expect(page.getByText(/related tags/i)).toBeVisible()
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
    await expect(page.getByText('Team Fortress 2').first()).toBeVisible()
  })

  test('shows Pro CTA for developer intelligence', async ({ page }) => {
    await expect(page.getByText(/developer intelligence.*pro|competitive analysis/i)).toBeVisible()
  })
})
