import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('User journeys', () => {
  test('home → search → game report', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/')
    await page.getByPlaceholder(/search.*steam games/i).fill('team fortress')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/search/)
    await page.getByText('Team Fortress 2').first().click()
    await expect(page).toHaveURL(/\/games\/440\//)
    await expect(page.getByRole('heading', { name: 'Team Fortress 2' })).toBeVisible()
  })

  test('home → browse genre → game report', async ({ page, isMobile }) => {
    test.skip(isMobile, 'Browse dropdown is desktop-only')
    await mockAllApiRoutes(page)
    await page.goto('/')
    await page.getByRole('button', { name: /browse/i }).click()
    await page.getByRole('link', { name: /^Action/ }).first().click()
    await expect(page).toHaveURL(/\/genre\/action/)
    await page.getByText('Team Fortress 2').first().click()
    await expect(page).toHaveURL(/\/games\/440\//)
  })

  test('game report tag chip → tag page', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/440/team-fortress-2')
    await page.getByRole('link', { name: /fps|multiplayer/i }).first().click()
    await expect(page).toHaveURL(/\/tag\//)
  })

  test('game report genre chip → genre page', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/440/team-fortress-2')
    await page.getByRole('link', { name: /action/i }).first().click()
    await expect(page).toHaveURL(/\/genre\/action/)
  })

  test('/about page loads', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/about')
    await expect(page.getByRole('heading', { name: /about steampulse/i })).toBeVisible()
  })
})
