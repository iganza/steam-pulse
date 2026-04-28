import { test, expect } from '@playwright/test'
import { collectConsoleErrors, assertNoVisibleGarbage, assertPageLoadsOk } from './fixtures/helpers'

test.describe('Home page — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
    await page.goto('/')
  })

  test.afterEach(async ({ page }) => {
    await assertNoVisibleGarbage(page)
    consoleCheck.check()
  })

  test('page loads without errors', async ({ page }) => {
    await assertPageLoadsOk(page)
  })

  test('hero heading is present', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /steam, decoded/i })).toBeVisible()
  })

  test('hero waitlist form is the primary CTA', async ({ page }) => {
    const form = page.getByTestId('waitlist-form-hero')
    await expect(form).toBeVisible()
    await expect(form.getByRole('button', { name: /join the pro waitlist/i })).toBeVisible()
  })

  test('navbar is visible with navigation landmark', async ({ page }) => {
    await expect(page.getByRole('navigation', { name: /main navigation/i })).toBeVisible()
  })

  test('Featured analyses tabbed showcase renders the three anchors', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /featured analyses/i })).toBeVisible()
    await expect(page.getByRole('tab', { name: /baldur'?s gate 3/i })).toBeVisible()
    await expect(page.getByRole('tab', { name: /stardew valley/i })).toBeVisible()
    await expect(page.getByRole('tab', { name: /cyberpunk 2077/i })).toBeVisible()
  })

  test('Featured analyses panel exposes a deep-link to the full report', async ({ page }) => {
    const panel = page.getByRole('tabpanel')
    const readLink = panel.getByRole('link', { name: /read full analysis/i })
    await expect(readLink).toBeVisible()
    const href = await readLink.getAttribute('href')
    expect(href).toMatch(/^\/games\/\d+\//)
  })
})
