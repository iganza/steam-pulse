import { test, expect } from '@playwright/test'

test.describe('/about page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/about')
  })

  test('renders the four anchored sections', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /About SteamPulse/i })).toBeVisible()
    for (const id of ['what', 'methodology', 'author', 'contact']) {
      await expect(page.locator(`section#${id}`)).toBeVisible()
    }
  })

  test('/about#methodology resolves to the methodology section', async ({ page }) => {
    await page.goto('/about#methodology')
    await expect(page.locator('section#methodology')).toBeVisible()
  })

  test('names the author and carries a canonical + title', async ({ page }) => {
    await expect(page.getByText(/Ivan Z\. Ganza/)).toBeVisible()
    const canonical = await page.locator('link[rel="canonical"]').getAttribute('href')
    expect(canonical).toBe('https://steampulse.io/about')
    await expect(page).toHaveTitle(/About SteamPulse/)
  })

  test('contact section exposes a mailto link', async ({ page }) => {
    const mailLink = page.locator('section#contact a[href^="mailto:"]')
    await expect(mailLink).toBeVisible()
  })
})
