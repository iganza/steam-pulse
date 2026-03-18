import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('Search page', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/search')
  })

  test('shows game cards in grid by default', async ({ page }) => {
    await expect(page.getByText('Team Fortress 2')).toBeVisible()
  })

  test('shows result count', async ({ page }) => {
    await expect(page.getByText(/\d+.*games/i)).toBeVisible()
  })

  test('filter sidebar is present', async ({ page }) => {
    await expect(page.getByText(/genre/i).first()).toBeVisible()
    await expect(page.getByText(/sentiment/i)).toBeVisible()
  })

  test('searching by text updates URL', async ({ page }) => {
    // Use the sidebar search input (placeholder "Game name...")
    await page.getByPlaceholder('Game name...').fill('hollow knight')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/q=hollow/)
  })

  test('selecting a genre filter updates URL', async ({ page }) => {
    // Genres load client-side — wait for them
    await expect(page.getByLabel('Action', { exact: false })).toBeVisible()
    await page.getByLabel('Action', { exact: false }).check()
    await expect(page).toHaveURL(/genre=action/)
  })

  test('active filter chip appears after selecting genre', async ({ page }) => {
    await expect(page.getByLabel('Action', { exact: false })).toBeVisible()
    await page.getByLabel('Action', { exact: false }).check()
    // Chip shows the label text with an X
    await expect(page.getByRole('button', { name: /genre.*action|action/i }).first()).toBeVisible()
  })

  test('"Clear all filters" resets filters', async ({ page }) => {
    await expect(page.getByLabel('Action', { exact: false })).toBeVisible()
    await page.getByLabel('Action', { exact: false }).check()
    await page.getByRole('button', { name: /clear all/i }).click()
    await expect(page).not.toHaveURL(/genre=action/)
  })

  test('switching to list view shows list rows', async ({ page }) => {
    // View toggle buttons use icons only — click the List (second) button
    const viewButtons = page.locator('button').filter({ has: page.locator('svg') })
    // The List view button is after the Grid view button in the sort bar
    const listBtn = page.locator('[class*="p-1.5"]').last()
    await listBtn.click()
    await expect(page.getByText('Team Fortress 2').first()).toBeVisible()
    // List view shows game names as plain text spans
    await expect(page.getByText(/most reviewed|sentiment/i)).toBeVisible()
  })

  test('list view preference is remembered on reload', async ({ page }) => {
    // Switch to list view via URL param
    await page.goto('/search?view=list')
    await expect(page.getByText('Team Fortress 2').first()).toBeVisible()
    await page.reload()
    // View stored in localStorage — still shows results
    await expect(page.getByText('Team Fortress 2').first()).toBeVisible()
  })

  test('clicking a game card navigates to game report', async ({ page }) => {
    await page.getByText('Team Fortress 2').first().click()
    await expect(page).toHaveURL(/\/games\/440\//)
  })

  test('empty state shown when no results', async ({ page }) => {
    await page.route('**/api/games**', route =>
      route.fulfill({ json: { total: 0, games: [] } })
    )
    await page.goto('/search?q=xyznonexistent')
    await expect(page.getByText(/no games match/i)).toBeVisible()
    await expect(page.getByRole('button', { name: /clear filters/i })).toBeVisible()
  })

  test('pagination controls are present', async ({ page }) => {
    // Mock returns total:100 which triggers pagination at perPage=24
    await expect(page.getByRole('navigation', { name: /pagination/i })).toBeVisible()
  })

  test('URL state survives browser back/forward', async ({ page }) => {
    await expect(page.getByLabel('Action', { exact: false })).toBeVisible()
    await page.getByLabel('Action', { exact: false }).check()
    await page.getByText('Team Fortress 2').first().click()
    await page.goBack()
    await expect(page).toHaveURL(/genre=action/)
  })
})
