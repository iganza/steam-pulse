import { test, expect } from '@playwright/test'
import {
  collectConsoleErrors,
  assertNoVisibleGarbage,
  assertPageLoadsOk,
  KNOWN_DEVELOPER_SLUG,
} from './fixtures/helpers'

test.describe('Developer page — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
    await page.goto(`/developer/${KNOWN_DEVELOPER_SLUG}`)
  })

  test.afterEach(async ({ page }) => {
    await assertNoVisibleGarbage(page)
    consoleCheck.check()
  })

  test('page loads with developer heading', async ({ page }) => {
    await assertPageLoadsOk(page)
    await expect(page.getByRole('heading', { name: /valve/i })).toBeVisible()
  })

  test('at least one game card is visible', async ({ page }) => {
    const gameLinks = page.locator('a[href^="/games/"]')
    expect(await gameLinks.count()).toBeGreaterThan(0)
  })

  test('developer analytics section is present', async ({ page }) => {
    await expect(page.getByText(/developer analytics/i)).toBeVisible()
  })
})

test.describe('Publisher page — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
    await page.goto('/publisher/valve')
  })

  test.afterEach(async ({ page }) => {
    await assertNoVisibleGarbage(page)
    consoleCheck.check()
  })

  test('page loads with publisher heading', async ({ page }) => {
    await assertPageLoadsOk(page)
    await expect(page.getByRole('heading', { name: /valve/i })).toBeVisible()
  })

  test('at least one game card is visible', async ({ page }) => {
    const gameLinks = page.locator('a[href^="/games/"]')
    expect(await gameLinks.count()).toBeGreaterThan(0)
  })
})
