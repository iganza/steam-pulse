import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'
import { MOCK_GAME_UNANALYZED } from './fixtures/mock-data'

// Soft-launch SEO discipline: every per-game page must be index-worthy even
// when there's no LLM-synthesized report. These specs characterize the
// no-report rendering so we don't regress the structured-data floor that
// Google crawls on the ~6000 games in the long tail.

const NO_REPORT_URL = '/games/9999999/obscure-indie-game'

const LLM_ONLY_HEADINGS = [
  /^the verdict$/i,
  /^design strengths$/i,
  /^gameplay friction$/i,
  /^audience profile$/i,
  /^player wishlist$/i,
  /^churn triggers$/i,
  /^developer priorities$/i,
  /^competitive context$/i,
  /^genre context$/i,
  /^sentiment trend$/i,
  /^promise gap$/i,
]

test.describe('Game page — no-report state, rich data variant', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto(NO_REPORT_URL)
  })

  test('LLM-only section headings are absent from the DOM', async ({ page }) => {
    for (const heading of LLM_ONLY_HEADINGS) {
      await expect(
        page.getByRole('heading', { name: heading }),
      ).toHaveCount(0)
    }
  })

  test('GameAnalyticsSection renders with overlap, top reviews, velocity, playtime, EA impact', async ({ page }) => {
    // The "Deep Dive Analytics" block is the ungated section. With
    // mockPerEntityAnalyticsRoutes returning populated fixtures, every
    // sub-chart should surface.
    await expect(page.getByText(/deep dive analytics/i)).toBeVisible()
    await expect(page.getByText(/audience overlap/i)).toBeVisible()
    await expect(page.getByText(/review velocity/i)).toBeVisible()
    await expect(page.getByText(/playtime.*sentiment|sentiment.*playtime/i)).toBeVisible()
    await expect(page.getByText(/early access/i).first()).toBeVisible()
    // Top reviews surface — assert a fragment from MOCK_TOP_REVIEWS body.
    await expect(page.getByText(/masterpiece/i)).toBeVisible()
  })

  test('competitive benchmark renders when cohort >= 10', async ({ page }) => {
    // MOCK_BENCHMARKS.cohort_size = 312 — comfortably above the threshold.
    await expect(page.getByTestId('competitive-benchmark')).toBeVisible()
  })

  test('Steam-sourced charts (sentiment history, playtime) render', async ({ page }) => {
    await expect(page.getByTestId('sentiment-timeline')).toBeVisible()
    await expect(page.getByTestId('playtime-chart')).toBeVisible()
  })

  test('RequestAnalysis CTA is still shown (only on no-report path)', async ({ page }) => {
    await expect(page.getByText(/hasn.?t been analyzed yet/i)).toBeVisible()
  })
})

test.describe('Game page — no-report state, thin data variant', () => {
  // Thin variant: no review-stats, no audience overlap, no top reviews, no
  // velocity, no EA impact, benchmark cohort too small. These sections MUST
  // all cleanly hide — no empty section headers in the DOM.
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    // Register thin overrides AFTER mockAllApiRoutes so Playwright LIFO
    // makes them win for 9999999 specifically.
    await page.route('**/api/games/9999999/review-stats', route =>
      route.fulfill({
        json: {
          timeline: [],
          playtime_buckets: [],
          review_velocity: { reviews_per_day: 0, reviews_last_30_days: 0 },
        },
      }),
    )
    await page.route('**/api/games/9999999/benchmarks', route =>
      route.fulfill({
        json: { sentiment_rank: null, popularity_rank: null, cohort_size: 3 },
      }),
    )
    await page.route('**/api/games/9999999/audience-overlap*', route =>
      route.fulfill({ json: { total_reviewers: 0, overlaps: [] } }),
    )
    await page.route('**/api/games/9999999/top-reviews*', route =>
      route.fulfill({ json: { sort: 'helpful', reviews: [] } }),
    )
    await page.route('**/api/games/9999999/review-velocity', route =>
      route.fulfill({
        json: {
          monthly: [],
          summary: {
            avg_monthly: 0,
            last_30_days: 0,
            last_3_months_avg: 0,
            peak_month: null,
            trend: 'stable',
          },
        },
      }),
    )
    await page.route('**/api/games/9999999/playtime-sentiment', route =>
      route.fulfill({
        json: { buckets: [], churn_point: null, median_playtime_hours: 0, value_score: null },
      }),
    )
    await page.route('**/api/games/9999999/early-access-impact', route =>
      route.fulfill({
        json: {
          has_ea_reviews: false,
          early_access: null,
          post_launch: null,
          impact_delta: null,
          verdict: 'no_ea',
        },
      }),
    )
    await page.goto(NO_REPORT_URL)
  })

  test('Sentiment History heading is absent when timeline is thin', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /sentiment history/i })).toHaveCount(0)
  })

  test('Playtime Sentiment heading is absent when bucket total < 50', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /playtime sentiment/i })).toHaveCount(0)
  })

  test('Competitive Benchmark heading is absent when cohort < 10', async ({ page }) => {
    await expect(page.getByTestId('competitive-benchmark')).toHaveCount(0)
  })

  test('Deep Dive Analytics block cleanly hides when all endpoints empty', async ({ page }) => {
    // GameAnalyticsSection's `!hasData` early-return should collapse the
    // whole "Deep Dive Analytics" label + children to nothing.
    await expect(page.getByText(/deep dive analytics/i)).toHaveCount(0)
  })

  test('Steam Facts and Quick Stats still render (Steam-sourced, independent)', async ({ page }) => {
    await expect(page.getByText(/^steam facts$/i)).toBeVisible()
    await expect(page.getByText(/^quick stats$/i).first()).toBeVisible()
  })
})

test.describe('Game page — no-report state, JSON-LD schema enrichment', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto(NO_REPORT_URL)
  })

  test('VideoGame schema includes aggregateRating, offers, author, publisher', async ({ page }) => {
    const jsonLd = await page.locator('script[type="application/ld+json"]').textContent()
    expect(jsonLd).toBeTruthy()
    const data = JSON.parse(jsonLd!)

    expect(data['@type']).toBe('VideoGame')

    // aggregateRating from Steam's positive_pct — not from the LLM.
    expect(data.aggregateRating).toBeDefined()
    expect(data.aggregateRating['@type']).toBe('AggregateRating')
    expect(Number(data.aggregateRating.ratingValue)).toBeCloseTo(
      MOCK_GAME_UNANALYZED.positive_pct / 10,
      1,
    )
    expect(data.aggregateRating.ratingCount).toBe(
      String(MOCK_GAME_UNANALYZED.review_count),
    )

    // offers — present because MOCK_GAME_UNANALYZED is paid ($9.99, not free).
    expect(data.offers).toBeDefined()
    expect(data.offers['@type']).toBe('Offer')
    expect(data.offers.priceCurrency).toBe('USD')
    expect(data.offers.price).toBe('9.99')
    expect(data.offers.availability).toBe('https://schema.org/InStock')

    // author = developer, publisher may be absent (fixture has developer
    // only). Assert author is populated at minimum.
    expect(data.author).toBeDefined()
    expect(data.author['@type']).toBe('Organization')
    expect(data.author.name).toBe(MOCK_GAME_UNANALYZED.developer)
  })
})
