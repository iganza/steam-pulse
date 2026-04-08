import { Page } from '@playwright/test'
import {
  MOCK_GAMES_LIST, MOCK_GENRES, MOCK_TAGS, MOCK_TAG_GROUPS,
  MOCK_REPORT, MOCK_REPORT_2, MOCK_GAME_ANALYZED, MOCK_GAME_2, MOCK_GAME_UNANALYZED,
  MOCK_REVIEW_STATS, MOCK_BENCHMARKS,
  MOCK_RELEASE_VOLUME, MOCK_SENTIMENT_DIST, MOCK_GENRE_SHARE,
  MOCK_VELOCITY_DIST, MOCK_PRICING, MOCK_EARLY_ACCESS,
  MOCK_PLATFORMS, MOCK_ENGAGEMENT, MOCK_CATEGORIES,
  MOCK_AUDIENCE_OVERLAP, MOCK_PLAYTIME_SENTIMENT, MOCK_EA_IMPACT,
  MOCK_REVIEW_VELOCITY, MOCK_TOP_REVIEWS, MOCK_PRICE_POSITIONING,
  MOCK_RELEASE_TIMING, MOCK_PLATFORM_GAPS, MOCK_TAG_TREND,
  MOCK_DEVELOPER_PORTFOLIO,
} from './mock-data'

export const MOCK_BUILDER_CATALOG = {
  metrics: [
    {
      id: "releases",
      label: "Releases",
      description: "Number of games released in the period.",
      category: "volume",
      unit: "count",
      source: "trend_matview",
      column: "releases",
      default_chart_hint: "bar",
    },
    {
      id: "free_count",
      label: "Free Releases",
      description: "Number of free-to-play games released.",
      category: "volume",
      unit: "count",
      source: "trend_matview",
      column: "free_count",
      default_chart_hint: "bar",
    },
    {
      id: "avg_steam_pct",
      label: "Avg Steam Positive %",
      description: "Average Steam positive_pct across releases.",
      category: "sentiment",
      unit: "pct",
      source: "trend_matview",
      column: "avg_steam_pct",
      default_chart_hint: "line",
    },
    {
      id: "avg_paid_price",
      label: "Avg Paid Price",
      description: "Average price of non-free releases.",
      category: "pricing",
      unit: "currency",
      source: "trend_matview",
      column: "avg_paid_price",
      default_chart_hint: "line",
    },
  ],
}

function mockTrendQueryPayload(metrics: string[], granularity = "month") {
  const periods = [
    { period: "2024-09", releases: 120, free_count: 22, avg_steam_pct: 78.1, avg_paid_price: 19.99 },
    { period: "2024-10", releases: 140, free_count: 25, avg_steam_pct: 80.2, avg_paid_price: 21.49 },
    { period: "2024-11", releases: 155, free_count: 30, avg_steam_pct: 76.5, avg_paid_price: 18.75 },
    { period: "2024-12", releases: 170, free_count: 34, avg_steam_pct: 79.3, avg_paid_price: 20.99 },
  ]
  const shaped = periods.map((p) => {
    const row: Record<string, number | string> = { period: p.period }
    for (const m of metrics) if (m in p) row[m] = p[m as keyof typeof p]
    return row
  })
  const meta = MOCK_BUILDER_CATALOG.metrics
    .filter((m) => metrics.includes(m.id))
    .map((m) => ({
      id: m.id,
      label: m.label,
      unit: m.unit,
      category: m.category,
      default_chart_hint: m.default_chart_hint,
    }))
  return { granularity, periods: shaped, metrics: meta }
}

export async function mockBuilderRoutes(page: Page) {
  await page.route('**/api/analytics/metrics', route =>
    route.fulfill({ json: MOCK_BUILDER_CATALOG })
  )
  await page.route('**/api/analytics/trend-query**', route => {
    const url = new URL(route.request().url())
    const metrics = (url.searchParams.get('metrics') ?? '').split(',').filter(Boolean)
    const granularity = url.searchParams.get('granularity') ?? 'month'
    route.fulfill({ json: mockTrendQueryPayload(metrics, granularity) })
  })
}

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

  // Tags grouped (LIFO — registered after wildcard so it wins for /api/tags/grouped)
  await page.route('**/api/tags/grouped**', route =>
    route.fulfill({ json: MOCK_TAG_GROUPS })
  )

  // Preview (fallback)
  await page.route('**/api/preview', route =>
    route.fulfill({
      json: {
        game_name: MOCK_GAME_ANALYZED.name,
        review_score_desc: 'Very Positive',
        positive_pct: 87,
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
          // Paid non-free to keep the populated revenue-estimate state
          // below realistic — the backend estimator never produces numeric
          // values for free-to-play games.
          price_usd: 19.99,
          is_free: false,
          is_early_access: false,
          genres: MOCK_GAME_ANALYZED.genres,
          tags: MOCK_GAME_ANALYZED.tags,
          deck_compatibility: MOCK_GAME_ANALYZED.deck_compatibility,
          deck_test_results: MOCK_GAME_ANALYZED.deck_test_results,
          // Steam-sourced sentiment + freshness (data-source-clarity refactor)
          positive_pct: MOCK_GAME_ANALYZED.positive_pct,
          review_score_desc: MOCK_GAME_ANALYZED.review_score_desc,
          review_count: MOCK_GAME_ANALYZED.review_count,
          meta_crawled_at: MOCK_GAME_ANALYZED.meta_crawled_at,
          review_crawled_at: MOCK_GAME_ANALYZED.review_crawled_at,
          reviews_completed_at: MOCK_GAME_ANALYZED.reviews_completed_at,
          tags_crawled_at: MOCK_GAME_ANALYZED.tags_crawled_at,
          last_analyzed: MOCK_GAME_ANALYZED.last_analyzed,
          // Boxleiter v1 revenue estimate (populated state for the default
          // fixture). `revenue_estimate_reason` is intentionally omitted
          // here — the report endpoint omits it when NULL, so the mock
          // mirrors that contract.
          estimated_owners: 360000,
          estimated_revenue_usd: 7200000,
          revenue_estimate_method: 'boxleiter_v1',
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
          is_early_access: false,
          deck_compatibility: MOCK_GAME_UNANALYZED.deck_compatibility,
          deck_test_results: MOCK_GAME_UNANALYZED.deck_test_results,
          // Steam-sourced fields are present even for unanalyzed games
          positive_pct: MOCK_GAME_UNANALYZED.positive_pct,
          review_score_desc: MOCK_GAME_UNANALYZED.review_score_desc,
          review_count: MOCK_GAME_UNANALYZED.review_count,
          meta_crawled_at: MOCK_GAME_UNANALYZED.meta_crawled_at,
          review_crawled_at: MOCK_GAME_UNANALYZED.review_crawled_at,
          reviews_completed_at: MOCK_GAME_UNANALYZED.reviews_completed_at,
          tags_crawled_at: MOCK_GAME_UNANALYZED.tags_crawled_at,
          // Insufficient-reviews empty state for the Market Reach card
          revenue_estimate_reason: 'insufficient_reviews',
        },
      },
    })
  )

  // Compare lens — second game report
  await page.route('**/api/games/892970/report', route =>
    route.fulfill({
      json: {
        status: 'available',
        report: MOCK_REPORT_2,
        game: {
          short_desc: MOCK_GAME_2.short_desc,
          developer: MOCK_GAME_2.developer,
          release_date: MOCK_GAME_2.release_date,
          price_usd: MOCK_GAME_2.price_usd,
          is_free: MOCK_GAME_2.is_free,
          is_early_access: MOCK_GAME_2.is_early_access,
          genres: MOCK_GAME_2.genres,
          tags: MOCK_GAME_2.tags,
          deck_compatibility: MOCK_GAME_2.deck_compatibility,
          deck_test_results: MOCK_GAME_2.deck_test_results,
          positive_pct: MOCK_GAME_2.positive_pct,
          review_score_desc: MOCK_GAME_2.review_score_desc,
          review_count: MOCK_GAME_2.review_count,
          meta_crawled_at: MOCK_GAME_2.meta_crawled_at,
          review_crawled_at: MOCK_GAME_2.review_crawled_at,
          reviews_completed_at: MOCK_GAME_2.reviews_completed_at,
          tags_crawled_at: MOCK_GAME_2.tags_crawled_at,
          last_analyzed: MOCK_GAME_2.last_analyzed,
        },
      },
    })
  )

  await mockAnalyticsRoutes(page)
  await mockPerEntityAnalyticsRoutes(page)
  await mockBuilderRoutes(page)
}
