/**
 * Lightweight mock API server for Playwright E2E tests.
 *
 * Next.js server components call `API_URL` for SSR data fetches. Playwright's
 * `page.route()` only intercepts browser-side requests, so a real HTTP server
 * is required to serve SSR API calls during testing.
 *
 * This server is started by playwright.config.ts as a webServer. Set
 * `API_URL=http://localhost:8000` so Next.js server components reach it.
 */

import http from 'http'

// ── Mock data (mirrors frontend/tests/fixtures/mock-data.ts) ─────────────────

const MOCK_GAME_ANALYZED = {
  appid: 440,
  name: 'Team Fortress 2',
  slug: 'team-fortress-2',
  developer: 'Valve',
  header_image: 'https://cdn.akamai.steamstatic.com/steam/apps/440/header.jpg',
  review_count: 142389,
  positive_pct: 0.967,
  hidden_gem_score: 12,
  sentiment_score: 87,
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
  positive_pct: 0.80,
  hidden_gem_score: null,
  sentiment_score: null,
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
  total_reviews_analyzed: 142389,
  overall_sentiment: 'Overwhelmingly Positive',
  sentiment_score: 87,
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
  { id: 1, name: 'Multiplayer', slug: 'multiplayer', game_count: 8900 },
  { id: 2, name: 'Singleplayer', slug: 'singleplayer', game_count: 42000 },
  { id: 3, name: 'Roguelike', slug: 'roguelike', game_count: 3100 },
  { id: 4, name: 'Open World', slug: 'open-world', game_count: 2200 },
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

// ── Router ────────────────────────────────────────────────────────────────────

function json(res, data, status = 200) {
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
  })
  res.end(JSON.stringify(data))
}

const server = http.createServer((req, res) => {
  if (req.method === 'OPTIONS') {
    res.writeHead(204, { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS' })
    res.end()
    return
  }

  const url = new URL(req.url ?? '/', 'http://localhost:8000')
  const path = url.pathname

  // Health check — used by playwright webServer url check
  if (path === '/api/health' || path === '/health') {
    return json(res, { ok: true })
  }

  // Game report: GET /api/games/{appid}/report
  const reportMatch = path.match(/^\/api\/games\/(\d+)\/report$/)
  if (reportMatch) {
    const appid = Number(reportMatch[1])
    if (appid === 440) {
      return json(res, {
        status: 'available',
        report: MOCK_REPORT,
        game: {
          short_desc: MOCK_GAME_ANALYZED.short_desc,
          developer: MOCK_GAME_ANALYZED.developer,
          release_date: MOCK_GAME_ANALYZED.release_date,
          price_usd: MOCK_GAME_ANALYZED.price_usd,
          is_free: MOCK_GAME_ANALYZED.is_free,
          genres: MOCK_GAME_ANALYZED.genres,
          tags: MOCK_GAME_ANALYZED.tags,
          deck_compatibility: MOCK_GAME_ANALYZED.deck_compatibility,
          deck_test_results: MOCK_GAME_ANALYZED.deck_test_results,
        },
      })
    }
    // Appid 441: deck_compatibility 3 (Verified) — used by the Deck Verified badge test
    if (appid === 441) {
      return json(res, {
        status: 'available',
        report: { ...MOCK_REPORT, game_name: 'Deck Verified Game', appid: 441 },
        game: {
          short_desc: 'A fully Steam Deck Verified game.',
          developer: 'Valve',
          release_date: '2022-02-25',
          price_usd: 29.99,
          is_free: false,
          genres: ['Action'],
          tags: ['Action'],
          deck_compatibility: 3,
          deck_test_results: [
            { display_type: 2, loc_token: '#SteamDeckVerified_TestResult_DefaultConfigurationIsPerformant' },
          ],
        },
      })
    }
    // Unknown / unanalyzed game
    return json(res, {
      status: 'not_available',
      review_count: 42,
      threshold: 500,
      game: {
        short_desc: MOCK_GAME_UNANALYZED.short_desc,
        developer: MOCK_GAME_UNANALYZED.developer,
        release_date: MOCK_GAME_UNANALYZED.release_date,
        price_usd: MOCK_GAME_UNANALYZED.price_usd,
        is_free: MOCK_GAME_UNANALYZED.is_free,
        genres: MOCK_GAME_UNANALYZED.genres,
        tags: MOCK_GAME_UNANALYZED.tags,
        deck_compatibility: MOCK_GAME_UNANALYZED.deck_compatibility,
        deck_test_results: MOCK_GAME_UNANALYZED.deck_test_results,
      },
    })
  }

  // Review stats: GET /api/games/{appid}/review-stats
  const reviewStatsMatch = path.match(/^\/api\/games\/(\d+)\/review-stats$/)
  if (reviewStatsMatch) {
    return json(res, MOCK_REVIEW_STATS)
  }

  // Benchmarks: GET /api/games/{appid}/benchmarks
  const benchmarksMatch = path.match(/^\/api\/games\/(\d+)\/benchmarks$/)
  if (benchmarksMatch) {
    return json(res, MOCK_BENCHMARKS)
  }

  // Tags top: GET /api/tags/top
  if (path === '/api/tags/top') {
    return json(res, MOCK_TAGS)
  }

  // Tags by slug: GET /api/tags/{slug}
  if (path.startsWith('/api/tags/')) {
    return json(res, MOCK_TAGS)
  }

  // Genres: GET /api/genres
  if (path === '/api/genres') {
    return json(res, MOCK_GENRES)
  }

  // Preview: POST /api/preview
  if (path === '/api/preview') {
    return json(res, {
      game_name: MOCK_GAME_ANALYZED.name,
      overall_sentiment: MOCK_REPORT.overall_sentiment,
      sentiment_score: MOCK_REPORT.sentiment_score,
      one_liner: MOCK_REPORT.one_liner,
    })
  }

  // Games list: GET /api/games (with any query params)
  if (path === '/api/games') {
    return json(res, MOCK_GAMES_LIST)
  }

  // Catch-all: empty games list
  json(res, { total: 0, games: [] })
})

const PORT = 8000
server.listen(PORT, () => {
  console.log(`Mock API server listening on http://localhost:${PORT}`)
})
