import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

// Genre page coverage moved to genre-page.spec.ts — /genre/[slug]/ now
// renders the synthesis page (genre-insights-page.md), not the listing.

test.describe('Tag page', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/tag/multiplayer')
  })

  test('renders tag name as heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /multiplayer/i })).toBeVisible()
  })

  test('shows related tags section', async ({ page }) => {
    // Heading is "More {category} Tags" when category is known, or "Related Tags" as fallback
    await expect(page.getByText(/(related tags|more .+ tags)/i)).toBeVisible()
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

test.describe('Publisher page', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/publisher/valve')
  })

  test('renders publisher name', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /valve/i })).toBeVisible()
  })

  test('shows publisher games', async ({ page }) => {
    await expect(page.getByText('Team Fortress 2').first()).toBeVisible()
  })

  test('shows Pro CTA for publisher intelligence', async ({ page }) => {
    await expect(page.getByText(/publisher intelligence.*pro|competitive analysis/i)).toBeVisible()
  })
})
