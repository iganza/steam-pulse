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
  MOCK_GENRE_INSIGHTS, MOCK_REPORT_SUMMARY_PREORDER, MOCK_REPORT_SUMMARY_LIVE,
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
  await page.route('**/api/games/*/related-analyzed*', route =>
    route.fulfill({
      json: {
        games: [
          {
            appid: 440,
            slug: 'team-fortress-2-440',
            name: 'Team Fortress 2',
            header_image: 'https://cdn.akamai.steamstatic.com/steam/apps/440/header.jpg',
            positive_pct: 96,
            one_liner: 'The gold standard of team shooters.',
          },
          {
            appid: 730,
            slug: 'counter-strike-2-730',
            name: 'Counter-Strike 2',
            header_image: 'https://cdn.akamai.steamstatic.com/steam/apps/730/header.jpg',
            positive_pct: 82,
            one_liner: 'Precise gunplay with demanding matchmaking.',
          },
          {
            appid: 570,
            slug: 'dota-2-570',
            name: 'Dota 2',
            header_image: 'https://cdn.akamai.steamstatic.com/steam/apps/570/header.jpg',
            positive_pct: 81,
            one_liner: 'Deep strategy with a punishing learning curve.',
          },
        ],
      },
    })
  )
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
  await page.route('**/api/publishers/*/analytics', route =>
    route.fulfill({
      json: {
        ...MOCK_DEVELOPER_PORTFOLIO,
        publisher: MOCK_DEVELOPER_PORTFOLIO.developer,
        publisher_slug: MOCK_DEVELOPER_PORTFOLIO.developer_slug,
      },
    })
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

  // Homepage discovery feeds (popular / top_rated / hidden_gem / new_release / just_analyzed)
  await page.route('**/api/discovery/**', route =>
    route.fulfill({ json: { games: MOCK_GAMES_LIST.games } })
  )

  // Catalog stats (ProofBar)
  await page.route('**/api/catalog/stats', route =>
    route.fulfill({ json: { total_games: MOCK_GAMES_LIST.total } })
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

  // Review stats and benchmarks — specific routes registered LAST (higher LIFO priority)
  await page.route('**/api/games/*/review-stats', route =>
    route.fulfill({ json: MOCK_REVIEW_STATS })
  )

  await page.route('**/api/games/*/benchmarks', route =>
    route.fulfill({ json: MOCK_BENCHMARKS })
  )

  // Generic game report fallback — catches appids not handled by specific routes below
  await page.route('**/api/games/*/report', route =>
    route.fulfill({
      json: {
        status: 'available',
        report: MOCK_REPORT,
        game: {
          short_desc: MOCK_GAME_ANALYZED.short_desc,
          header_image: MOCK_GAME_ANALYZED.header_image,
          developer: MOCK_GAME_ANALYZED.developer,
          release_date: MOCK_GAME_ANALYZED.release_date,
          price_usd: 19.99,
          is_free: false,
          is_early_access: false,
          genres: MOCK_GAME_ANALYZED.genres,
          tags: MOCK_GAME_ANALYZED.tags,
          positive_pct: MOCK_GAME_ANALYZED.positive_pct,
          review_score_desc: MOCK_GAME_ANALYZED.review_score_desc,
          review_count: MOCK_GAME_ANALYZED.review_count,
          review_count_english: MOCK_GAME_ANALYZED.review_count_english,
          meta_crawled_at: MOCK_GAME_ANALYZED.meta_crawled_at,
          review_crawled_at: MOCK_GAME_ANALYZED.review_crawled_at,
          reviews_completed_at: MOCK_GAME_ANALYZED.reviews_completed_at,
          tags_crawled_at: MOCK_GAME_ANALYZED.tags_crawled_at,
          last_analyzed: MOCK_GAME_ANALYZED.last_analyzed,
        },
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
          review_count_english: MOCK_GAME_ANALYZED.review_count_english,
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
        game: {
          name: MOCK_GAME_UNANALYZED.name,
          slug: MOCK_GAME_UNANALYZED.slug,
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
          review_count_english: MOCK_GAME_UNANALYZED.review_count_english,
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
}

/** Mock the /genre/[slug]/ page endpoints.
 *
 *   reportState: 'pre-order' | 'live' | 'none'
 *     - pre-order: getReportForGenre returns a future-dated row
 *     - live:      returns a past-dated row
 *     - none:      returns 404 (block doesn't render)
 *
 *   insights: 'present' | '404'
 *     - present: MOCK_GENRE_INSIGHTS
 *     - 404:     /api/tags/{slug}/insights returns 404 (page 404s)
 */
export async function mockGenreInsights(
  page: Page,
  opts: {
    reportState: 'pre-order' | 'live' | 'none'
    insights?: 'present' | '404'
    slug?: string
  } = { reportState: 'none' },
) {
  const slug = opts.slug ?? 'roguelike-deckbuilder'
  const insightsMode = opts.insights ?? 'present'

  // Source-game lookups for friction/wishlist/benchmark crosslinks. Benchmarks
  // 99999901 / 99999902 are in the fixture but off-preview (first-3 slice),
  // so the page shouldn't call their report endpoint.
  const gameReportMocks: Record<number, { slug: string; name: string }> = {
    646570: { slug: 'slay-the-spire', name: 'Slay the Spire' },
    2379780: { slug: 'balatro', name: 'Balatro' },
    1196590: { slug: 'monster-train', name: 'Monster Train' },
  }
  for (const [appidStr, g] of Object.entries(gameReportMocks)) {
    const appid = Number(appidStr)
    await page.route(`**/api/games/${appid}/report`, route =>
      route.fulfill({
        json: {
          status: 'available',
          game: {
            slug: g.slug,
            name: g.name,
            header_image: `https://cdn.akamai.steamstatic.com/steam/apps/${appid}/header.jpg`,
          },
        },
      }),
    )
  }

  // Insights — override the fixture's slug so response.slug matches the URL.
  const insightsPattern = `**/api/tags/${slug}/insights`
  if (insightsMode === '404') {
    await page.route(insightsPattern, route =>
      route.fulfill({ status: 404, json: { error: 'not_found' } }),
    )
  } else {
    await page.route(insightsPattern, route =>
      route.fulfill({ json: { ...MOCK_GENRE_INSIGHTS, slug } }),
    )
  }

  // Report — clone the fixture with the requested slug so checkout flows
  // that read report.slug stay consistent with the mocked route.
  const reportPattern = `**/api/genres/${slug}/report`
  if (opts.reportState === 'none') {
    await page.route(reportPattern, route =>
      route.fulfill({ status: 404, json: { error: 'not_found' } }),
    )
  } else if (opts.reportState === 'pre-order') {
    await page.route(reportPattern, route =>
      route.fulfill({ json: { ...MOCK_REPORT_SUMMARY_PREORDER, slug } }),
    )
  } else {
    await page.route(reportPattern, route =>
      route.fulfill({ json: { ...MOCK_REPORT_SUMMARY_LIVE, slug } }),
    )
  }
}
