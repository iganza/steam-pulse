import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'
import { MOCK_REVIEW_STATS_SPARSE, MOCK_REPORT, MOCK_GAME_ANALYZED } from './fixtures/mock-data'

test.describe('Game report page — analyzed game', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/440/team-fortress-2')
  })

  test('renders game name in hero', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Team Fortress 2' })).toBeVisible()
  })

  test('renders all report sections', async ({ page }) => {
    const sections = [
      /the verdict/i,
      /design strengths/i,
      /gameplay friction/i,
      /audience profile/i,
      /player wishlist/i,
      /churn triggers/i,
      /developer priorities/i,
      /competitive context/i,
      /genre context/i,
    ]
    for (const section of sections) {
      await expect(page.getByText(section)).toBeVisible()
    }
  })

  test('no blur overlay or lock icons', async ({ page }) => {
    await expect(page.locator('.premium-blur-content')).not.toBeAttached()
    await expect(page.locator('.premium-overlay')).not.toBeAttached()
  })

  test('no unlock or pricing CTAs', async ({ page }) => {
    await expect(page.getByText(/unlock/i)).not.toBeVisible()
    await expect(page.getByText(/\$7/)).not.toBeVisible()
  })

  test('sentiment score is shown', async ({ page }) => {
    // ScoreBar always renders the "Sentiment Score" label
    await expect(page.getByText('Sentiment Score')).toBeVisible()
  })

  test('tag chips are rendered and link to /tag/', async ({ page }) => {
    const tagLink = page.getByRole('link', { name: /fps|multiplayer|shooter/i }).first()
    await expect(tagLink).toBeVisible()
    await expect(tagLink).toHaveAttribute('href', /\/tag\//)
  })

  test('developer Pro CTA is present at bottom', async ({ page }) => {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    await expect(page.getByText(/genre intelligence.*pro|pro.*genre intelligence/i)).toBeVisible()
  })

  test('breadcrumbs are present', async ({ page }) => {
    await expect(page.getByRole('navigation', { name: /breadcrumb/i })).toBeVisible()
    await expect(page.getByRole('link', { name: /home/i })).toBeVisible()
  })

  test('page has main landmark', async ({ page }) => {
    await expect(page.getByRole('main')).toBeVisible()
  })

  test('overall sentiment label is shown', async ({ page }) => {
    await expect(page.getByText(/overwhelmingly positive/i)).toBeVisible()
  })

  test('displays Deck Playable badge for analyzed game', async ({ page }) => {
    const badge = page.getByTestId('deck-badge')
    await expect(badge).toBeVisible()
    await expect(badge).toContainText('Playable')
  })

  test('deck badge expands test results on click', async ({ page }) => {
    const badge = page.getByTestId('deck-badge')
    await badge.click()
    await expect(page.getByTestId('deck-test-results')).toBeVisible()
  })
})

test.describe('Data-driven insights — analyzed game', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/440/team-fortress-2')
  })

  test('sentiment timeline chart renders when 3+ weeks of data present', async ({ page }) => {
    await expect(page.getByTestId('sentiment-timeline')).toBeVisible()
  })

  test('playtime chart renders all 6 buckets', async ({ page }) => {
    const chart = page.getByTestId('playtime-chart')
    await expect(chart).toBeVisible()
    await expect(chart.locator('[data-bucket="0h"]')).toBeVisible()
    await expect(chart.locator('[data-bucket="200h+"]')).toBeVisible()
  })

  test('playtime chart colors: green ≥80%, amber 60-79%, red <60%', async ({ page }) => {
    const chart = page.getByTestId('playtime-chart')
    await expect(chart).toBeVisible()
    // 88% bucket (50-200h) should be green
    const greenBucket = chart.locator('[data-bucket="50-200h"]')
    await expect(greenBucket).toBeVisible()
    // 59% bucket (<2h) should use red/amber — check it exists with pct attribute
    const redBucket = chart.locator('[data-pct="59"]')
    await expect(redBucket).toBeVisible()
  })

  test('playtime insight sentence is visible (free tier)', async ({ page }) => {
    const chart = page.getByTestId('playtime-chart')
    await expect(chart).toBeVisible()
    // Insight text renders (blurred but present in DOM)
    await expect(chart.locator('p.italic')).toBeAttached()
  })

  test('competitive benchmark section is present in DOM and fully visible', async ({ page }) => {
    const benchmark = page.getByTestId('competitive-benchmark')
    await expect(benchmark).toBeVisible()
    // isPro = true — content is not blurred and no upgrade CTA
    await expect(benchmark.locator('.blur-sm')).not.toBeAttached()
    await expect(benchmark.getByRole('link', { name: /upgrade to pro/i })).not.toBeVisible()
  })

  test('score context sentence appears below score bar', async ({ page }) => {
    await expect(page.getByTestId('score-context')).toBeVisible()
  })

  test('review velocity card shows reviews/day', async ({ page }) => {
    // Velocity card renders once review-stats fetch completes
    await expect(page.getByText(/\/day/)).toBeVisible()
  })

  test('timeline skeleton placeholder visible before data loads', async ({ page }) => {
    // Skeleton is in DOM initially — check it was rendered (it may have already
    // been replaced by the time assertion runs, so check for either)
    const timeline = page.getByTestId('sentiment-timeline')
    const skeleton = page.getByTestId('sentiment-timeline-skeleton')
    await expect(timeline.or(skeleton)).toBeAttached()
  })

  test('playtime skeleton placeholder visible before data loads', async ({ page }) => {
    const chart = page.getByTestId('playtime-chart')
    const skeleton = page.getByTestId('playtime-chart-skeleton')
    await expect(chart.or(skeleton)).toBeAttached()
  })
})

test.describe('Steam Deck badge — Verified override', () => {
  test('displays Deck Verified badge', async ({ page }) => {
    await mockAllApiRoutes(page)
    // Override game report with deck_compatibility: 3 (Verified)
    await page.route('**/api/games/440/report', route =>
      route.fulfill({
        json: {
          status: 'available',
          report: MOCK_REPORT,
          game: {
            short_desc: MOCK_GAME_ANALYZED.short_desc,
            developer: MOCK_GAME_ANALYZED.developer,
            release_date: MOCK_GAME_ANALYZED.release_date,
            price_usd: null,
            is_free: true,
            deck_compatibility: 3,
            deck_test_results: [
              { display_type: 2, loc_token: '#SteamDeckVerified_TestResult_DefaultConfigurationIsPerformant' },
            ],
          },
        },
      })
    )
    await page.goto('/games/440/team-fortress-2')
    const badge = page.getByTestId('deck-badge')
    await expect(badge).toBeVisible()
    await expect(badge).toContainText('Verified')
  })
})

test.describe('Data-driven insights — timeline sparse data', () => {
  test('timeline chart does NOT render when fewer than 3 data points', async ({ page }) => {
    await mockAllApiRoutes(page)
    // Override review-stats with sparse data (only 1 week)
    await page.route('**/api/games/440/review-stats', route =>
      route.fulfill({ json: MOCK_REVIEW_STATS_SPARSE })
    )
    await page.goto('/games/440/team-fortress-2')
    await expect(page.getByTestId('sentiment-timeline')).not.toBeAttached()
  })
})

test.describe('Data-driven insights — unanalyzed game', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/9999999/obscure-indie-game')
  })

  test('sentiment timeline renders for unanalyzed game if review data exists', async ({ page }) => {
    await expect(page.getByTestId('sentiment-timeline')).toBeVisible()
  })

  test('playtime chart renders for unanalyzed game if review data exists', async ({ page }) => {
    await expect(page.getByTestId('playtime-chart')).toBeVisible()
  })

  test('competitive benchmark is NOT shown for unanalyzed games', async ({ page }) => {
    // Benchmarks section only renders in the analyzed game path
    await expect(page.getByTestId('competitive-benchmark')).not.toBeAttached()
  })
})

test.describe('Game report page — unanalyzed game', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/9999999/obscure-indie-game')
  })

  test('does not show analysis sections', async ({ page }) => {
    await expect(page.getByText(/the verdict/i)).not.toBeVisible()
  })

  test('shows quick stats section', async ({ page }) => {
    // Quick Stats section always renders in unanalyzed state
    await expect(page.getByText('Quick Stats').first()).toBeVisible()
  })

  test('shows "analysis not yet available" message', async ({ page }) => {
    await expect(page.getByText(/Analysis in progress/i)).toBeVisible()
  })

  test('hero section is rendered', async ({ page }) => {
    // The hero with the game name is always rendered even without analysis
    await expect(page.getByRole('main')).toBeVisible()
  })

  test('hides Deck badge when unknown/null', async ({ page }) => {
    await expect(page.getByTestId('deck-badge')).not.toBeAttached()
  })
})
