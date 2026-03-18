import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('Game report page — analyzed game', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/440/team-fortress-2')
  })

  test('renders game name in hero', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Team Fortress 2' })).toBeVisible()
  })

  test('renders all report sections', async ({ page }) => {
    const sections = [
      /the verdict/i,
      /design strengths/i,
      /gameplay friction/i,
      /audience profile/i,
      /player wishlist/i,
      /churn triggers/i,
      /developer priorities/i,
      /competitive context/i,
      /genre context/i,
    ]
    for (const section of sections) {
      await expect(page.getByText(section)).toBeVisible()
    }
  })

  test('no blur overlay or lock icons', async ({ page }) => {
    await expect(page.locator('.premium-blur-content')).not.toBeAttached()
    await expect(page.locator('.premium-overlay')).not.toBeAttached()
  })

  test('no unlock or pricing CTAs', async ({ page }) => {
    await expect(page.getByText(/unlock/i)).not.toBeVisible()
    await expect(page.getByText(/\$7/)).not.toBeVisible()
  })

  test('sentiment score is shown', async ({ page }) => {
    // ScoreBar renders the numeric score and sentiment label
    await expect(page.getByText('87')).toBeVisible()
  })

  test('tag chips are rendered and link to /tag/', async ({ page }) => {
    const tagLink = page.getByRole('link', { name: /fps|multiplayer|shooter/i }).first()
    await expect(tagLink).toBeVisible()
    await expect(tagLink).toHaveAttribute('href', /\/tag\//)
  })

  test('developer Pro CTA is present at bottom', async ({ page }) => {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    await expect(page.getByText(/genre intelligence.*pro|pro.*genre intelligence/i)).toBeVisible()
  })

  test('breadcrumbs are present', async ({ page }) => {
    await expect(page.getByRole('navigation', { name: /breadcrumb/i })).toBeVisible()
    await expect(page.getByRole('link', { name: /home/i })).toBeVisible()
  })

  test('page has main landmark', async ({ page }) => {
    await expect(page.getByRole('main')).toBeVisible()
  })

  test('overall sentiment label is shown', async ({ page }) => {
    await expect(page.getByText(/overwhelmingly positive/i)).toBeVisible()
  })
})

test.describe('Game report page — unanalyzed game', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/9999999/obscure-indie-game')
  })

  test('does not show analysis sections', async ({ page }) => {
    await expect(page.getByText(/the verdict/i)).not.toBeVisible()
  })

  test('shows review count in quick stats', async ({ page }) => {
    // reviewCount=42 renders in Quick Stats section
    await expect(page.getByText('42')).toBeVisible()
  })

  test('shows "analysis not yet available" message', async ({ page }) => {
    await expect(page.getByText(/AI analysis available once this game reaches sufficient reviews/i)).toBeVisible()
  })

  test('short description is shown', async ({ page }) => {
    await expect(page.getByText(/small indie adventure/i)).toBeVisible()
  })
})
