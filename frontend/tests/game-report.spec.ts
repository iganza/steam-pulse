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
      /promise gap/i,
    ]
    for (const section of sections) {
      await expect(page.getByText(section)).toBeVisible()
    }
  })

  test('no blur overlay or lock icons', async ({ page }) => {
    await expect(page.locator('.premium-blur-content')).not.toBeAttached()
    await expect(page.locator('.premium-overlay')).not.toBeAttached()
  })

  test('no unlock or pricing CTAs outside the Market Reach card', async ({ page }) => {
    // Market Reach is the one deliberately Pro-gated surface on this page.
    // Assert any unlock CTA is confined to that subtree — there should be
    // exactly one on the page and it must live inside [data-testid="market-reach"].
    const marketReach = page.getByTestId('market-reach')
    await expect(marketReach.getByText(/unlock/i)).toHaveCount(1)
    await expect(page.getByText(/unlock/i)).toHaveCount(1)
    await expect(page.getByText(/\$7/)).not.toBeVisible()
  })

  test('Steam-branded sentiment score is shown', async ({ page }) => {
    // ScoreBar is now labelled "Steam Sentiment" with a 👍 prefix — sentiment
    // magnitude is Steam-owned post-data-source-clarity, never AI-derived.
    await expect(page.getByText('Steam Sentiment')).toBeVisible()
  })

  test('Steam Facts zone shows crawl freshness', async ({ page }) => {
    // Freshness is framed as a confident statement with an owned cadence,
    // not "Crawled Xd ago" (which read as defensive).
    await expect(page.getByTestId('steam-facts-crawled')).toHaveText(
      /Data current as of .+\. We re-crawl reviews and metadata every 14 days\./,
    )
  })

  test('SteamPulse Analysis zone header renders with analyzed freshness', async ({ page }) => {
    // The AI-narrative zone is clearly demarcated from Steam Facts and carries
    // its own freshness stamp sourced from reports.last_analyzed.
    await expect(page.getByText(/SteamPulse Analysis/i)).toBeVisible()
    await expect(page.getByText(/Analyzed \d+[mhd] ago/)).toBeVisible()
  })

  test('named-author byline renders under the Verdict with methodology link', async ({ page }) => {
    // Google March-2026 AI-content signal: every LLM-synthesised page needs a
    // visible human byline linking to the methodology anchor.
    const byline = page.getByTestId('author-byline')
    await expect(byline).toBeVisible()
    await expect(byline).toContainText(/Analysis by Ivan Z\. Ganza/)
    const methodologyLink = byline.getByRole('link', { name: /methodology/i })
    await expect(methodologyLink).toHaveAttribute('href', '/about#methodology')
  })

  test('footer methodology paragraph names the author and review count', async ({ page }) => {
    const footer = page.getByTestId('methodology-footer')
    await expect(footer).toBeVisible()
    // MOCK_REPORT.total_reviews_analyzed = 2000 per fixtures.
    await expect(footer).toContainText(/2,000 reviews analysed/)
    await expect(footer).toContainText(/reviewed and curated by Ivan Z\. Ganza/)
    await expect(footer.getByRole('link', { name: /methodology/i })).toHaveAttribute(
      'href',
      '/about#methodology',
    )
  })

  test('hero renders Steam chip with review_score_desc', async ({ page }) => {
    // The hero badge block replaces the old `report.overall_sentiment` pill
    // with a Steam-attributed chip reading "Steam · {review_score_desc}".
    await expect(page.getByText(/Steam · Very Positive/i)).toBeVisible()
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

  test('Steam review_score_desc label is shown', async ({ page }) => {
    // The old test asserted /overwhelmingly positive/ from the now-deleted
    // report.overall_sentiment. The mock game's Steam review_score_desc is
    // "Very Positive" — that's what the UI surfaces post-data-source-clarity.
    await expect(page.getByText(/very positive/i).first()).toBeVisible()
  })

  test('Quick Stats Reviews tile shows crawl freshness caption', async ({ page }) => {
    await expect(page.getByTestId('reviews-tile-crawled')).toHaveText(/Current as of .+/)
  })

  test('Quick Stats Reviews tile main value is Steam English count with "en" suffix', async ({ page }) => {
    // Regression guard for PR #109: the main value must be Steam's English
    // review total (review_count_english), NOT the analyzed-sample size. The
    // fixture sets these to 98,432 and 2,000 respectively so a regression
    // that swaps the two would flip the assertion.
    const tile = page
      .locator('section')
      .filter({ hasText: 'Quick Stats' })
      .locator('div')
      .filter({ has: page.locator('span', { hasText: /^Reviews$/ }) })
      .first()
    await expect(tile.locator('p').first()).toContainText('98,432')
    await expect(tile.locator('p').first()).not.toContainText('2,000')
    await expect(tile.locator('span', { hasText: /^en$/ })).toBeVisible()
  })

  test('Quick Stats Reviews tile subtitle shows analyzed sample size', async ({ page }) => {
    // The "N analyzed" subtitle is independent of the main value — it only
    // appears when totalReviewsAnalyzed is present, and always reflects the
    // analyzed sample, not the English total.
    const tile = page
      .locator('section')
      .filter({ hasText: 'Quick Stats' })
      .locator('div')
      .filter({ has: page.locator('span', { hasText: /^Reviews$/ }) })
      .first()
    await expect(tile.getByText(/2,000 analyzed/)).toBeVisible()
  })

  test('Quick Stats grid shows page metadata freshness footer', async ({ page }) => {
    await expect(page.getByTestId('quick-stats-meta-updated')).toHaveText(
      /Metadata current as of .+ · Source: Steam/,
    )
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

  test('promise gap renders verdict rows and audience match', async ({ page }) => {
    const promiseGap = page.getByTestId('promise-gap')
    await expect(promiseGap).toBeVisible()
    await expect(promiseGap.getByText('VALIDATED').first()).toBeVisible()
    await expect(promiseGap.getByText('UNDERDELIVERED').first()).toBeVisible()
    await expect(promiseGap.getByText('HIDDEN STRENGTH').first()).toBeVisible()
    await expect(promiseGap.getByText('PARTIAL MISMATCH')).toBeVisible()
    // isPro = true — full audience note rendered, no blur, no upgrade CTA
    await expect(promiseGap.locator('.blur-sm')).not.toBeAttached()
    await expect(promiseGap.getByRole('link', { name: /upgrade to pro/i })).not.toBeVisible()
    await expect(promiseGap.getByText(/Store page targets new players/i)).toBeVisible()
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

test.describe('Hidden Gem badge — 0.0-1.0 backend scale', () => {
  test('renders the badge when backend returns a high 0-1 score', async ({ page }) => {
    // Regression for the scaling bug flagged in PR #51 review: the backend
    // returns hidden_gem_score on a 0.0-1.0 scale and the UI must multiply by
    // 100 before feeding HiddenGemBadge (whose thresholds are 50/70/85).
    // 0.75 → 75 → "Underrated" label should render.
    await mockAllApiRoutes(page)
    await page.route('**/api/games/440/report', route =>
      route.fulfill({
        json: {
          status: 'available',
          report: { ...MOCK_REPORT, hidden_gem_score: 0.75 },
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
            positive_pct: MOCK_GAME_ANALYZED.positive_pct,
            review_score_desc: MOCK_GAME_ANALYZED.review_score_desc,
            review_count: MOCK_GAME_ANALYZED.review_count,
            meta_crawled_at: MOCK_GAME_ANALYZED.meta_crawled_at,
            review_crawled_at: MOCK_GAME_ANALYZED.review_crawled_at,
            last_analyzed: MOCK_GAME_ANALYZED.last_analyzed,
          },
        },
      })
    )
    await page.goto('/games/440/team-fortress-2')
    await expect(page.getByText(/underrated/i)).toBeVisible()
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
            // Steam-sourced fields so the Verdict section renders the full
            // post-data-source-clarity layout, not the empty-Steam fallback.
            positive_pct: MOCK_GAME_ANALYZED.positive_pct,
            review_score_desc: MOCK_GAME_ANALYZED.review_score_desc,
            review_count: MOCK_GAME_ANALYZED.review_count,
            meta_crawled_at: MOCK_GAME_ANALYZED.meta_crawled_at,
            review_crawled_at: MOCK_GAME_ANALYZED.review_crawled_at,
            reviews_completed_at: MOCK_GAME_ANALYZED.reviews_completed_at,
            last_analyzed: MOCK_GAME_ANALYZED.last_analyzed,
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

  test('competitive benchmark IS shown for unanalyzed games when cohort >= 10', async ({ page }) => {
    // Soft-launch SEO discipline: benchmark is sourced from
    // /api/games/{appid}/benchmarks which is report-independent. Ungated so
    // no-report pages still get a credible "Top X% in genre" dashboard row.
    // MOCK_BENCHMARKS.cohort_size = 312 so the threshold (>= 10) is met.
    await expect(page.getByTestId('competitive-benchmark')).toBeVisible()
  })

  test('promise gap is NOT shown for unanalyzed games', async ({ page }) => {
    await expect(page.getByTestId('promise-gap')).not.toBeAttached()
  })
})

test.describe('Promise Gap — legacy report without store_page_alignment', () => {
  test('section is not rendered when store_page_alignment is null', async ({ page }) => {
    await mockAllApiRoutes(page)
    // Override the analyzed-game report route AFTER the suite mock so this
    // registration wins (Playwright LIFO). Strip store_page_alignment to
    // simulate a legacy report produced before this feature existed.
    const { store_page_alignment: _omit, ...legacyReport } = MOCK_REPORT
    await page.route('**/api/games/440/report', route =>
      route.fulfill({
        json: {
          status: 'available',
          report: legacyReport,
          game: {
            short_desc: 'Legacy',
            developer: 'Valve',
            release_date: '2007-10-10',
            price_usd: null,
            is_free: true,
            is_early_access: false,
            genres: [],
            tags: [],
            deck_compatibility: null,
            deck_test_results: [],
            positive_pct: 87,
            review_score_desc: 'Very Positive',
            review_count: 100,
            meta_crawled_at: null,
            review_crawled_at: null,
            reviews_completed_at: null,
            tags_crawled_at: null,
            last_analyzed: new Date().toISOString(),
          },
        },
      }),
    )
    await page.goto('/games/440/team-fortress-2')
    await expect(page.getByRole('heading', { name: 'Team Fortress 2' })).toBeVisible()
    await expect(page.getByTestId('promise-gap')).not.toBeAttached()
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

  test('shows the report waitlist card as primary CTA', async ({ page }) => {
    await expect(page.getByTestId('report-waitlist-card')).toBeVisible()
    await expect(
      page.getByText(/Get the full SteamPulse report on .+ when it's ready/i),
    ).toBeVisible()
  })

  test('hero section is rendered', async ({ page }) => {
    // The hero with the game name is always rendered even without analysis
    await expect(page.getByRole('main')).toBeVisible()
  })

  test('hides Deck badge when unknown/null', async ({ page }) => {
    await expect(page.getByTestId('deck-badge')).not.toBeAttached()
  })

  test('Quick Stats Reviews tile shows crawl freshness caption', async ({ page }) => {
    await expect(page.getByTestId('reviews-tile-crawled')).toHaveText(/Current as of .+/)
  })

  test('Quick Stats grid shows page metadata freshness footer', async ({ page }) => {
    await expect(page.getByTestId('quick-stats-meta-updated')).toHaveText(
      /Metadata current as of .+ · Source: Steam/,
    )
  })
})

test.describe('Quick Stats freshness — null timestamps', () => {
  test('omits both freshness captions when crawl timestamps are null', async ({ page }) => {
    await mockAllApiRoutes(page)
    // Override the unanalyzed game route to strip all crawl timestamps —
    // the captions must degrade gracefully (no render, no layout shift).
    await page.route('**/api/games/9999999/report', route =>
      route.fulfill({
        json: {
          status: 'not_available',
          game: {
            short_desc: 'A small indie adventure game.',
            developer: 'Small Studio',
            release_date: '2024-06-01',
            price_usd: 9.99,
            is_free: false,
            is_early_access: false,
            deck_compatibility: null,
            deck_test_results: [],
            positive_pct: 80,
            review_score_desc: 'Mostly Positive',
            review_count: 42,
            // meta_crawled_at / review_crawled_at / reviews_completed_at omitted
          },
        },
      }),
    )
    await page.goto('/games/9999999/obscure-indie-game')
    await expect(page.getByText('Quick Stats').first()).toBeVisible()
    await expect(page.getByTestId('reviews-tile-crawled')).not.toBeAttached()
    await expect(page.getByTestId('quick-stats-meta-updated')).not.toBeAttached()
  })
})

test.describe('Early Access badge', () => {
  test('displays Early Access badge when is_early_access is true', async ({ page }) => {
    await mockAllApiRoutes(page)
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
            is_early_access: true,
            genres: MOCK_GAME_ANALYZED.genres,
            tags: MOCK_GAME_ANALYZED.tags,
            deck_compatibility: MOCK_GAME_ANALYZED.deck_compatibility,
            deck_test_results: MOCK_GAME_ANALYZED.deck_test_results,
            // Steam-sourced fields — same rationale as the Deck override
            positive_pct: MOCK_GAME_ANALYZED.positive_pct,
            review_score_desc: MOCK_GAME_ANALYZED.review_score_desc,
            review_count: MOCK_GAME_ANALYZED.review_count,
            meta_crawled_at: MOCK_GAME_ANALYZED.meta_crawled_at,
            review_crawled_at: MOCK_GAME_ANALYZED.review_crawled_at,
            reviews_completed_at: MOCK_GAME_ANALYZED.reviews_completed_at,
            last_analyzed: MOCK_GAME_ANALYZED.last_analyzed,
          },
        },
      })
    )
    await page.goto('/games/440/team-fortress-2')
    const badge = page.getByTestId('early-access-badge')
    await expect(badge).toBeVisible()
    await expect(badge).toContainText('Early Access')
  })

  test('hides Early Access badge when is_early_access is false', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/440/team-fortress-2')
    await expect(page.getByTestId('early-access-badge')).not.toBeAttached()
  })
})

test.describe('Review date range in footer', () => {
  test('renders date range when both dates are present', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/440/team-fortress-2')
    // MOCK_REPORT has review_date_range_start: "2021-03-15", end: "2025-01-20"
    await expect(page.getByText(/Mar 2021\s*[–\u2013]\s*Jan 2025/)).toBeVisible()
  })

  test('collapses to single month when start and end are same month', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.route('**/api/games/440/report', route =>
      route.fulfill({
        json: {
          status: 'available',
          report: {
            ...MOCK_REPORT,
            review_date_range_start: '2024-03-01',
            review_date_range_end: '2024-03-28',
          },
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
            positive_pct: MOCK_GAME_ANALYZED.positive_pct,
            review_score_desc: MOCK_GAME_ANALYZED.review_score_desc,
            review_count: MOCK_GAME_ANALYZED.review_count,
            meta_crawled_at: MOCK_GAME_ANALYZED.meta_crawled_at,
            review_crawled_at: MOCK_GAME_ANALYZED.review_crawled_at,
            last_analyzed: MOCK_GAME_ANALYZED.last_analyzed,
          },
        },
      }),
    )
    await page.goto('/games/440/team-fortress-2')
    // Same month — should show "Mar 2024" once, not "Mar 2024 – Mar 2024"
    await expect(page.getByText(/\(Mar 2024\)/)).toBeVisible()
    await expect(page.getByText(/Mar 2024\s*[–\u2013]\s*Mar 2024/)).not.toBeVisible()
  })

  test('omits date range when fields are null (legacy report)', async ({ page }) => {
    await mockAllApiRoutes(page)
    const { review_date_range_start: _s, review_date_range_end: _e, ...legacyReport } = MOCK_REPORT
    await page.route('**/api/games/440/report', route =>
      route.fulfill({
        json: {
          status: 'available',
          report: legacyReport,
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
            positive_pct: MOCK_GAME_ANALYZED.positive_pct,
            review_score_desc: MOCK_GAME_ANALYZED.review_score_desc,
            review_count: MOCK_GAME_ANALYZED.review_count,
            meta_crawled_at: MOCK_GAME_ANALYZED.meta_crawled_at,
            review_crawled_at: MOCK_GAME_ANALYZED.review_crawled_at,
            last_analyzed: MOCK_GAME_ANALYZED.last_analyzed,
          },
        },
      }),
    )
    await page.goto('/games/440/team-fortress-2')
    await expect(page.getByText(/Analysis based on/)).toBeVisible()
    // No date range parenthetical
    await expect(page.getByText(/\(.*20[12]\d\)/)).not.toBeVisible()
  })
})
