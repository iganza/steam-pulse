import { test, expect } from '@playwright/test'
import { MOCK_GENRE_SYNTHESIS } from './fixtures/mock-data'

// This page is a server component — fetches resolve via the mock API server
// on :3001, not via page.route(). To avoid Next.js ISR caching bleeding state
// across tests, each report-block scenario navigates to a distinct slug and
// the mock server responds deterministically based on that slug.

const SLUG_CORE = 'roguelike-deckbuilder'
const SLUG_PREORDER = 'rdb-preorder'
const SLUG_LIVE = 'rdb-live'
const SLUG_UNSEEDED = 'unseeded-genre-slug'

test.describe('Genre synthesis page — core sections', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`/genre/${SLUG_CORE}`)
  })

  test('renders the synthesis h1 and narrative summary', async ({ page }) => {
    await expect(
      page.getByRole('heading', {
        level: 1,
        name: /what roguelike deckbuilder players want, hate, and praise/i,
      }),
    ).toBeVisible()
    const firstNarrativeChunk = MOCK_GENRE_SYNTHESIS.narrative_summary.slice(0, 40)
    await expect(page.getByText(firstNarrativeChunk)).toBeVisible()
  })

  test('meta line reports game and review counts', async ({ page }) => {
    await expect(
      page.getByText(/synthesised from 141 games.*median 2,100 reviews/i),
    ).toBeVisible()
  })

  test('renders all 10 friction points with mention-count badges', async ({ page }) => {
    const section = page.getByRole('region', { name: /top 10 friction points/i })
    await expect(section).toBeVisible()
    const items = section.locator('ol > li')
    await expect(items).toHaveCount(10)
    await expect(section.getByText('42 of 141 games')).toBeVisible()
  })

  test('renders all 10 wishlist items', async ({ page }) => {
    const section = page.getByRole('region', { name: /top 10 wishlist features/i })
    const items = section.locator('ol > li')
    await expect(items).toHaveCount(10)
  })

  test('renders 5 benchmark game cards with cover images and links', async ({ page }) => {
    const section = page.getByRole('region', { name: /benchmark games/i })
    const cards = section.locator('ul > li')
    await expect(cards).toHaveCount(5)
    const firstLink = cards.first().locator('a').first()
    const href = await firstLink.getAttribute('href')
    expect(href).toMatch(/^\/games\/\d+\//)
    await expect(cards.first().locator('img').first()).toBeVisible()
  })

  test('churn wall renders the typical drop-off number', async ({ page }) => {
    const section = page.getByRole('region', { name: /the churn wall/i })
    await expect(section).toBeVisible()
    await expect(section.getByText(/~4 hours/i)).toBeVisible()
    await expect(
      section.getByText(/lost three runs to opening hands/i),
    ).toBeVisible()
  })

  test('dev priorities table renders every row', async ({ page }) => {
    const section = page.getByRole('region', { name: /dev priorities/i })
    const dataRows = section.locator('tbody tr')
    await expect(dataRows).toHaveCount(5)
  })

  test('methodology footer displays', async ({ page }) => {
    await expect(
      page.getByRole('heading', { name: /how this page is built/i }),
    ).toBeVisible()
    await expect(page.getByText(/feedback@steampulse\.io/i)).toBeVisible()
  })

  test('emits Article JSON-LD with the genre display name', async ({ page }) => {
    // The root layout emits its own JSON-LD (WebSite + Organization) — scan
    // all scripts and pick the Article entry this page is responsible for.
    const scripts = page.locator('script[type="application/ld+json"]')
    const count = await scripts.count()
    let articleData: Record<string, unknown> | null = null
    for (let i = 0; i < count; i++) {
      const text = await scripts.nth(i).textContent()
      if (!text) continue
      const data = JSON.parse(text)
      if (data['@type'] === 'Article') {
        articleData = data
        break
      }
    }
    expect(articleData).not.toBeNull()
    expect((articleData!.about as { name?: string })?.name).toBe('Roguelike Deckbuilder')
  })
})

test.describe('Genre synthesis page — report block states', () => {
  test('pre-order block shows Pre-order buttons and ship date', async ({ page }) => {
    await page.goto(`/genre/${SLUG_PREORDER}`)
    await expect(
      page.getByRole('button', { name: /pre-order indie/i }).first(),
    ).toBeVisible()
    await expect(page.getByText(/ships .+2099/i).first()).toBeVisible()
  })

  test('live block shows Buy buttons and available-now copy', async ({ page }) => {
    await page.goto(`/genre/${SLUG_LIVE}`)
    await expect(
      page.getByRole('button', { name: /^buy indie$/i }).first(),
    ).toBeVisible()
    await expect(page.getByText(/available now/i).first()).toBeVisible()
  })

  test('no-report state omits the commerce block entirely', async ({ page }) => {
    await page.goto(`/genre/${SLUG_CORE}`)
    await expect(
      page.getByRole('button', { name: /pre-order|^buy /i }),
    ).toHaveCount(0)
    await expect(page.getByText(/print-ready report/i)).toHaveCount(0)
  })
})

test.describe('Genre synthesis page — 404 state', () => {
  test('unknown slug returns Next.js 404', async ({ page }) => {
    const response = await page.goto(`/genre/${SLUG_UNSEEDED}`)
    expect(response?.status()).toBe(404)
  })
})
