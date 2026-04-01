import { Page } from '@playwright/test'
import {
  MOCK_GAMES_LIST, MOCK_GENRES, MOCK_TAGS,
  MOCK_REPORT, MOCK_GAME_ANALYZED, MOCK_GAME_UNANALYZED,
  MOCK_REVIEW_STATS, MOCK_BENCHMARKS,
  MOCK_RELEASE_VOLUME, MOCK_SENTIMENT_DIST, MOCK_GENRE_SHARE,
  MOCK_VELOCITY_DIST, MOCK_PRICING, MOCK_EARLY_ACCESS,
  MOCK_PLATFORMS, MOCK_ENGAGEMENT, MOCK_CATEGORIES,
} from './mock-data'

export async function mockAnalyticsRoutes(page: Page) {
  await page.route('**/api/analytics/trends/release-volume**', route =>
    route.fulfill({ json: MOCK_RELEASE_VOLUME })
  )
  await page.route('**/api/analytics/trends/sentiment**', route =>
    route.fulfill({ json: MOCK_SENTIMENT_DIST })
  )
  await page.route('**/api/analytics/trends/genre-share**', route =>
    route.fulfill({ json: MOCK_GENRE_SHARE })
  )
  await page.route('**/api/analytics/trends/velocity**', route =>
    route.fulfill({ json: MOCK_VELOCITY_DIST })
  )
  await page.route('**/api/analytics/trends/pricing**', route =>
    route.fulfill({ json: MOCK_PRICING })
  )
  await page.route('**/api/analytics/trends/early-access**', route =>
    route.fulfill({ json: MOCK_EARLY_ACCESS })
  )
  await page.route('**/api/analytics/trends/platforms**', route =>
    route.fulfill({ json: MOCK_PLATFORMS })
  )
  await page.route('**/api/analytics/trends/engagement**', route =>
    route.fulfill({ json: MOCK_ENGAGEMENT })
  )
  await page.route('**/api/analytics/trends/categories**', route =>
    route.fulfill({ json: MOCK_CATEGORIES })
  )
}

export async function mockAllApiRoutes(page: Page) {
  // Register wildcard routes FIRST — Playwright uses LIFO so routes registered
  // LAST win. Specific routes are registered after the wildcard so they take
  // priority.

  // Games list — wildcard fallback for all other /api/games requests
  await page.route('**/api/games**', route =>
    route.fulfill({ json: MOCK_GAMES_LIST })
  )

  // Genres
  await page.route('**/api/genres**', route =>
    route.fulfill({ json: MOCK_GENRES })
  )

  // Tags
  await page.route('**/api/tags/**', route =>
    route.fulfill({ json: MOCK_TAGS })
  )

  // Preview (fallback)
  await page.route('**/api/preview', route =>
    route.fulfill({
      json: {
        game_name: MOCK_GAME_ANALYZED.name,
        overall_sentiment: 'Overwhelmingly Positive',
        sentiment_score: 87,
        one_liner: MOCK_REPORT.one_liner,
      },
    })
  )

  // Review stats and benchmarks — specific routes registered LAST (higher LIFO priority)
  await page.route('**/api/games/*/review-stats', route =>
    route.fulfill({ json: MOCK_REVIEW_STATS })
  )

  await page.route('**/api/games/*/benchmarks', route =>
    route.fulfill({ json: MOCK_BENCHMARKS })
  )

  // Specific game report routes — registered LAST so they win over wildcard
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
          genres: MOCK_GAME_ANALYZED.genres,
          tags: MOCK_GAME_ANALYZED.tags,
          deck_compatibility: MOCK_GAME_ANALYZED.deck_compatibility,
          deck_test_results: MOCK_GAME_ANALYZED.deck_test_results,
        },
      },
    })
  )

  await page.route('**/api/games/9999999/report', route =>
    route.fulfill({
      json: {
        status: 'not_available',
        review_count: 42,
        game: {
          short_desc: MOCK_GAME_UNANALYZED.short_desc,
          developer: MOCK_GAME_UNANALYZED.developer,
          release_date: MOCK_GAME_UNANALYZED.release_date,
          price_usd: 9.99,
          is_free: false,
          deck_compatibility: MOCK_GAME_UNANALYZED.deck_compatibility,
          deck_test_results: MOCK_GAME_UNANALYZED.deck_test_results,
        },
      },
    })
  )

  await mockAnalyticsRoutes(page)
}
