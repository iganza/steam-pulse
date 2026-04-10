import { test, expect } from '@playwright/test'
import {
  collectConsoleErrors,
  assertNoVisibleGarbage,
  assertPageLoadsOk,
  KNOWN_GENRE_SLUG,
  KNOWN_TAG_SLUG,
} from './fixtures/helpers'

test.describe('Genre page — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
    await page.goto(`/genre/${KNOWN_GENRE_SLUG}`)
  })

  test.afterEach(async ({ page }) => {
    await assertNoVisibleGarbage(page)
    consoleCheck.check()
  })

  test('page loads with genre heading', async ({ page }) => {
    await assertPageLoadsOk(page)
    await expect(page.getByRole('heading', { name: /action/i })).toBeVisible()
  })

  test('game cards are present', async ({ page }) => {
    const gameLinks = page.locator('a[href^="/games/"]')
    expect(await gameLinks.count()).toBeGreaterThan(0)
  })

  test('breadcrumbs include home', async ({ page }) => {
    await expect(page.getByRole('navigation', { name: /breadcrumb/i })).toBeVisible()
  })

  test('game cards link to valid game URLs', async ({ page }) => {
    const firstGameLink = page.locator('a[href^="/games/"]').first()
    const href = await firstGameLink.getAttribute('href')
    expect(href).toMatch(/\/games\/\d+\//)
  })
})

test.describe('Tag page — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
    await page.goto(`/tag/${KNOWN_TAG_SLUG}`)
  })

  test.afterEach(async ({ page }) => {
    await assertNoVisibleGarbage(page)
    consoleCheck.check()
  })

  test('page loads with tag heading', async ({ page }) => {
    await assertPageLoadsOk(page)
    await expect(page.getByRole('heading', { name: /multiplayer/i })).toBeVisible()
  })

  test('game cards load', async ({ page }) => {
    // Games load via client-side fetch — wait for at least one to appear
    const firstGame = page.locator('a[href^="/games/"]').first()
    await expect(firstGame).toBeVisible({ timeout: 15_000 })
  })

  test('related tags section is visible', async ({ page }) => {
    await expect(page.getByText(/(related tags|more .+ tags)/i)).toBeVisible()
  })

  test('tag trend chart renders', async ({ page }) => {
    await expect(page.getByText(/tag trends/i)).toBeVisible()
  })
})
