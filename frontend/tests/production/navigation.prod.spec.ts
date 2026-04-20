import { test, expect } from '@playwright/test'
import { collectConsoleErrors, assertNoVisibleGarbage, KNOWN_GAME_PATHS } from './fixtures/helpers'

test.describe('Navigation flows — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
  })

  test.afterEach(async ({ page }) => {
    await assertNoVisibleGarbage(page)
    consoleCheck.check()
  })

  test('home → search → game report', async ({ page }) => {
    await page.goto('/')
    await page.getByPlaceholder(/search.*steam games/i).fill('team fortress')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/search/)
    // Click the first game result
    const firstGame = page.locator('a[href^="/games/"]').first()
    await firstGame.click()
    await expect(page).toHaveURL(/\/games\/\d+\//)
    await expect(page.getByRole('main')).toBeVisible()
  })

  test('game report tag chip → tag page', async ({ page }) => {
    await page.goto(KNOWN_GAME_PATHS.TF2)
    const tagLink = page.locator('a[href^="/tag/"]').first()
    await tagLink.click()
    await expect(page).toHaveURL(/\/tag\//)
  })

  test('game report genre chip → genre page', async ({ page }) => {
    await page.goto(KNOWN_GAME_PATHS.TF2)
    const genreLink = page.locator('a[href^="/genre/"]').first()
    await genreLink.click()
    await expect(page).toHaveURL(/\/genre\//)
  })

  test('/about page loads', async ({ page }) => {
    await page.goto('/about')
    await expect(page.getByRole('heading', { name: /about steampulse/i })).toBeVisible()
  })
})
