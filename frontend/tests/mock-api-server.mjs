/**
 * Lightweight mock API server for Playwright E2E tests.
 *
 * Next.js server components make server-side fetch calls to API_URL. Playwright's
 * page.route() only intercepts browser-side requests, not server-to-server calls.
 * This server runs on port 3001 and handles those server-side calls so that pages
 * render properly during tests.
 *
 * Client-side browser calls are still intercepted by page.route() in api-mock.ts.
 */
import { createServer } from 'http'

// ── Mock data (mirrors tests/fixtures/mock-data.ts) ───────────────────────────

const MOCK_GAME_ANALYZED = {
  appid: 440,
  name: 'Team Fortress 2',
  slug: 'team-fortress-2',
  developer: 'Valve',
  header_image: 'https://cdn.akamai.steamstatic.com/steam/apps/440/header.jpg',
  review_count: 142389,
  review_count_english: 98432,
  positive_pct: 87,
  review_score_desc: 'Very Positive',
  // 0.0-1.0 scale matching the backend; UI scales x100 at the badge boundary.
  hidden_gem_score: 0.12,
  price_usd: null,
  is_free: true,
  genres: ['Action', 'Free to Play'],
  tags: ['FPS', 'Multiplayer', 'Shooter', 'Team-Based'],
  release_date: '2007-10-10',
  short_desc: 'Nine distinct classes provide a broad range of tactical abilities and personalities.',
  deck_compatibility: 2,
  deck_test_results: [
    { display_type: 3, loc_token: '#SteamDeckVerified_TestResult_DefaultControllerConfigNotFullyFunctional' },
    { display_type: 4, loc_token: '#SteamDeckVerified_TestResult_DefaultConfigurationIsPerformant' },
  ],
}

const MOCK_GAME_UNANALYZED = {
  appid: 9999999,
  name: 'Obscure Indie Game',
  slug: 'obscure-indie-game',
  developer: 'Small Studio',
  header_image: 'https://cdn.akamai.steamstatic.com/steam/apps/9999999/header.jpg',
  review_count: 42,
  review_count_english: 38,
  positive_pct: 80,
  review_score_desc: 'Mostly Positive',
  hidden_gem_score: null,
  price_usd: 9.99,
  is_free: false,
  genres: ['Indie', 'Adventure'],
  tags: ['Indie', 'Adventure', 'Singleplayer'],
  release_date: '2024-06-01',
  short_desc: 'A small indie adventure game.',
  deck_compatibility: null,
  deck_test_results: [],
}

const MOCK_REPORT = {
  game_name: 'Team Fortress 2',
  appid: 440,
  total_reviews_analyzed: 2000,
  sentiment_trend: 'stable',
  sentiment_trend_note: 'Sentiment has remained consistent over the past 6 months.',
  one_liner: 'A timeless class-based shooter that rewards teamwork and creativity.',
  audience_profile: {
    ideal_player: 'Competitive FPS fans',
    casual_friendliness: 'Moderate',
    archetypes: ['Competitive gamer', 'Casual player'],
    not_for: ['Solo-only players'],
  },
  design_strengths: ['Class diversity', 'Team dynamics', 'Free-to-play accessibility'],
  gameplay_friction: ['Matchmaking quality', 'Bot problem in casual mode'],
  player_wishlist: ['Better anti-cheat', 'New maps', 'Ranked mode improvements'],
  churn_triggers: ['Toxic players', 'Unbalanced teams'],
  dev_priorities: [
    { action: 'Bot/cheat mitigation', why_it_matters: 'Ruins matches', frequency: 'Very common', effort: 'High' },
    { action: 'Matchmaking improvements', why_it_matters: 'Affects retention', frequency: 'Common', effort: 'Medium' },
  ],
  competitive_context: [
    { game: 'Overwatch 2', comparison_sentiment: 'positive', note: 'Players prefer TF2 art style' },
  ],
  genre_context: 'Dominates the class-based shooter genre. No direct competitor matches its longevity.',
  hidden_gem_score: 12,
  last_analyzed: '2025-03-01T00:00:00Z',
}

const MOCK_GENRES = [
  { id: 1, name: 'Action', slug: 'action', game_count: 12400, analyzed_count: 980 },
  { id: 2, name: 'Indie', slug: 'indie', game_count: 28000, analyzed_count: 1200 },
  { id: 3, name: 'RPG', slug: 'rpg', game_count: 8200, analyzed_count: 740 },
  { id: 4, name: 'Strategy', slug: 'strategy', game_count: 6100, analyzed_count: 510 },
]

const MOCK_TAGS = [
  { id: 1, name: 'Multiplayer', slug: 'multiplayer', game_count: 8900, category: 'Player Mode' },
  { id: 2, name: 'Singleplayer', slug: 'singleplayer', game_count: 42000, category: 'Player Mode' },
  { id: 3, name: 'Roguelike', slug: 'roguelike', game_count: 3100, category: 'Sub-Genre' },
  { id: 4, name: 'Open World', slug: 'open-world', game_count: 2200, category: 'Gameplay' },
]

const MOCK_TAG_GROUPS = [
  { category: 'Genre', tags: [{ id: 10, name: 'Action', slug: 'action', game_count: 12000, category: 'Genre' }], total_count: 1 },
  { category: 'Sub-Genre', tags: [{ id: 3, name: 'Roguelike', slug: 'roguelike', game_count: 3100, category: 'Sub-Genre' }], total_count: 1 },
  { category: 'Theme & Setting', tags: [{ id: 11, name: 'Fantasy', slug: 'fantasy', game_count: 6100, category: 'Theme & Setting' }], total_count: 1 },
  { category: 'Gameplay', tags: [{ id: 4, name: 'Open World', slug: 'open-world', game_count: 2200, category: 'Gameplay' }], total_count: 1 },
  { category: 'Player Mode', tags: [{ id: 2, name: 'Singleplayer', slug: 'singleplayer', game_count: 42000, category: 'Player Mode' }], total_count: 1 },
]

const MOCK_GAMES_LIST = {
  total: 100,
  games: [MOCK_GAME_ANALYZED, MOCK_GAME_UNANALYZED],
}

const MOCK_REVIEW_STATS = {
  timeline: [
    { week: '2023-10-02', total: 120, positive: 96, pct_positive: 80 },
    { week: '2023-10-09', total: 98, positive: 78, pct_positive: 80 },
    { week: '2023-10-16', total: 145, positive: 116, pct_positive: 80 },
    { week: '2023-10-23', total: 132, positive: 112, pct_positive: 85 },
    { week: '2023-10-30', total: 110, positive: 99, pct_positive: 90 },
  ],
  playtime_buckets: [
    { bucket: '0h', reviews: 22, pct_positive: 55 },
    { bucket: '<2h', reviews: 45, pct_positive: 59 },
    { bucket: '2-10h', reviews: 121, pct_positive: 68 },
    { bucket: '10-50h', reviews: 205, pct_positive: 82 },
    { bucket: '50-200h', reviews: 212, pct_positive: 88 },
    { bucket: '200h+', reviews: 150, pct_positive: 71 },
  ],
  review_velocity: {
    reviews_per_day: 12.3,
    reviews_last_30_days: 320,
  },
}

const MOCK_BENCHMARKS = {
  sentiment_rank: 0.77,
  popularity_rank: 0.45,
  cohort_size: 312,
}

const MOCK_PRICE_POSITIONING = {
  genre: 'Action',
  genre_slug: 'action',
  distribution: [
    { price_range: 'Free', game_count: 45, avg_steam_pct: 72.3, median_price: 0 },
    { price_range: '$5-10', game_count: 120, avg_steam_pct: 68.5, median_price: 7.99 },
    { price_range: '$10-15', game_count: 95, avg_steam_pct: 78.2, median_price: 12.99 },
    { price_range: '$15-20', game_count: 68, avg_steam_pct: 74.1, median_price: 17.49 },
    { price_range: '$20-30', game_count: 42, avg_steam_pct: 71.8, median_price: 24.99 },
  ],
  summary: {
    avg_price: 14.99, median_price: 9.99,
    free_count: 45, paid_count: 325, sweet_spot: '$10-15',
  },
}

const MOCK_RELEASE_TIMING = {
  genre: 'Action',
  monthly: [
    { month: 1, month_name: 'January', releases: 28, avg_steam_pct: 74.2, avg_reviews: 320 },
    { month: 2, month_name: 'February', releases: 35, avg_steam_pct: 78.3, avg_reviews: 410 },
    { month: 3, month_name: 'March', releases: 42, avg_steam_pct: 72.1, avg_reviews: 350 },
    { month: 4, month_name: 'April', releases: 38, avg_steam_pct: 71.0, avg_reviews: 300 },
    { month: 5, month_name: 'May', releases: 40, avg_steam_pct: 73.5, avg_reviews: 380 },
    { month: 6, month_name: 'June', releases: 55, avg_steam_pct: 70.2, avg_reviews: 450 },
    { month: 7, month_name: 'July', releases: 30, avg_steam_pct: 75.0, avg_reviews: 290 },
    { month: 8, month_name: 'August', releases: 32, avg_steam_pct: 74.8, avg_reviews: 310 },
    { month: 9, month_name: 'September', releases: 60, avg_steam_pct: 69.5, avg_reviews: 500 },
    { month: 10, month_name: 'October', releases: 85, avg_steam_pct: 67.3, avg_reviews: 550 },
    { month: 11, month_name: 'November', releases: 50, avg_steam_pct: 64.2, avg_reviews: 420 },
    { month: 12, month_name: 'December', releases: 25, avg_steam_pct: 76.1, avg_reviews: 270 },
  ],
  best_month: { month: 2, month_name: 'February', avg_steam_pct: 78.3 },
  worst_month: { month: 11, month_name: 'November', avg_steam_pct: 64.2 },
  quietest_month: { month: 12, month_name: 'December', releases: 25 },
  busiest_month: { month: 10, month_name: 'October', releases: 85 },
}

const MOCK_PLATFORM_GAPS = {
  genre: 'Action',
  total_games: 500,
  platforms: {
    windows: { count: 498, pct: 99.6, avg_steam_pct: 71.2 },
    mac: { count: 175, pct: 35.0, avg_steam_pct: 73.5 },
    linux: { count: 110, pct: 22.0, avg_steam_pct: 75.1 },
  },
  underserved: 'linux',
}

const MOCK_TAG_TREND = {
  tag: 'Roguelike', tag_slug: 'roguelike',
  yearly: [
    { year: 2018, game_count: 45, avg_steam_pct: 71.2 },
    { year: 2019, game_count: 62, avg_steam_pct: 69.8 },
    { year: 2020, game_count: 78, avg_steam_pct: 73.5 },
    { year: 2021, game_count: 95, avg_steam_pct: 74.1 },
    { year: 2022, game_count: 110, avg_steam_pct: 72.8 },
    { year: 2023, game_count: 130, avg_steam_pct: 75.2 },
  ],
  growth_rate: 1.89, peak_year: 2023, total_games: 520,
}

const MOCK_DEVELOPER_PORTFOLIO = {
  developer: 'Valve', developer_slug: 'valve',
  summary: {
    total_games: 3, total_reviews: 10500000, avg_steam_pct: 88.5,
    first_release: '2004-11-16', latest_release: '2023-09-27',
    avg_price: 9.99, free_games: 2, well_received: 3, poorly_received: 0,
    sentiment_trajectory: 'stable',
  },
  games: [
    {
      appid: 730, name: 'Counter-Strike 2', slug: 'counter-strike-2-730',
      header_image: 'https://cdn.akamai.steamstatic.com/steam/apps/730/header.jpg',
      release_date: '2023-09-27', price_usd: null, is_free: true,
      review_count: 8500000, positive_pct: 82, review_score_desc: 'Very Positive',
      metacritic_score: null, achievements_total: 168,
    },
    {
      appid: 440, name: 'Team Fortress 2', slug: 'team-fortress-2-440',
      header_image: 'https://cdn.akamai.steamstatic.com/steam/apps/440/header.jpg',
      release_date: '2007-10-10', price_usd: null, is_free: true,
      review_count: 1000000, positive_pct: 92, review_score_desc: 'Overwhelmingly Positive',
      metacritic_score: 92, achievements_total: 520,
    },
    {
      appid: 570, name: 'Dota 2', slug: 'dota-2-570',
      header_image: 'https://cdn.akamai.steamstatic.com/steam/apps/570/header.jpg',
      release_date: '2013-07-09', price_usd: null, is_free: true,
      review_count: 2000000, positive_pct: 81, review_score_desc: 'Very Positive',
      metacritic_score: 90, achievements_total: null,
    },
  ],
}

// ── Cross-genre synthesis fixtures ───────────────────────────────────────────

const MOCK_GENRE_INSIGHTS = {
  slug: 'roguelike-deckbuilder',
  display_name: 'Roguelike Deckbuilder',
  input_appids: [646570, 2379780, 1196590],
  input_count: 141,
  prompt_version: 'v1',
  input_hash: 'mock-hash',
  narrative_summary:
    'Players of the genre cluster around three patterns: tight run length rewards craft, meta-progression carries late-game attention, and anything resembling grind breaks the loop.',
  avg_positive_pct: 88.5,
  median_review_count: 12000,
  computed_at: '2026-04-15T00:00:00Z',
  editorial_intro:
    'This is a hand-written editorial intro for testing purposes. It frames what the synthesis found and why it matters to an indie dev building in this genre.\n\nThe second paragraph adds context so the page renders with a real-looking body of prose above the first section heading.',
  churn_interpretation:
    'Unlock grind hits around the 8-hour mark — players drop before meta-progression kicks in.',
  synthesis: {
    narrative_summary:
      'Players of the genre cluster around three patterns: tight run length rewards craft, meta-progression carries late-game attention, and anything resembling grind breaks the loop.',
    friction_points: [
      { title: 'Run length too long', description: 'Runs routinely exceed 90 minutes.', representative_quote: '2-hour runs are brutal on mobile.', source_appid: 646570, mention_count: 18 },
      { title: 'Unlock pacing grind', description: 'Players stall when meta-progression gates core content.', representative_quote: 'I just want the cards I\u2019ve earned already.', source_appid: 2379780, mention_count: 14 },
      { title: 'Endgame feels empty', description: 'After ascension peaks, motivation drops hard.', representative_quote: 'Nothing to chase after A20.', source_appid: 646570, mention_count: 11 },
      { title: 'Balance swings between patches', description: 'Meta whiplash frustrates experienced players.', representative_quote: 'Last patch killed my favorite deck.', source_appid: 1196590, mention_count: 9 },
      { title: 'UI hides key information', description: 'Relic interactions are buried under tooltips.', representative_quote: 'I had to read the wiki.', source_appid: 646570, mention_count: 8 },
      { title: 'Sixth friction item', description: 'Hidden in PDF.', representative_quote: 'Hidden.', source_appid: 1196590, mention_count: 5 },
      { title: 'Seventh friction item', description: 'Hidden in PDF.', representative_quote: 'Hidden.', source_appid: 1196590, mention_count: 4 },
      { title: 'Eighth friction item', description: 'Hidden in PDF.', representative_quote: 'Hidden.', source_appid: 1196590, mention_count: 4 },
      { title: 'Ninth friction item', description: 'Hidden in PDF.', representative_quote: 'Hidden.', source_appid: 1196590, mention_count: 3 },
      { title: 'Tenth friction item', description: 'Hidden in PDF.', representative_quote: 'Hidden.', source_appid: 1196590, mention_count: 3 },
    ],
    wishlist_items: [
      { title: 'Daily shared seed', description: 'Community run comparisons.', representative_quote: 'I wish runs were shareable.', source_appid: 1196590, mention_count: 12 },
      { title: 'Deeper deck archetypes', description: 'More viable non-meta builds.', representative_quote: 'Give me more decks, not more balance patches.', source_appid: 646570, mention_count: 10 },
      { title: 'Pause during combat', description: 'Accessibility.', representative_quote: 'Pausing mid-fight would unlock the game for me.', source_appid: 2379780, mention_count: 7 },
      { title: 'Fourth wishlist item', description: 'Hidden.', representative_quote: 'Hidden.', source_appid: 646570, mention_count: 6 },
      { title: 'Fifth wishlist item', description: 'Hidden.', representative_quote: 'Hidden.', source_appid: 646570, mention_count: 5 },
      { title: 'Sixth wishlist item', description: 'Hidden.', representative_quote: 'Hidden.', source_appid: 646570, mention_count: 4 },
      { title: 'Seventh wishlist item', description: 'Hidden.', representative_quote: 'Hidden.', source_appid: 646570, mention_count: 4 },
      { title: 'Eighth wishlist item', description: 'Hidden.', representative_quote: 'Hidden.', source_appid: 646570, mention_count: 3 },
      { title: 'Ninth wishlist item', description: 'Hidden.', representative_quote: 'Hidden.', source_appid: 646570, mention_count: 3 },
      { title: 'Tenth wishlist item', description: 'Hidden.', representative_quote: 'Hidden.', source_appid: 646570, mention_count: 3 },
    ],
    benchmark_games: [
      { appid: 646570, name: 'Slay the Spire', why_benchmark: 'Defines the pacing ceiling for the genre.' },
      { appid: 2379780, name: 'Balatro', why_benchmark: 'Proves a fresh mechanical core still lands with mass audiences.' },
      { appid: 1196590, name: 'Monster Train', why_benchmark: 'Multi-lane combat expanded the design envelope.' },
      { appid: 99999901, name: 'Benchmark 4', why_benchmark: 'Hidden behind the paywall.' },
      { appid: 99999902, name: 'Benchmark 5', why_benchmark: 'Hidden behind the paywall.' },
    ],
    churn_insight: {
      typical_dropout_hour: 8,
      primary_reason: 'Unlock grind between runs',
      representative_quote: 'Stopped at hour 8 — too many cards locked.',
      source_appid: 646570,
    },
    dev_priorities: [
      { action: 'Shorten late-run pacing', why_it_matters: 'Cuts the top friction cluster.', frequency: 18, effort: 'medium' },
      { action: 'Unlock all content by hour 6', why_it_matters: 'Pre-empts the churn wall.', frequency: 14, effort: 'low' },
      { action: 'Add shared daily seed mode', why_it_matters: 'Top wishlist item with low cost.', frequency: 12, effort: 'low' },
      { action: 'Fourth priority', why_it_matters: 'Hidden in PDF.', frequency: 9, effort: 'high' },
    ],
  },
}

const _NOW = Date.now()
const _FUTURE_SHIP_ISO = new Date(_NOW + 21 * 86_400 * 1000).toISOString()
const _PAST_SHIP_ISO = new Date(_NOW - 3 * 86_400 * 1000).toISOString()

const MOCK_REPORT_SUMMARY_PREORDER = {
  slug: 'rdb-preorder',
  display_name: 'The Roguelike Deckbuilder Market Report 2026',
  price_cents: 4900,
  stripe_price_id: 'price_report_test',
  published_at: _FUTURE_SHIP_ISO,
  is_pre_order: true,
}

const MOCK_REPORT_SUMMARY_LIVE = {
  ...MOCK_REPORT_SUMMARY_PREORDER,
  slug: 'rdb-live',
  published_at: _PAST_SHIP_ISO,
  is_pre_order: false,
}

// Test slugs used by the /genre/[slug]/ Playwright spec. All 'rdb-*' slugs
// return the same synthesis content; the report endpoint varies per slug.
const GENRE_INSIGHTS_SLUGS = new Set([
  'roguelike-deckbuilder',
  'rdb-base',
  'rdb-preorder',
  'rdb-live',
])

const GENRE_REPORT_BY_SLUG = {
  'rdb-preorder': MOCK_REPORT_SUMMARY_PREORDER,
  'rdb-live': MOCK_REPORT_SUMMARY_LIVE,
}

const BENCHMARK_GAME_BASICS = {
  646570: { slug: 'slay-the-spire', name: 'Slay the Spire', positive_pct: 96, review_count: 90000 },
  2379780: { slug: 'balatro', name: 'Balatro', positive_pct: 97, review_count: 75000 },
  1196590: { slug: 'monster-train', name: 'Monster Train', positive_pct: 92, review_count: 22000 },
}

// ── HTTP helpers ─────────────────────────────────────────────────────────────

function respond(res, statusCode, data) {
  const body = JSON.stringify(data)
  res.writeHead(statusCode, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body),
    'Access-Control-Allow-Origin': '*',
  })
  res.end(body)
}

// ── Route handler ─────────────────────────────────────────────────────────────

const server = createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost')
  const path = url.pathname

  // Root health probe — lets Playwright's webServer.reuseExistingServer
  // recognize an already-running mock instead of trying to relaunch on 3001.
  if (path === '/') {
    return respond(res, 200, { ok: true })
  }

  // Cross-genre synthesis — /api/tags/:slug/insights.
  // Must come BEFORE the /api/tags/.../trend and generic tags wildcards.
  {
    const m = path.match(/^\/api\/tags\/([^/]+)\/insights$/)
    if (m) {
      const slug = m[1]
      if (GENRE_INSIGHTS_SLUGS.has(slug)) {
        return respond(res, 200, { ...MOCK_GENRE_INSIGHTS, slug, display_name: MOCK_GENRE_INSIGHTS.display_name })
      }
      return respond(res, 404, { error: 'no_synthesis', code: 'not_found', slug })
    }
  }

  // Paid-PDF report summary — /api/genres/:slug/report.
  // Only the 'rdb-preorder' and 'rdb-live' test slugs return a row; other
  // slugs 404 so the pre-order/buy block stays hidden.
  {
    const m = path.match(/^\/api\/genres\/([^/]+)\/report$/)
    if (m) {
      const slug = m[1]
      const body = GENRE_REPORT_BY_SLUG[slug]
      if (body) return respond(res, 200, body)
      return respond(res, 404, { error: 'no_report', code: 'not_found', slug })
    }
  }

  // Batched crosslink lookup — used by the genre synthesis page in place
  // of N per-appid /report fetches. Matched BEFORE any /api/games/:id/*
  // routes so "basics" isn't mistaken for an appid segment.
  if (path === '/api/games/basics') {
    const raw = url.searchParams.get('appids') ?? ''
    const appids = raw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
      .map(Number)
      .filter((n) => Number.isFinite(n))
    const games = appids
      .map((appid) => {
        const g = BENCHMARK_GAME_BASICS[appid]
        if (!g) return null
        return {
          appid,
          name: g.name,
          slug: g.slug,
          header_image: `https://cdn.akamai.steamstatic.com/steam/apps/${appid}/header.jpg`,
          positive_pct: g.positive_pct ?? null,
          review_count: g.review_count ?? null,
        }
      })
      .filter((x) => x !== null)
    return respond(res, 200, { games })
  }

  // Benchmark-game reports kept for any other callers that still hit the
  // full /report endpoint (not the genre page anymore). Matched BEFORE the
  // generic /api/games/:id/report fallback so the benchmark game names win.
  {
    const m = path.match(/^\/api\/games\/(\d+)\/report$/)
    if (m && BENCHMARK_GAME_BASICS[Number(m[1])]) {
      const appid = Number(m[1])
      const g = BENCHMARK_GAME_BASICS[appid]
      return respond(res, 200, {
        status: 'available',
        game: {
          slug: g.slug,
          name: g.name,
          header_image: `https://cdn.akamai.steamstatic.com/steam/apps/${appid}/header.jpg`,
          short_desc: `${g.name} test fixture.`,
          developer: 'Test Dev',
          release_date: '2020-01-01',
          price_usd: 19.99,
          is_free: false,
          is_early_access: false,
          genres: ['Roguelike'],
          tags: ['Deckbuilder'],
          positive_pct: 95,
          review_score_desc: 'Overwhelmingly Positive',
          review_count: 1000,
          review_count_english: 800,
        },
      })
    }
  }

  // Specific game reports — registered before the wildcard
  if (path === '/api/games/440/report') {
    const now = new Date()
    const twoHoursAgo = new Date(now.getTime() - 2 * 3600 * 1000).toISOString()
    return respond(res, 200, {
      status: 'available',
      report: MOCK_REPORT,
      game: {
        short_desc: MOCK_GAME_ANALYZED.short_desc,
        developer: MOCK_GAME_ANALYZED.developer,
        release_date: MOCK_GAME_ANALYZED.release_date,
        price_usd: null,
        is_free: true,
        is_early_access: false,
        genres: MOCK_GAME_ANALYZED.genres,
        tags: MOCK_GAME_ANALYZED.tags,
        deck_compatibility: MOCK_GAME_ANALYZED.deck_compatibility,
        deck_test_results: MOCK_GAME_ANALYZED.deck_test_results,
        positive_pct: MOCK_GAME_ANALYZED.positive_pct,
        review_score_desc: MOCK_GAME_ANALYZED.review_score_desc,
        review_count: MOCK_GAME_ANALYZED.review_count,
        review_count_english: MOCK_GAME_ANALYZED.review_count_english,
        meta_crawled_at: twoHoursAgo,
        review_crawled_at: twoHoursAgo,
        reviews_completed_at: twoHoursAgo,
      },
    })
  }

  if (path === '/api/games/9999999/report') {
    const now = new Date()
    const twoHoursAgo = new Date(now.getTime() - 2 * 3600 * 1000).toISOString()
    return respond(res, 200, {
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
        genres: MOCK_GAME_UNANALYZED.genres,
        tags: MOCK_GAME_UNANALYZED.tags,
        deck_compatibility: null,
        deck_test_results: [],
        positive_pct: MOCK_GAME_UNANALYZED.positive_pct,
        review_score_desc: MOCK_GAME_UNANALYZED.review_score_desc,
        review_count: MOCK_GAME_UNANALYZED.review_count,
        review_count_english: MOCK_GAME_UNANALYZED.review_count_english,
        meta_crawled_at: twoHoursAgo,
        review_crawled_at: twoHoursAgo,
        reviews_completed_at: twoHoursAgo,
      },
    })
  }

  // Review stats and benchmarks
  if (/^\/api\/games\/\d+\/review-stats$/.test(path)) {
    return respond(res, 200, MOCK_REVIEW_STATS)
  }

  if (/^\/api\/games\/\d+\/benchmarks$/.test(path)) {
    return respond(res, 200, MOCK_BENCHMARKS)
  }

  // Related analyzed games — tag-overlap neighbors for the un-analyzed page
  if (/^\/api\/games\/\d+\/related-analyzed/.test(path)) {
    return respond(res, 200, {
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
    })
  }

  // Audience overlap
  if (/^\/api\/games\/\d+\/audience-overlap/.test(path)) {
    return respond(res, 200, {
      total_reviewers: 5000,
      overlaps: [
        { appid: 730, name: 'Counter-Strike 2', slug: 'counter-strike-2-730', header_image: null, positive_pct: 82, review_count: 8500000, overlap_count: 1200, overlap_pct: 24.0, shared_sentiment_pct: 78 },
        { appid: 570, name: 'Dota 2', slug: 'dota-2-570', header_image: null, positive_pct: 81, review_count: 2000000, overlap_count: 800, overlap_pct: 16.0, shared_sentiment_pct: 72 },
        { appid: 252490, name: 'Rust', slug: 'rust-252490', header_image: null, positive_pct: 77, review_count: 500000, overlap_count: 400, overlap_pct: 8.0, shared_sentiment_pct: 65 },
      ],
    })
  }

  // Any other /api/games/* report (unknown appid) → return mock report
  if (/^\/api\/games\/\d+\/report$/.test(path)) {
    return respond(res, 200, {
      status: 'available',
      report: MOCK_REPORT,
      game: {
        short_desc: MOCK_GAME_ANALYZED.short_desc,
        header_image: MOCK_GAME_ANALYZED.header_image,
        developer: MOCK_GAME_ANALYZED.developer,
        release_date: MOCK_GAME_ANALYZED.release_date,
        price_usd: null,
        is_free: true,
        is_early_access: false,
        genres: MOCK_GAME_ANALYZED.genres,
        tags: MOCK_GAME_ANALYZED.tags,
        positive_pct: MOCK_GAME_ANALYZED.positive_pct,
        review_score_desc: MOCK_GAME_ANALYZED.review_score_desc,
        review_count: MOCK_GAME_ANALYZED.review_count,
        review_count_english: MOCK_GAME_ANALYZED.review_count_english,
      },
    })
  }

  // Trend analytics
  if (path === '/api/analytics/trends/sentiment') {
    return respond(res, 200, {
      granularity: 'month',
      periods: [
        { period: '2024-01', total: 500, positive_count: 380, mixed_count: 70, negative_count: 50, positive_pct: 76.0, avg_steam_pct: 76.0, avg_metacritic: null },
        { period: '2024-02', total: 520, positive_count: 400, mixed_count: 68, negative_count: 52, positive_pct: 76.9, avg_steam_pct: 76.9, avg_metacritic: null },
        { period: '2024-03', total: 540, positive_count: 420, mixed_count: 65, negative_count: 55, positive_pct: 77.8, avg_steam_pct: 77.8, avg_metacritic: null },
        { period: '2024-04', total: 510, positive_count: 395, mixed_count: 66, negative_count: 49, positive_pct: 77.5, avg_steam_pct: 77.5, avg_metacritic: null },
      ],
    })
  }
  if (path === '/api/analytics/trends/release-volume') {
    return respond(res, 200, {
      granularity: 'month',
      filter: {},
      periods: [
        { period: '2024-01', releases: 1200, avg_steam_pct: 74.2, avg_reviews: 42, free_count: 180 },
        { period: '2024-02', releases: 1350, avg_steam_pct: 75.1, avg_reviews: 38, free_count: 195 },
        { period: '2024-03', releases: 1500, avg_steam_pct: 73.8, avg_reviews: 40, free_count: 210 },
        { period: '2024-04', releases: 1420, avg_steam_pct: 74.5, avg_reviews: 45, free_count: 200 },
      ],
      summary: { total_releases: 5470, avg_per_period: 1368, trend: 'stable' },
    })
  }

  // Genre analytics
  if (path === '/api/analytics/price-positioning') {
    return respond(res, 200, MOCK_PRICE_POSITIONING)
  }
  if (path === '/api/analytics/release-timing') {
    return respond(res, 200, MOCK_RELEASE_TIMING)
  }
  if (path === '/api/analytics/platform-gaps') {
    return respond(res, 200, MOCK_PLATFORM_GAPS)
  }

  // Developer analytics
  if (/^\/api\/developers\/[^/]+\/analytics$/.test(path)) {
    return respond(res, 200, MOCK_DEVELOPER_PORTFOLIO)
  }

  // Genres
  if (path.startsWith('/api/genres')) {
    return respond(res, 200, MOCK_GENRES)
  }

  // Tag trend (before wildcard tags route)
  if (/^\/api\/tags\/[^/]+\/trend$/.test(path)) {
    return respond(res, 200, MOCK_TAG_TREND)
  }

  // Tags grouped (before generic tags route)
  if (path.startsWith('/api/tags/grouped')) {
    return respond(res, 200, MOCK_TAG_GROUPS)
  }

  // Tags
  if (path.startsWith('/api/tags')) {
    return respond(res, 200, MOCK_TAGS)
  }

  // Homepage discovery rows — served from mv_discovery_feeds (pre-computed).
  if (path.startsWith('/api/discovery/')) {
    return respond(res, 200, { games: MOCK_GAMES_LIST.games })
  }

  // Catalog stats (homepage ProofBar)
  if (path === '/api/catalog/stats') {
    return respond(res, 200, { total_games: MOCK_GAMES_LIST.total })
  }

  // Games list (wildcard — must come after specific /report routes)
  if (path.startsWith('/api/games')) {
    return respond(res, 200, MOCK_GAMES_LIST)
  }

  // 404 for anything else
  respond(res, 404, { error: 'Not found' })
})

const PORT = 3001
server.listen(PORT, () => {
  console.log(`Mock API server listening on http://localhost:${PORT}`)
})
