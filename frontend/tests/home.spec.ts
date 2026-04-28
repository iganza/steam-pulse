import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('Home page', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/')
  })

  test('hero heading is present', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /steam, decoded/i })).toBeVisible()
  })

  test('hero waitlist form is the primary above-the-fold CTA', async ({ page }) => {
    const form = page.getByTestId('waitlist-form-hero')
    await expect(form).toBeVisible()
    await expect(form.getByRole('button', { name: /join the pro waitlist/i })).toBeVisible()
    await expect(form.getByPlaceholder(/your@email\.com/i)).toBeVisible()
  })

  test('repeat waitlist form renders at the bottom of the page', async ({ page }) => {
    await expect(page.getByTestId('waitlist-form-repeat')).toBeVisible()
  })

  test('Featured analyses tabbed showcase renders all three anchors', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /featured analyses/i })).toBeVisible()
    await expect(page.getByRole('tab', { name: /baldur'?s gate 3/i })).toBeVisible()
    await expect(page.getByRole('tab', { name: /stardew valley/i })).toBeVisible()
    await expect(page.getByRole('tab', { name: /cyberpunk 2077/i })).toBeVisible()
  })

  test('clicking a Featured analyses tab swaps the panel content', async ({ page }) => {
    const stardewTab = page.getByRole('tab', { name: /stardew valley/i })
    await stardewTab.click()
    await expect(stardewTab).toHaveAttribute('aria-selected', 'true')
    // Panel should reflect the active tab via aria-controls/aria-labelledby wiring
    const panel = page.getByRole('tabpanel')
    await expect(panel).toBeVisible()
    await expect(panel.getByRole('heading', { name: /stardew valley/i })).toBeVisible()
  })

  test('Featured analyses panel exposes a "Read full analysis" deep link', async ({ page }) => {
    const panel = page.getByRole('tabpanel')
    const readLink = panel.getByRole('link', { name: /read full analysis/i })
    await expect(readLink).toBeVisible()
    const href = await readLink.getAttribute('href')
    expect(href).toMatch(/^\/games\/\d+\//)
  })

  test('Just analyzed section renders the latest analyzed games', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /just analyzed/i })).toBeVisible()
  })

  test('navbar Browse dropdown opens and shows genres', async ({ page, isMobile }) => {
    test.skip(isMobile, 'Browse dropdown is desktop-only — mobile uses hamburger menu')
    await page.getByRole('button', { name: /browse/i }).click()
    await expect(page.getByRole('link', { name: /^Action/ }).first()).toBeVisible()
  })

  test('clicking a browse genre navigates to genre page', async ({ page, isMobile }) => {
    test.skip(isMobile, 'Browse dropdown is desktop-only — mobile uses hamburger menu')
    await page.getByRole('button', { name: /browse/i }).click()
    await page.getByRole('link', { name: /^Action/ }).first().click()
    await expect(page).toHaveURL(/\/genre\/action/)
  })

  test('navbar is visible', async ({ page }) => {
    await expect(page.getByRole('navigation', { name: /main navigation/i })).toBeVisible()
  })

  test('no paywall or unlock buttons present', async ({ page }) => {
    await expect(page.getByText(/unlock/i)).not.toBeVisible()
    await expect(page.getByText(/\$7/)).not.toBeVisible()
    await expect(page.getByText(/\$15/)).not.toBeVisible()
  })

  test('Market Trends section is visible with granularity toggle', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /market trends/i })).toBeVisible()
    const section = page.locator('section').filter({ hasText: 'Market Trends' })
    await expect(section.getByRole('button', { name: /^Week$/ })).toBeVisible()
    await expect(section.getByRole('button', { name: /^Month$/ })).toBeVisible()
    await expect(section.getByRole('button', { name: /^Quarter$/ })).toBeVisible()
    await expect(section.getByRole('button', { name: /^Year$/ })).toBeVisible()
  })

  test('switching granularity refetches trend data with new param', async ({ page }) => {
    const section = page.locator('section').filter({ hasText: 'Market Trends' })
    await expect(section.getByRole('button', { name: /^Year$/ })).toBeVisible()
    const sentimentReq = page.waitForRequest((req) =>
      /\/api\/analytics\/trends\/sentiment\?.*granularity=month/.test(req.url()),
    )
    const releasesReq = page.waitForRequest((req) =>
      /\/api\/analytics\/trends\/release-volume\?.*granularity=month/.test(req.url()),
    )
    await section.getByRole('button', { name: /^Month$/ }).click()
    await sentimentReq
    await releasesReq
  })
})
