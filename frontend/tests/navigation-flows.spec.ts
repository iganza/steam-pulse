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

  test('home → browse genre → game report', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/')
    await page.getByRole('button', { name: /browse/i }).click()
    await page.getByText('Action').first().click()
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

  test('/trending page loads', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/trending')
    await expect(page.getByRole('heading', { name: /trending/i })).toBeVisible()
  })

  test('/new-releases page loads with tabs', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/new-releases')
    await expect(page.getByRole('tab', { name: /new on steam/i })).toBeVisible()
    await expect(page.getByRole('tab', { name: /just analyzed/i })).toBeVisible()
  })

  test('/pro page loads', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/pro')
    await expect(page.getByText(/coming soon|join the waitlist|intelligence for/i)).toBeVisible()
  })
})
