import { test, expect } from '@playwright/test'
import { collectConsoleErrors, assertNoVisibleGarbage, assertPageLoadsOk } from './fixtures/helpers'

test.describe('Builder lens — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
    await page.goto('/explore?lens=builder')
  })

  test.afterEach(async ({ page }) => {
    await assertNoVisibleGarbage(page)
    consoleCheck.check()
  })

  test('builder lens renders', async ({ page }) => {
    await assertPageLoadsOk(page)
    await expect(page.getByTestId('builder-lens')).toBeVisible()
  })

  test('metric chips are present', async ({ page }) => {
    // At least the "releases" default chip should exist
    await expect(page.getByTestId('builder-metric-chip-releases')).toBeVisible()
  })

  test('chart renders with smart default (no empty state)', async ({ page }) => {
    await expect(page.getByTestId('builder-empty-state')).toHaveCount(0)
  })
})
