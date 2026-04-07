import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

const IS_PRO = process.env.NEXT_PUBLIC_PRO_ENABLED === 'true'

test.describe('Compare lens', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
  })

  test('empty state — shows prompt to pick games', async ({ page }) => {
    await page.goto('/compare')
    await expect(page.getByTestId('compare-empty-prompt')).toBeVisible()
    await expect(page.getByTestId('compare-lens')).toBeVisible()
  })

  test('renders columns + metric rows with two games from URL', async ({ page }) => {
    await page.goto('/compare?appids=440,892970')
    await expect(page.getByTestId('compare-lens')).toBeVisible()
    await expect(page.getByText('Team Fortress 2').first()).toBeVisible()
    await expect(page.getByText('Valheim').first()).toBeVisible()
    // Free-tier metric rows
    await expect(page.getByTestId('metric-row-positive_pct')).toBeVisible()
    await expect(page.getByTestId('metric-row-review_count')).toBeVisible()
    await expect(page.getByTestId('metric-row-price_usd')).toBeVisible()
  })

  test('leader highlighting — at least one cell marked as leader', async ({ page }) => {
    await page.goto('/compare?appids=440,892970')
    await expect(page.getByTestId('metric-row-positive_pct')).toBeVisible()
    // Valheim (94%) should beat TF2 (87%)
    const leaders = page.getByTestId('metric-leader')
    expect(await leaders.count()).toBeGreaterThan(0)
  })

  test('picker: remove a game drops it from the URL', async ({ page }) => {
    await page.goto('/compare?appids=440,892970')
    await page.getByTestId('compare-pill-440').getByRole('button').click()
    await expect(page).toHaveURL(/appids=892970/)
    await expect(page.getByTestId('compare-pill-440')).toHaveCount(0)
  })

  test('picker: adding via search updates the URL', async ({ page }) => {
    await page.goto('/compare?appids=440')
    await page.getByTestId('compare-add-button').click()
    await page.getByTestId('compare-search-popover').getByRole('textbox').fill('Valheim')
    // Click the result for Valheim
    await page.getByTestId('compare-search-popover').getByText('Valheim', { exact: false }).first().click()
    await expect(page).toHaveURL(/appids=440.*892970|appids=892970.*440/)
  })

  test('free tier: pro metrics blurred behind single gate', async ({ page }) => {
    test.skip(IS_PRO, 'Only runs when Pro flag is off')
    await page.goto('/compare?appids=440,892970')
    await expect(page.getByTestId('compare-pro-gate')).toBeVisible()
    await expect(page.getByTestId('compare-pro-gate')).toContainText(/Unlock/i)
    // Radar + promise gap diff should NOT render for free users
    await expect(page.getByTestId('compare-radar')).toHaveCount(0)
    await expect(page.getByTestId('compare-promise-gap-diff')).toHaveCount(0)
  })

  test('free tier: picker capped at 2 games', async ({ page }) => {
    test.skip(IS_PRO, 'Only runs when Pro flag is off')
    await page.goto('/compare?appids=440,892970')
    await expect(page.getByTestId('compare-add-button')).toHaveCount(0)
    await expect(page.getByText(/Add up to 4 games with Pro/i)).toBeVisible()
  })

  test('pro tier: radar + promise gap diff + CSV export render', async ({ page }) => {
    test.skip(!IS_PRO, 'Only runs when Pro flag is on')
    await page.goto('/compare?appids=440,892970')
    await expect(page.getByTestId('compare-radar')).toBeVisible()
    await expect(page.getByTestId('compare-promise-gap-diff')).toBeVisible()
    const exportBtn = page.getByTestId('compare-export-csv')
    await expect(exportBtn).toBeVisible()
    const downloadPromise = page.waitForEvent('download')
    await exportBtn.click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toMatch(/steampulse-compare.*\.csv$/)
  })

  test('who-wins-where narrative renders game names and scores', async ({ page }) => {
    await page.goto('/compare?appids=440,892970')
    const summary = page.getByTestId('compare-wins-summary')
    await expect(summary).toBeVisible()
    await expect(summary).toContainText('Team Fortress 2')
    await expect(summary).toContainText('Valheim')
  })

  test('empty prompt shown even with a single appid selected', async ({ page }) => {
    // Regression: previously the lens rendered nothing when exactly 1 appid
    // was selected because the prompt was gated on !loading.
    await page.goto('/compare?appids=440')
    await expect(page.getByTestId('compare-empty-prompt')).toBeVisible()
  })

  test('URL normalizes duplicates and over-cap entries', async ({ page }) => {
    test.skip(IS_PRO, 'URL cap is only enforced in free mode at 2 games')
    // Duplicates + over-cap: dedupe to [440, 892970], drop the rest.
    await page.goto('/compare?appids=440,440,892970,9999999')
    await page.waitForURL(/appids=440(%2C|,)892970(?!\d)/)
    // Only two pills rendered
    await expect(page.getByTestId('compare-pill-440')).toBeVisible()
    await expect(page.getByTestId('compare-pill-892970')).toBeVisible()
    await expect(page.getByTestId('compare-pill-9999999')).toHaveCount(0)
  })

  test('game report page has Compare deep-link pointing to /compare', async ({ page }) => {
    await page.goto('/games/440/team-fortress-2')
    const link = page.getByTestId('game-compare-deeplink')
    await expect(link).toBeVisible()
    await expect(link).toHaveAttribute('href', '/compare?appids=440')
  })
})
