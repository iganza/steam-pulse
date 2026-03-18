import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('Home page', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/')
  })

  test('renders search hero with placeholder', async ({ page }) => {
    const input = page.getByPlaceholder(/search.*steam games/i)
    await expect(input).toBeVisible()
  })

  test('typing in search navigates to /search with q param', async ({ page }) => {
    const input = page.getByPlaceholder(/search.*steam games/i)
    await input.fill('hollow knight')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/search\?q=hollow/)
  })

  test('page heading is present', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /discover steam games/i })).toBeVisible()
  })

  test('navbar Browse dropdown opens and shows genres', async ({ page }) => {
    await page.getByRole('button', { name: /browse/i }).click()
    await expect(page.getByText('Action')).toBeVisible()
  })

  test('clicking a browse genre navigates to genre page', async ({ page }) => {
    await page.getByRole('button', { name: /browse/i }).click()
    await page.getByText('Action').first().click()
    await expect(page).toHaveURL(/\/genre\/action/)
  })

  test('navbar is visible', async ({ page }) => {
    await expect(page.getByRole('navigation')).toBeVisible()
  })

  test('no paywall or unlock buttons present', async ({ page }) => {
    await expect(page.getByText(/unlock/i)).not.toBeVisible()
    await expect(page.getByText(/\$7/)).not.toBeVisible()
    await expect(page.getByText(/\$15/)).not.toBeVisible()
  })
})
