import { Page } from '@playwright/test'
import {
  MOCK_GAMES_LIST, MOCK_GENRES, MOCK_TAGS,
  MOCK_REPORT, MOCK_GAME_ANALYZED, MOCK_GAME_UNANALYZED,
} from './mock-data'

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
        },
      },
    })
  )

  await page.route('**/api/games/9999999/report', route =>
    route.fulfill({
      json: {
        status: 'not_available',
        review_count: 42,
        threshold: 500,
        game: {
          short_desc: MOCK_GAME_UNANALYZED.short_desc,
          developer: MOCK_GAME_UNANALYZED.developer,
          release_date: MOCK_GAME_UNANALYZED.release_date,
          price_usd: 9.99,
          is_free: false,
        },
      },
    })
  )
}
