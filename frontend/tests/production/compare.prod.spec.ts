import { test, expect } from '@playwright/test'
import {
  collectConsoleErrors,
  assertNoVisibleGarbage,
  assertPageLoadsOk,
  KNOWN_APPIDS,
} from './fixtures/helpers'

test.describe('Compare lens — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
  })

  test.afterEach(async ({ page }) => {
    await assertNoVisibleGarbage(page)
    consoleCheck.check()
  })

  test('empty state renders when no appids', async ({ page }) => {
    await page.goto('/compare')
    await assertPageLoadsOk(page)
    await expect(page.getByTestId('compare-empty-prompt')).toBeVisible()
  })

  test('two games load with columns visible', async ({ page }) => {
    await page.goto(`/compare?appids=${KNOWN_APPIDS.TF2},${KNOWN_APPIDS.CS2}`)
    await expect(page.getByTestId('compare-lens')).toBeVisible()
    // Both game pills should be present (names may show as appids locally)
    await expect(page.getByTestId(`compare-pill-${KNOWN_APPIDS.TF2}`)).toBeVisible()
    await expect(page.getByTestId(`compare-pill-${KNOWN_APPIDS.CS2}`)).toBeVisible()
  })

  test('metric rows render', async ({ page }) => {
    await page.goto(`/compare?appids=${KNOWN_APPIDS.TF2},${KNOWN_APPIDS.CS2}`)
    await expect(page.getByTestId('metric-row-positive_pct')).toBeVisible()
    await expect(page.getByTestId('metric-row-review_count')).toBeVisible()
  })

  test('metric values are displayed', async ({ page }) => {
    await page.goto(`/compare?appids=${KNOWN_APPIDS.TF2},${KNOWN_APPIDS.CS2}`)
    // At least one metric row should have numeric content
    const pctRow = page.getByTestId('metric-row-positive_pct')
    await expect(pctRow).toBeVisible()
    await expect(pctRow).toContainText(/%/)
  })

  test('who-wins-where summary renders', async ({ page }) => {
    await page.goto(`/compare?appids=${KNOWN_APPIDS.TF2},${KNOWN_APPIDS.CS2}`)
    const summary = page.getByTestId('compare-wins-summary')
    await expect(summary).toBeVisible()
  })
})
