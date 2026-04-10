import { test, expect } from '@playwright/test'
import { collectConsoleErrors, assertNoVisibleGarbage } from './fixtures/helpers'

test.describe('Trends lens — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
    await page.goto('/explore')
  })

  test.afterEach(async ({ page }) => {
    await assertNoVisibleGarbage(page)
    consoleCheck.check()
  })

  test('trends segment caption shows "entire catalog"', async ({ page }) => {
    const caption = page.getByTestId('trends-segment-caption')
    await expect(caption).toBeVisible()
    await expect(caption).toContainText(/entire catalog/i)
  })

  test('genre filter updates caption', async ({ page }) => {
    await page.goto('/explore?genre=action')
    const caption = page.getByTestId('trends-segment-caption')
    await expect(caption).toContainText(/genre=action/i)
  })

  test('tag filter updates caption', async ({ page }) => {
    await page.goto('/explore?tag=roguelike')
    const caption = page.getByTestId('trends-segment-caption')
    await expect(caption).toContainText(/tag=roguelike/i)
  })

  test('Release Volume chart renders', async ({ page }) => {
    await expect(page.getByText('Release Volume', { exact: true })).toBeVisible()
  })
})
