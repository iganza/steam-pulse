import { test, expect } from '@playwright/test'
import { collectConsoleErrors, assertNoVisibleGarbage, assertPageLoadsOk } from './fixtures/helpers'

test.describe('New Releases page — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
    await page.goto('/new-releases')
  })

  test.afterEach(async ({ page }) => {
    await assertNoVisibleGarbage(page)
    consoleCheck.check()
  })

  test('page loads with heading', async ({ page }) => {
    await assertPageLoadsOk(page)
    await expect(page.getByRole('heading', { name: 'New Releases' })).toBeVisible()
  })

  test('three lens tabs are visible', async ({ page }) => {
    await expect(page.getByTestId('lens-released')).toBeVisible()
    await expect(page.getByTestId('lens-upcoming')).toBeVisible()
    await expect(page.getByTestId('lens-added')).toBeVisible()
  })

  test('released lens renders feed grid or empty state', async ({ page }) => {
    // Feed grid renders when there are recent releases; empty state otherwise
    const feedGrid = page.getByTestId('feed-grid')
    const emptyState = page.getByTestId('empty-state')
    await expect(feedGrid.or(emptyState)).toBeVisible()
  })

  test('window pills are visible', async ({ page }) => {
    await expect(page.getByTestId('window-pills')).toBeVisible()
  })

  test('switching to Coming Soon updates URL', async ({ page }) => {
    await page.getByTestId('lens-upcoming').click()
    await expect(page).toHaveURL(/lens=upcoming/)
  })

  test('genre filter dropdown is present', async ({ page }) => {
    await expect(page.getByTestId('genre-filter')).toBeVisible()
  })

  test('Just Added lens loads without error', async ({ page }) => {
    await page.goto('/new-releases?lens=added')
    await assertPageLoadsOk(page)
    await expect(page.getByTestId('lens-added')).toHaveAttribute('aria-pressed', 'true')
  })
})
