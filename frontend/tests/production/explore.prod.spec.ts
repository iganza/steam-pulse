import { test, expect } from '@playwright/test'
import { collectConsoleErrors, assertNoVisibleGarbage, assertPageLoadsOk } from './fixtures/helpers'

test.describe('Explore page — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
    await page.goto('/explore')
  })

  test.afterEach(async ({ page }) => {
    await assertNoVisibleGarbage(page)
    consoleCheck.check()
  })

  test('page loads with heading', async ({ page }) => {
    await assertPageLoadsOk(page)
    await expect(page.getByRole('heading', { name: /explore/i })).toBeVisible()
  })

  test('all chart section headings render', async ({ page }) => {
    const sections = [
      'Release Volume',
      'Sentiment Distribution',
      'Genre Share',
      'Review Velocity',
      'Pricing Trends',
      'Early Access Trends',
      'Platform & Steam Deck',
      'Engagement Depth',
      'Feature Adoption',
    ]
    for (const section of sections) {
      await expect(page.getByText(section, { exact: true })).toBeVisible()
    }
  })

  test('granularity toggle buttons are present', async ({ page }) => {
    await expect(page.getByRole('button', { name: /week/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /month/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /quarter/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /year/i })).toBeVisible()
  })

  test('trends segment caption is visible', async ({ page }) => {
    await expect(page.getByTestId('trends-segment-caption')).toBeVisible()
  })

  test('/analytics redirects to /explore', async ({ page }) => {
    await page.goto('/analytics')
    await expect(page).toHaveURL(/\/explore$/)
  })
})
