import { Page } from '@playwright/test'
import {
  MOCK_GAMES_LIST, MOCK_GENRES, MOCK_TAGS,
  MOCK_REPORT, MOCK_GAME_ANALYZED, MOCK_GAME_UNANALYZED,
  MOCK_REVIEW_STATS, MOCK_BENCHMARKS,
  MOCK_RELEASE_VOLUME, MOCK_SENTIMENT_DIST, MOCK_GENRE_SHARE,
  MOCK_VELOCITY_DIST, MOCK_PRICING, MOCK_EARLY_ACCESS,
  MOCK_PLATFORMS, MOCK_ENGAGEMENT, MOCK_CATEGORIES,
  MOCK_AUDIENCE_OVERLAP, MOCK_PLAYTIME_SENTIMENT, MOCK_EA_IMPACT,
  MOCK_REVIEW_VELOCITY, MOCK_TOP_REVIEWS, MOCK_PRICE_POSITIONING,
  MOCK_RELEASE_TIMING, MOCK_PLATFORM_GAPS, MOCK_TAG_TREND,
  MOCK_DEVELOPER_PORTFOLIO,
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

export async function mockPerEntityAnalyticsRoutes(page: Page) {
  await page.route('**/api/games/*/audience-overlap*', route =>
    route.fulfill({ json: MOCK_AUDIENCE_OVERLAP })
  )
  await page.route('**/api/games/*/playtime-sentiment', route =>
    route.fulfill({ json: MOCK_PLAYTIME_SENTIMENT })
  )
  await page.route('**/api/games/*/early-access-impact', route =>
    route.fulfill({ json: MOCK_EA_IMPACT })
  )
  await page.route('**/api/games/*/review-velocity', route =>
    route.fulfill({ json: MOCK_REVIEW_VELOCITY })
  )
  await page.route('**/api/games/*/top-reviews*', route =>
    route.fulfill({ json: MOCK_TOP_REVIEWS })
  )
  await page.route('**/api/analytics/price-positioning*', route =>
    route.fulfill({ json: MOCK_PRICE_POSITIONING })
  )
  await page.route('**/api/analytics/release-timing*', route =>
    route.fulfill({ json: MOCK_RELEASE_TIMING })
  )
  await page.route('**/api/analytics/platform-gaps*', route =>
    route.fulfill({ json: MOCK_PLATFORM_GAPS })
  )
  await page.route('**/api/tags/*/trend', route =>
    route.fulfill({ json: MOCK_TAG_TREND })
  )
  await page.route('**/api/developers/*/analytics', route =>
    route.fulfill({ json: MOCK_DEVELOPER_PORTFOLIO })
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

  // New releases — three lenses
  const NEW_RELEASES_ITEMS = [
    {
      appid: 440,
      name: 'Team Fortress 2',
      slug: 'team-fortress-2',
      type: 'game',
      developer: 'Valve',
      developer_slug: 'valve',
      publisher: 'Valve',
      publisher_slug: 'valve',
      header_image: 'https://example.com/tf2.jpg',
      release_date: '2026-04-01',
      coming_soon: false,
      price_usd: 0,
      is_free: true,
      review_count: 5000,
      review_count_english: 4500,
      positive_pct: 92,
      review_score_desc: 'Very Positive',
      discovered_at: '2026-04-01T00:00:00Z',
      meta_crawled_at: '2026-04-01T01:00:00Z',
      metadata_pending: false,
      days_since_release: 7,
      has_analysis: true,
      top_tags: ['FPS', 'Multiplayer', 'Free to Play'],
      top_tag_slugs: ['fps', 'multiplayer', 'free-to-play'],
      genres: ['Action'],
      genre_slugs: ['action'],
    },
    {
      appid: 9999,
      name: 'Pending Game',
      slug: null,
      type: null,
      developer: null,
      developer_slug: null,
      publisher: null,
      publisher_slug: null,
      header_image: null,
      release_date: null,
      coming_soon: false,
      price_usd: null,
      is_free: false,
      review_count: null,
      review_count_english: null,
      positive_pct: null,
      review_score_desc: null,
      discovered_at: '2026-04-08T10:00:00Z',
      meta_crawled_at: null,
      metadata_pending: true,
      days_since_release: null,
      has_analysis: false,
      top_tags: [],
      top_tag_slugs: [],
      genres: [],
      genre_slugs: [],
    },
  ]
  await page.route('**/api/new-releases/released**', route =>
    route.fulfill({
      json: {
        items: [NEW_RELEASES_ITEMS[0]],
        total: 1,
        window: 'week',
        page: 1,
        page_size: 24,
        filters: { genre: null, tag: null },
        counts: { today: 0, week: 1, month: 3, all: 12 },
      },
    }),
  )
  await page.route('**/api/new-releases/upcoming**', route =>
    route.fulfill({
      json: {
        items: [],
        total: 0,
        page: 1,
        page_size: 24,
        filters: { genre: null, tag: null },
        buckets: { this_week: 0, this_month: 0, this_quarter: 0, tba: 0 },
      },
    }),
  )
  await page.route('**/api/new-releases/added**', route =>
    route.fulfill({
      json: {
        items: NEW_RELEASES_ITEMS,
        total: 2,
        window: 'week',
        page: 1,
        page_size: 24,
        filters: { genre: null, tag: null },
        counts: { today: 1, week: 2, month: 5, all: 8 },
      },
    }),
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
  await mockPerEntityAnalyticsRoutes(page)
}
