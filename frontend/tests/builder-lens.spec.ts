import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

const IS_PRO = process.env.NEXT_PUBLIC_PRO_ENABLED === 'true'

test.describe('Builder lens', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
  })

  test('smart default — pre-selects a metric and renders a chart', async ({ page }) => {
    await page.goto('/explore?lens=builder')
    await expect(page.getByTestId('builder-lens')).toBeVisible()
    // Default metric ("releases") should be auto-selected, causing the chart
    // to render (not the empty state).
    await expect(page.getByTestId('builder-empty-state')).toHaveCount(0)
    await expect(page.getByTestId('builder-metric-chip-releases')).toHaveAttribute('data-selected', 'true')
  })

  test('picking a metric updates URL and fires a fetch', async ({ page }) => {
    const fetchedMetrics: string[] = []
    await page.route('**/api/analytics/trend-query**', async (route) => {
      const url = new URL(route.request().url())
      fetchedMetrics.push(url.searchParams.get('metrics') ?? '')
      await route.fallback()
    })

    await page.goto('/explore?lens=builder')
    await expect(page.getByTestId('builder-lens')).toBeVisible()

    // Free tier = 1 metric cap — clicking the current selection deselects it,
    // then clicking a new one selects it.
    await page.getByTestId('builder-metric-chip-releases').click()
    await page.getByTestId('builder-metric-chip-avg_steam_pct').click()

    await expect(page.getByTestId('builder-metric-chip-avg_steam_pct')).toHaveAttribute(
      'data-selected',
      'true',
    )
    await expect.poll(() => fetchedMetrics.join('|')).toContain('avg_steam_pct')
  })

  test('switching chart type does not re-fetch', async ({ page }) => {
    let fetchCount = 0
    await page.route('**/api/analytics/trend-query**', async (route) => {
      fetchCount += 1
      await route.fallback()
    })

    await page.goto('/explore?lens=builder')
    await expect(page.getByTestId('builder-lens')).toBeVisible()
    // Wait for the initial smart-default fetch to complete.
    await expect.poll(() => fetchCount).toBeGreaterThanOrEqual(1)
    const before = fetchCount

    await page.getByTestId('builder-chart-type-line').click()
    // Give the component a moment — if a fetch were going to fire it would
    // be within the 250ms debounce window.
    await page.waitForTimeout(400)
    expect(fetchCount).toBe(before)
  })

  test('free tier: metric picker capped at 1', async ({ page }) => {
    test.skip(IS_PRO, 'Only runs when Pro flag is off')
    await page.goto('/explore?lens=builder')
    await expect(page.getByTestId('builder-lens')).toBeVisible()
    // Smart default already took the single slot.
    await expect(page.getByTestId('builder-metric-chip-releases')).toHaveAttribute(
      'data-selected',
      'true',
    )
    // Another metric chip should be disabled (at cap).
    await expect(page.getByTestId('builder-metric-chip-avg_steam_pct')).toBeDisabled()
  })

  test('genre filter forwards to trend-query', async ({ page }) => {
    const seen: string[] = []
    await page.route('**/api/analytics/trend-query**', async (route) => {
      const url = new URL(route.request().url())
      const g = url.searchParams.get('genre')
      if (g) seen.push(g)
      await route.fallback()
    })
    await page.goto('/explore?lens=builder&genre=action')
    await expect(page.getByTestId('builder-lens')).toBeVisible()
    await expect.poll(() => seen).toContain('action')
  })
})
