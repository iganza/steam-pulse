import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'
import { MOCK_EA_IMPACT_NO_EA, MOCK_PLAYTIME_SENTIMENT_NO_CHURN } from './fixtures/mock-data'

// Game report page — analytics features
test.describe('Game report — analytics features', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/440/team-fortress-2')
  })

  // Audience Overlap
  test('audience overlap shows game names and shared counts', async ({ page }) => {
    await expect(page.getByText(/audience overlap/i)).toBeVisible()
    await expect(page.getByText('Dota 2')).toBeVisible()
    await expect(page.getByText('Counter-Strike 2')).toBeVisible()
    // Shows overlap_count + overlap_pct
    await expect(page.getByText(/342/)).toBeVisible()
    await expect(page.getByText(/6\.3%/)).toBeVisible()
  })

  // Playtime Sentiment
  test('playtime sentiment deep dive section renders', async ({ page }) => {
    await expect(page.getByText(/playtime.*sentiment|sentiment.*playtime/i)).toBeVisible()
    await expect(page.getByText(/median playtime/i)).toBeVisible()
  })

  test('churn wall annotation visible when present', async ({ page }) => {
    await expect(page.getByText(/churn wall/i)).toBeVisible()
  })

  test('no churn wall when churn_point is null', async ({ page }) => {
    await page.route('**/api/games/*/playtime-sentiment', route =>
      route.fulfill({ json: MOCK_PLAYTIME_SENTIMENT_NO_CHURN })
    )
    await page.goto('/games/440/team-fortress-2')
    await expect(page.getByText(/churn wall/i)).not.toBeVisible()
  })

  // Early Access Impact
  test('early access impact shows comparison when EA data exists', async ({ page }) => {
    await expect(page.getByText(/early access/i).first()).toBeVisible()
    await expect(page.getByText(/post-launch/i)).toBeVisible()
  })

  test('early access section hidden when no EA reviews', async ({ page }) => {
    await page.route('**/api/games/*/early-access-impact', route =>
      route.fulfill({ json: MOCK_EA_IMPACT_NO_EA })
    )
    await page.goto('/games/440/team-fortress-2')
    await expect(page.getByText(/post-launch/i)).not.toBeVisible()
  })

  // Review Velocity
  test('review velocity chart renders with trend badge', async ({ page }) => {
    await expect(page.getByText(/review velocity/i)).toBeVisible()
    await expect(page.getByText(/accelerating/i)).toBeVisible()
  })

  // Top Reviews
  test('top reviews renders review cards with content', async ({ page }) => {
    await expect(page.getByText(/masterpiece/i)).toBeVisible()
  })

  test('top reviews show helpful vote counts', async ({ page }) => {
    await expect(page.getByText(/1,?523/)).toBeVisible()
  })
})

// Genre page — market analytics
test.describe('Genre page — market analytics', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/genre/action')
  })

  test('price positioning chart renders with sweet spot', async ({ page }) => {
    await expect(page.getByText(/price positioning/i)).toBeVisible()
    await expect(page.getByText(/sweet spot/i)).toBeVisible()
  })

  test('release timing chart renders with best month', async ({ page }) => {
    await expect(page.getByText(/release timing/i)).toBeVisible()
    await expect(page.getByText(/february/i)).toBeVisible()
  })

  test('platform gaps renders with underserved indicator', async ({ page }) => {
    await expect(page.getByText(/platform/i).first()).toBeVisible()
    await expect(page.getByText(/linux/i)).toBeVisible()
  })
})

// Tag page — tag trend
test.describe('Tag page — tag trend', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/tag/roguelike')
  })

  test('tag trend chart renders with growth stats', async ({ page }) => {
    await expect(page.getByText(/tag trends/i)).toBeVisible()
    await expect(page.getByText(/growth/i)).toBeVisible()
  })

  test('peak year shown', async ({ page }) => {
    await expect(page.getByText(/2023/)).toBeVisible()
  })
})

// Developer page — portfolio analytics
test.describe('Developer page — portfolio analytics', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/developer/valve')
  })

  test('developer portfolio summary renders', async ({ page }) => {
    await expect(page.getByText(/developer analytics/i)).toBeVisible()
  })

  test('developer games list renders with links', async ({ page }) => {
    await expect(page.getByText('Counter-Strike 2')).toBeVisible()
  })
})

// Graceful degradation
test.describe('Analytics — graceful degradation', () => {
  test('game page renders when analytics endpoints fail', async ({ page }) => {
    await mockAllApiRoutes(page)
    for (const ep of ['audience-overlap', 'playtime-sentiment', 'early-access-impact', 'review-velocity', 'top-reviews']) {
      await page.route(`**/api/games/*/${ep}*`, route =>
        route.fulfill({ status: 500, body: 'error' })
      )
    }
    await page.goto('/games/440/team-fortress-2')
    await expect(page.getByRole('heading', { name: 'Team Fortress 2' })).toBeVisible()
  })

  test('genre page renders when analytics endpoints fail', async ({ page }) => {
    await mockAllApiRoutes(page)
    for (const ep of ['price-positioning', 'release-timing', 'platform-gaps']) {
      await page.route(`**/api/analytics/${ep}*`, route =>
        route.fulfill({ status: 500, body: 'error' })
      )
    }
    await page.goto('/genre/action')
    await expect(page.getByText(/action/i).first()).toBeVisible()
  })
})
