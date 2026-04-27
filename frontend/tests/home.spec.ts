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
    await expect(page.getByRole('heading', { name: /steam, decoded/i })).toBeVisible()
  })

  test('proof bar shows game count', async ({ page }) => {
    await expect(page.getByText(/games tracked/i)).toBeVisible()
  })

  test('featured report card is visible with synthesis CTA', async ({ page }) => {
    await expect(page.getByText(/featured report · new/i)).toBeVisible()
    await expect(page.getByRole('link', { name: /read the free synthesis/i })).toBeVisible()
  })

  test('featured report game strip links to the SEO-anchor games', async ({ page }) => {
    // Mock-api-server seeds BG3 / Stardew / Cyberpunk for /api/games/basics;
    // each renders as a Link to /games/{appid}/{slug}.
    await expect(page.getByRole('link', { name: /baldur'?s gate 3/i })).toBeVisible()
    await expect(page.getByRole('link', { name: /stardew valley/i })).toBeVisible()
    await expect(page.getByRole('link', { name: /cyberpunk 2077/i })).toBeVisible()
  })

  test('intelligence cards section renders the four cards', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /what you get/i })).toBeVisible()
    await expect(page.getByRole('heading', { name: /player sentiment/i })).toBeVisible()
    await expect(page.getByRole('heading', { name: /competitive intelligence/i })).toBeVisible()
    await expect(page.getByRole('heading', { name: /market intelligence/i })).toBeVisible()
    await expect(page.getByRole('heading', { name: /deep review reports/i })).toBeVisible()
  })

  test('for-developers section is visible with pro waitlist CTA', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /built for the people who make games/i })).toBeVisible()
    const cta = page.getByRole('link', { name: /join the pro waitlist/i })
    await expect(cta).toBeVisible()
    await expect(cta).toHaveAttribute('href', '/pro')
  })

  test('footer CTA is visible', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /free to explore/i })).toBeVisible()
  })

  test('navbar Browse dropdown opens and shows genres', async ({ page, isMobile }) => {
    test.skip(isMobile, 'Browse dropdown is desktop-only — mobile uses hamburger menu')
    await page.getByRole('button', { name: /browse/i }).click()
    // Scope to the dropdown link to avoid strict-mode hits from genre grid
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

  test('Browse by Tag section shows grouped categories', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /browse by tag/i })).toBeVisible()
    // At least one category header should be visible (Genre is expanded by default)
    await expect(page.getByText('Genre')).toBeVisible()
  })

  test('Browse by Tag search filters tags', async ({ page }) => {
    const search = page.getByPlaceholder(/search tags/i)
    await expect(search).toBeVisible()
    await search.fill('Action')
    await expect(page.getByRole('link', { name: /^Action/ }).first()).toBeVisible()
  })

  test('Market Trends section is visible with granularity toggle', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /market trends/i })).toBeVisible()
    const section = page.locator('section').filter({ hasText: 'Market Trends' })
    // The toggle renders Week / Month / Quarter / Year buttons.
    await expect(section.getByRole('button', { name: /^Week$/ })).toBeVisible()
    await expect(section.getByRole('button', { name: /^Month$/ })).toBeVisible()
    await expect(section.getByRole('button', { name: /^Quarter$/ })).toBeVisible()
    await expect(section.getByRole('button', { name: /^Year$/ })).toBeVisible()
  })

  test('switching granularity refetches trend data with new param', async ({ page }) => {
    const section = page.locator('section').filter({ hasText: 'Market Trends' })
    // Wait for the initial default (year) fetch to settle before we interact.
    await expect(section.getByRole('button', { name: /^Year$/ })).toBeVisible()
    // Clicking "Month" should trigger a refetch with granularity=month.
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
