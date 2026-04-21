import { test, expect } from '@playwright/test'

// Server-side fetches in Next.js bypass Playwright's page.route() — they hit
// the mock API server at tests/mock-api-server.mjs instead. State is driven
// by the slug:
//   rdb-base     → insights 200, report 404
//   rdb-preorder → insights 200, report 200 (pre-order)
//   rdb-live     → insights 200, report 200 (live)
//   rdb-missing  → insights 404 (triggers Next.js notFound)

test.describe('Genre synthesis page — no report', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/genre/rdb-base')
  })

  test('renders headline, byline, editorial intro, and meta line', async ({ page }) => {
    await expect(
      page.getByRole('heading', { level: 1, name: /Players Want, Hate, and Praise/i }),
    ).toBeVisible()
    await expect(page.getByTestId('author-byline')).toBeVisible()
    await expect(page.getByText(/hand-written editorial intro/i)).toBeVisible()
    await expect(page.getByText(/Synthesised from 141 games/i)).toBeVisible()
  })

  test('renders exactly 5 friction points with mention counts', async ({ page }) => {
    const friction = page.getByTestId('friction-list')
    await expect(friction).toBeVisible()
    await expect(friction.locator('ol > li')).toHaveCount(5)
    await expect(friction).toContainText('Run length too long')
    await expect(friction).toContainText('18 of 141 games')
  })

  test('renders exactly 3 wishlist items', async ({ page }) => {
    const wishlist = page.getByTestId('wishlist-list')
    await expect(wishlist).toBeVisible()
    await expect(wishlist.locator('ol > li')).toHaveCount(3)
    await expect(wishlist).toContainText('Daily shared seed')
  })

  test('renders exactly 3 benchmark cards with links to game pages', async ({ page }) => {
    const grid = page.getByTestId('benchmark-grid')
    await expect(grid).toBeVisible()
    await expect(grid).toContainText('Slay the Spire')
    await expect(grid).toContainText('Balatro')
    await expect(grid).toContainText('Monster Train')
    await expect(grid.locator('a[href="/games/646570/slay-the-spire"]')).toBeVisible()
  })

  test('churn wall shows stat, reason, and editorial interpretation (no blockquote)', async ({ page }) => {
    const wall = page.getByTestId('churn-wall')
    await expect(wall).toBeVisible()
    await expect(page.getByTestId('churn-wall-stat')).toContainText('~8h')
    await expect(wall).toContainText('Unlock grind between runs')
    await expect(page.getByTestId('churn-wall-interpretation')).toBeVisible()
    await expect(wall.locator('blockquote')).toHaveCount(0)
  })

  test('dev priorities teaser renders 2 rows', async ({ page }) => {
    const teaser = page.getByTestId('dev-priorities')
    await expect(teaser).toBeVisible()
    await expect(teaser.locator('tbody > tr')).toHaveCount(2)
  })

  test('methodology footer is the anchor target for the byline link', async ({ page }) => {
    await expect(page.getByTestId('methodology-footer')).toBeVisible()
    await expect(page.locator('section#methodology')).toBeVisible()
    const bylineHref = await page.getByTestId('author-byline').locator('a').getAttribute('href')
    expect(bylineHref).toBe('#methodology')
  })

  test('buy block and "in the PDF" teasers hidden when no report exists', async ({ page }) => {
    await expect(page.getByTestId('report-buy-block-main')).toHaveCount(0)
    await expect(page.getByTestId('report-buy-block-sidebar')).toHaveCount(0)
    // The PDF teasers anchor to #buy — with no buy block on the page, they
    // would be broken in-page links. They must not render.
    await expect(page.locator('a[href="#buy"]')).toHaveCount(0)
  })
})

test.describe('Genre synthesis page — pre-order report', () => {
  test('buy block renders in pre-order state with ship date', async ({ page }) => {
    await page.goto('/genre/rdb-preorder')
    const block = page.getByTestId('report-buy-block-main')
    await expect(block).toBeVisible()
    await expect(block).toHaveAttribute('data-state', 'pre-order')
    await expect(block).toContainText('Pre-order Indie')
    await expect(block).toContainText('Pre-order Studio')
    await expect(block).toContainText('Pre-order Publisher')
    await expect(block).toContainText(/ships/i)
  })

  test('PDF teaser CTAs render and anchor to #buy', async ({ page }) => {
    await page.goto('/genre/rdb-preorder')
    await expect(
      page.getByTestId('friction-list').locator('a[href="#buy"]'),
    ).toContainText(/more friction clusters/i)
    await expect(
      page.getByTestId('wishlist-list').locator('a[href="#buy"]'),
    ).toContainText(/wishlist items are in the PDF/i)
    await expect(
      page.getByTestId('benchmark-grid').locator('a[href="#buy"]'),
    ).toContainText(/more benchmark games/i)
    await expect(
      page.getByTestId('dev-priorities').locator('a[href="#buy"]'),
    ).toBeVisible()
  })
})

test.describe('Genre synthesis page — live report', () => {
  test('buy block renders in live state with Buy buttons', async ({ page }) => {
    await page.goto('/genre/rdb-live')
    const block = page.getByTestId('report-buy-block-main')
    await expect(block).toBeVisible()
    await expect(block).toHaveAttribute('data-state', 'live')
    await expect(block).toContainText('Buy Indie')
    await expect(block).toContainText(/available now/i)
  })
})

test.describe('Genre synthesis page — 404', () => {
  test('unknown slug 404s cleanly', async ({ page }) => {
    const response = await page.goto('/genre/rdb-missing')
    expect(response?.status()).toBe(404)
  })
})
