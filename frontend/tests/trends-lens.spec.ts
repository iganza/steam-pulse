import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('Trends lens — segment caption', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
  })

  test('default caption shows "entire catalog"', async ({ page }) => {
    await page.goto('/explore')
    const caption = page.getByTestId('trends-segment-caption')
    await expect(caption).toBeVisible()
    await expect(caption).toContainText(/entire catalog/i)
  })

  test('caption reflects genre filter from URL', async ({ page }) => {
    await page.goto('/explore?genre=action')
    const caption = page.getByTestId('trends-segment-caption')
    await expect(caption).toContainText(/genre=action/i)
  })

  test('caption reflects tag filter from URL', async ({ page }) => {
    await page.goto('/explore?tag=roguelike')
    const caption = page.getByTestId('trends-segment-caption')
    await expect(caption).toContainText(/tag=roguelike/i)
  })

  test('ignored-filter notice appears for unsupported filters', async ({ page }) => {
    await page.goto('/explore?price_tier=under_10')
    const caption = page.getByTestId('trends-segment-caption')
    await expect(caption).toContainText(/not yet supported in Trends/i)
    await expect(caption).toContainText(/price tier/i)
  })

  test('appids advisory appears when games are scoped', async ({ page }) => {
    await page.goto('/explore?appids=440,570')
    const caption = page.getByTestId('trends-segment-caption')
    await expect(caption).toContainText(/catalog-wide/i)
    await expect(caption).toContainText(/single-game timeline/i)
  })
})

test.describe('Trends lens — filter propagation', () => {
  test('genre filter is forwarded to trend API helpers', async ({ page }) => {
    await mockAllApiRoutes(page)

    const seenGenres: string[] = []
    await page.route('**/api/analytics/trends/release-volume**', async (route) => {
      const url = new URL(route.request().url())
      const g = url.searchParams.get('genre')
      if (g) seenGenres.push(g)
      await route.fallback()
    })

    await page.goto('/explore?genre=action')
    // Wait for the lens to fire its requests
    await page.getByText('Release Volume').waitFor()
    await expect.poll(() => seenGenres).toContain('action')
  })

  test('tag filter is forwarded to release-volume helper', async ({ page }) => {
    await mockAllApiRoutes(page)

    const seenTags: string[] = []
    await page.route('**/api/analytics/trends/release-volume**', async (route) => {
      const url = new URL(route.request().url())
      const t = url.searchParams.get('tag')
      if (t) seenTags.push(t)
      await route.fallback()
    })

    await page.goto('/explore?tag=roguelike')
    await page.getByText('Release Volume').waitFor()
    await expect.poll(() => seenTags).toContain('roguelike')
  })
})

test.describe('Trends lens — genre page integration', () => {
  test('Trends tab on /genre/action renders the lens scoped to action', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/genre/action?lens=trends')
    await expect(page.getByText('Release Volume')).toBeVisible()
    await expect(page.getByTestId('trends-segment-caption')).toContainText(/genre=action/i)
  })

  test('Trends tab on /tag/roguelike renders the lens scoped to roguelike', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/tag/roguelike?lens=trends')
    await expect(page.getByText('Release Volume')).toBeVisible()
    await expect(page.getByTestId('trends-segment-caption')).toContainText(/tag=roguelike/i)
  })
})
