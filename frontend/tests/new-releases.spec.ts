import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('/new-releases — three-lens feed', () => {
  test('defaults to Released lens with grid + window pills', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/new-releases')
    await expect(page.getByRole('heading', { name: 'New Releases' })).toBeVisible()
    await expect(page.getByTestId('window-pills')).toBeVisible()
    await expect(page.getByTestId('feed-grid')).toBeVisible()
  })

  test('switching to Coming Soon hides window pills and shows buckets', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/new-releases')
    await page.getByTestId('lens-upcoming').click()
    await expect(page).toHaveURL(/lens=upcoming/)
    await expect(page.getByTestId('window-pills')).not.toBeVisible()
    await expect(page.getByTestId('upcoming-buckets')).toBeVisible()
  })

  test('window pill switch updates URL', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/new-releases')
    await page.getByTestId('window-month').click()
    await expect(page).toHaveURL(/window=month/)
  })

  test('Quarter window pill is present and selectable', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/new-releases')
    await expect(page.getByTestId('window-quarter')).toBeVisible()
    await page.getByTestId('window-quarter').click()
    await expect(page).toHaveURL(/window=quarter/)
  })

  test('Just Added lens renders metadata-pending skeleton card', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/new-releases?lens=added')
    await expect(page.getByTestId('pending-metadata-card').first()).toBeVisible()
    await expect(page.getByText('metadata pending', { exact: false }).first()).toBeVisible()
  })

  test('Coming Soon empty state shows friendly message', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/new-releases?lens=upcoming')
    await expect(page.getByTestId('empty-state')).toBeVisible()
  })

  test('lens deep-link works directly', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/new-releases?lens=added&window=today')
    await expect(page.getByTestId('lens-added')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('window-today')).toHaveAttribute('aria-pressed', 'true')
  })

  test('genre filter dropdown updates URL', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/new-releases')
    await page.getByTestId('genre-filter').selectOption({ value: 'action' })
    await expect(page).toHaveURL(/genre=action/)
    await expect(page.getByTestId('clear-filters')).toBeVisible()
  })

  test('tag filter deep-link is reflected in dropdown', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/new-releases?tag=fps')
    await expect(page.getByTestId('tag-filter')).toHaveValue('fps')
  })

  test('clear filters button removes both genre and tag', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/new-releases?genre=action&tag=fps')
    await expect(page.getByTestId('clear-filters')).toBeVisible()
    await page.getByTestId('clear-filters').click()
    await expect(page).not.toHaveURL(/genre=/)
    await expect(page).not.toHaveURL(/tag=/)
  })
})
