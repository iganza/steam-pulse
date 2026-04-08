import { test, expect } from '@playwright/test'
import { mockAllApiRoutes, mockAnalyticsRoutes } from './fixtures/api-mock'
import { MOCK_ENGAGEMENT_UNAVAILABLE } from './fixtures/mock-data'

test.describe('Explore page', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/explore')
  })

  test('renders page heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /explore/i })).toBeVisible()
  })

  test('renders Release Volume chart', async ({ page }) => {
    await expect(page.getByText('Release Volume')).toBeVisible()
  })

  test('renders Sentiment Distribution chart', async ({ page }) => {
    await expect(page.getByText('Sentiment Distribution')).toBeVisible()
  })

  test('renders Genre Share chart', async ({ page }) => {
    await expect(page.getByText('Genre Share')).toBeVisible()
  })

  test('renders Review Velocity chart', async ({ page }) => {
    await expect(page.getByText('Review Velocity')).toBeVisible()
  })

  test('renders Pricing Trends chart', async ({ page }) => {
    await expect(page.getByText('Pricing Trends')).toBeVisible()
  })

  test('renders Early Access Trends chart', async ({ page }) => {
    await expect(page.getByText('Early Access Trends')).toBeVisible()
  })

  test('renders Platform & Steam Deck chart', async ({ page }) => {
    await expect(page.getByText('Platform & Steam Deck')).toBeVisible()
  })

  test('renders Engagement Depth chart', async ({ page }) => {
    await expect(page.getByText('Engagement Depth')).toBeVisible()
  })

  test('renders Feature Adoption chart', async ({ page }) => {
    await expect(page.getByText('Feature Adoption')).toBeVisible()
  })

  test('control bar is blurred for non-Pro users', async ({ page }) => {
    // The blurred controls container is present with blur-sm class
    const blurred = page.locator('.blur-sm')
    await expect(blurred).toBeVisible()
  })

  test('shows "Customize with Pro" CTA for non-Pro users', async ({ page }) => {
    await expect(page.getByRole('link', { name: /customize with pro/i })).toBeVisible()
  })

  test('"Customize with Pro" links to /pro', async ({ page }) => {
    await page.getByRole('link', { name: /customize with pro/i }).click()
    await expect(page).toHaveURL('/pro')
  })

  test('granularity toggle buttons are present', async ({ page }) => {
    await expect(page.getByRole('button', { name: /week/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /month/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /quarter/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /year/i })).toBeVisible()
  })

  test('granularity toggle buttons are disabled for non-Pro users', async ({ page }) => {
    await expect(page.getByRole('button', { name: /week/i })).toBeDisabled()
    await expect(page.getByRole('button', { name: /month/i })).toBeDisabled()
  })

  test('explore link is in the navbar', async ({ page, isMobile }) => {
    test.skip(isMobile, 'Desktop nav only')
    const nav = page.getByRole('navigation', { name: /main navigation/i })
    await expect(nav.getByRole('link', { name: /explore/i })).toBeVisible()
  })

  test('explore link appears in mobile menu', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const hamburger = page.locator('nav button').last()
    await hamburger.click()
    await expect(page.getByRole('link', { name: /explore/i })).toBeVisible()
  })
})

test.describe('Explore page — engagement empty state', () => {
  test('shows empty state when engagement data is unavailable', async ({ page }) => {
    await mockAnalyticsRoutes(page)
    // Override just the engagement route to return data_available: false
    await page.route('**/api/analytics/trends/engagement**', route =>
      route.fulfill({ json: MOCK_ENGAGEMENT_UNAVAILABLE })
    )
    // Also mock other routes the page needs
    await page.route('**/api/genres**', route =>
      route.fulfill({ json: [] })
    )
    await page.route('**/api/tags/**', route =>
      route.fulfill({ json: [] })
    )
    await page.goto('/explore')
    await expect(page.getByText(/engagement data is being computed/i)).toBeVisible()
  })
})

test.describe('Route redirects', () => {
  test('/analytics redirects to /explore', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/analytics')
    await expect(page).toHaveURL(/\/explore$/)
  })

  test('/toolkit redirects to /explore', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/toolkit')
    await expect(page).toHaveURL(/\/explore$/)
  })
})
