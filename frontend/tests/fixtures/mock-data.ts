// Dynamic-but-stable-per-run freshness timestamps — keeps the relative-time
// helper ("Crawled 2h ago" / "Analyzed 3d ago") rendering realistic values
// without pinning to a wall-clock date that'd rot over time.
const _NOW_MS = Date.now()
const _HOURS_AGO = (h: number) => new Date(_NOW_MS - h * 3600 * 1000).toISOString()
const _DAYS_AGO = (d: number) => new Date(_NOW_MS - d * 86_400 * 1000).toISOString()

export const MOCK_GAME_ANALYZED = {
  appid: 440,
  name: 'Team Fortress 2',
  slug: 'team-fortress-2',
  developer: 'Valve',
  header_image: 'https://cdn.akamai.steamstatic.com/steam/apps/440/header.jpg',
  review_count: 142389,
  positive_pct: 87,
  review_score_desc: 'Very Positive',
  // 0.0-1.0 scale matching the backend; UI scales x100 at the badge boundary.
  hidden_gem_score: 0.12,
  price_usd: null,
  is_free: true,
  is_early_access: false,
  genres: ['Action', 'Free to Play'],
  tags: ['FPS', 'Multiplayer', 'Shooter', 'Team-Based'],
  release_date: '2007-10-10',
  short_desc: 'Nine distinct classes provide a broad range of tactical abilities and personalities.',
  deck_compatibility: 2,
  deck_test_results: [
    { display_type: 3, loc_token: '#SteamDeckVerified_TestResult_DefaultControllerConfigNotFullyFunctional' },
    { display_type: 4, loc_token: '#SteamDeckVerified_TestResult_DefaultConfigurationIsPerformant' },
  ],
  // Steam Facts zone freshness
  meta_crawled_at: _HOURS_AGO(2),
  review_crawled_at: _HOURS_AGO(2),
  reviews_completed_at: _HOURS_AGO(2),
  tags_crawled_at: _HOURS_AGO(2),
  // SteamPulse Analysis zone freshness
  last_analyzed: _DAYS_AGO(3),
}

export const MOCK_GAME_UNANALYZED = {
  appid: 9999999,
  name: 'Obscure Indie Game',
  slug: 'obscure-indie-game',
  developer: 'Small Studio',
  header_image: 'https://cdn.akamai.steamstatic.com/steam/apps/9999999/header.jpg',
  review_count: 42,
  positive_pct: 80,
  review_score_desc: 'Mostly Positive',
  hidden_gem_score: null,
  price_usd: 9.99,
  is_free: false,
  is_early_access: false,
  genres: ['Indie', 'Adventure'],
  tags: ['Indie', 'Adventure', 'Singleplayer'],
  release_date: '2024-06-01',
  short_desc: 'A small indie adventure game.',
  deck_compatibility: null,
  deck_test_results: [],
}

export const MOCK_REPORT = {
  game_name: 'Team Fortress 2',
  appid: 440,
  total_reviews_analyzed: 142389,
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
  // 0.0-1.0 scale (backend); UI multiplies by 100 for the HiddenGemBadge
  hidden_gem_score: 0.12,
  last_analyzed: _DAYS_AGO(3),
}

export const MOCK_GENRES = [
  { id: 1, name: 'Action', slug: 'action', game_count: 12400, analyzed_count: 980 },
  { id: 2, name: 'Indie', slug: 'indie', game_count: 28000, analyzed_count: 1200 },
  { id: 3, name: 'RPG', slug: 'rpg', game_count: 8200, analyzed_count: 740 },
  { id: 4, name: 'Strategy', slug: 'strategy', game_count: 6100, analyzed_count: 510 },
]

export const MOCK_TAGS = [
  { id: 1, name: 'Multiplayer', slug: 'multiplayer', game_count: 8900, category: 'Player Mode' },
  { id: 2, name: 'Singleplayer', slug: 'singleplayer', game_count: 42000, category: 'Player Mode' },
  { id: 3, name: 'Roguelike', slug: 'roguelike', game_count: 3100, category: 'Sub-Genre' },
  { id: 4, name: 'Open World', slug: 'open-world', game_count: 2200, category: 'Gameplay' },
]

export const MOCK_TAG_GROUPS = [
  { category: 'Genre', tags: [{ id: 10, name: 'Action', slug: 'action', game_count: 12000, category: 'Genre' }], total_count: 1 },
  { category: 'Sub-Genre', tags: [{ id: 3, name: 'Roguelike', slug: 'roguelike', game_count: 3100, category: 'Sub-Genre' }], total_count: 1 },
  { category: 'Theme & Setting', tags: [{ id: 11, name: 'Fantasy', slug: 'fantasy', game_count: 6100, category: 'Theme & Setting' }], total_count: 1 },
  { category: 'Gameplay', tags: [{ id: 4, name: 'Open World', slug: 'open-world', game_count: 2200, category: 'Gameplay' }], total_count: 1 },
  { category: 'Player Mode', tags: [{ id: 2, name: 'Singleplayer', slug: 'singleplayer', game_count: 42000, category: 'Player Mode' }], total_count: 1 },
]

export const MOCK_GAMES_LIST = {
  total: 100, // >24 so pagination renders in SearchClient
  games: [MOCK_GAME_ANALYZED, MOCK_GAME_UNANALYZED],
}

export const MOCK_REVIEW_STATS = {
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

// Fewer than 3 timeline entries — timeline chart should NOT render
export const MOCK_REVIEW_STATS_SPARSE = {
  timeline: [
    { week: '2024-01-01', total: 10, positive: 8, pct_positive: 80 },
  ],
  playtime_buckets: [
    { bucket: '<2h', reviews: 5, pct_positive: 80 },
  ],
  review_velocity: {
    reviews_per_day: 0.5,
    reviews_last_30_days: 10,
  },
}

export const MOCK_BENCHMARKS = {
  sentiment_rank: 0.77,
  popularity_rank: 0.45,
  cohort_size: 312,
}

// Analytics trend mock data

const PERIODS_MONTHLY = ['2024-01', '2024-02', '2024-03', '2024-04', '2024-05', '2024-06']

// Releases: 100, 110, 120, 130, 140, 150 → total=750, avg=125
export const MOCK_RELEASE_VOLUME = {
  granularity: 'month',
  filter: {},
  periods: PERIODS_MONTHLY.map((period, i) => ({
    period,
    releases: 100 + i * 10,
    avg_steam_pct: 70.0 + i * 1,  // 0–100 scale (AVG of games.positive_pct)
    avg_reviews: 45 + i * 2,
    free_count: 20 + i,
  })),
  summary: { total_releases: 750, avg_per_period: 125, trend: 'increasing' },
}

export const MOCK_SENTIMENT_DIST = {
  granularity: 'month',
  periods: PERIODS_MONTHLY.map((period, i) => ({
    period,
    total: 100,
    positive_count: 60 + i,
    mixed_count: 20,
    negative_count: 20 - i,
    positive_pct: 60 + i,
    avg_steam_pct: 72.0 + i,
    avg_metacritic: 72.0,
  })),
}

export const MOCK_GENRE_SHARE = {
  granularity: 'year',
  genres: ['Action', 'Indie', 'RPG', 'Strategy', 'Other'],
  periods: PERIODS_MONTHLY.map((period) => ({
    period,
    total: 100,
    // Backend returns 0–1 fractions (round(count/total, 2))
    shares: { Action: 0.30, Indie: 0.25, RPG: 0.20, Strategy: 0.15, Other: 0.10 },
  })),
}

export const MOCK_VELOCITY_DIST = {
  granularity: 'month',
  periods: PERIODS_MONTHLY.map((period, i) => ({
    period,
    total: 100 + i,
    velocity_under_1: 50 + i,
    velocity_1_10: 30,
    velocity_10_50: 15,
    velocity_50_plus: 5,
  })),
}

export const MOCK_PRICING = {
  granularity: 'quarter',
  periods: PERIODS_MONTHLY.map((period, i) => ({
    period,
    total: 100 + i * 10,
    avg_paid_price: 12.5 + i * 0.5,
    avg_price_incl_free: 10.0 + i * 0.3,
    free_count: 20 + i,
    free_pct: 20 - i,
  })),
}

export const MOCK_EARLY_ACCESS = {
  granularity: 'quarter',
  periods: PERIODS_MONTHLY.map((period, i) => ({
    period,
    total_releases: 200 + i * 10,
    ea_count: 30 + i,
    ea_pct: 15 + i * 0.5,
    ea_avg_steam_pct: 65.0,   // 0–100 scale (AVG of games.positive_pct)
    non_ea_avg_steam_pct: 72.0,
  })),
}

export const MOCK_PLATFORMS = {
  granularity: 'quarter',
  periods: PERIODS_MONTHLY.map((period, i) => ({
    period,
    total: 100 + i * 10,
    mac_pct: 12 + i * 0.2,
    linux_pct: 8 + i * 0.1,
    deck_verified_pct: 20 + i,
    deck_playable_pct: 35 + i,
    deck_unsupported_pct: 10 + i,
  })),
}

export const MOCK_ENGAGEMENT = {
  granularity: 'year',
  data_available: true,
  periods: PERIODS_MONTHLY.map((period) => ({
    period,
    total_reviews: 500,
    playtime_under_2h_pct: 15,
    playtime_2_10h_pct: 25,
    playtime_10_50h_pct: 35,
    playtime_50_200h_pct: 18,
    playtime_200h_plus_pct: 7,
  })),
}

export const MOCK_ENGAGEMENT_UNAVAILABLE = {
  granularity: 'year',
  data_available: false,
  periods: [],
}

export const MOCK_CATEGORIES = {
  granularity: 'year',
  categories: ['VR Supported', 'Co-op', 'Full controller support'],
  periods: PERIODS_MONTHLY.map((period, i) => ({
    period,
    total: 100 + i,
    adoption: { 'VR Supported': 0.05, 'Co-op': 0.35, 'Full controller support': 0.60 },
  })),
}

// Per-entity analytics mock data

export const MOCK_AUDIENCE_OVERLAP = {
  total_reviewers: 5432,
  overlaps: [
    {
      appid: 570, name: 'Dota 2', slug: 'dota-2-570',
      header_image: 'https://cdn.akamai.steamstatic.com/steam/apps/570/header.jpg',
      positive_pct: 82, review_count: 1800000,
      overlap_count: 342, overlap_pct: 6.3, shared_sentiment_pct: 78.5,
    },
    {
      appid: 730, name: 'Counter-Strike 2', slug: 'counter-strike-2-730',
      header_image: 'https://cdn.akamai.steamstatic.com/steam/apps/730/header.jpg',
      positive_pct: 85, review_count: 8500000,
      overlap_count: 289, overlap_pct: 5.3, shared_sentiment_pct: 71.2,
    },
    {
      appid: 220, name: 'Half-Life 2', slug: 'half-life-2-220',
      header_image: 'https://cdn.akamai.steamstatic.com/steam/apps/220/header.jpg',
      positive_pct: 97, review_count: 180000,
      overlap_count: 156, overlap_pct: 2.9, shared_sentiment_pct: 95.1,
    },
  ],
}

export const MOCK_PLAYTIME_SENTIMENT = {
  buckets: [
    { bucket: '0h', total: 50, positive: 20, negative: 30, pct_positive: 40.0 },
    { bucket: '<1h', total: 120, positive: 60, negative: 60, pct_positive: 50.0 },
    { bucket: '1-2h', total: 200, positive: 140, negative: 60, pct_positive: 70.0 },
    { bucket: '2-5h', total: 300, positive: 240, negative: 60, pct_positive: 80.0 },
    { bucket: '5-10h', total: 250, positive: 210, negative: 40, pct_positive: 84.0 },
    { bucket: '10-20h', total: 180, positive: 135, negative: 45, pct_positive: 75.0 },
    { bucket: '20-50h', total: 100, positive: 60, negative: 40, pct_positive: 60.0 },
  ],
  churn_point: { bucket: '20-50h', drop_from: 75.0, drop_to: 60.0, delta: -15.0 },
  median_playtime_hours: 8,
  value_score: 1.6,
}

export const MOCK_EA_IMPACT = {
  has_ea_reviews: true,
  early_access: { total: 500, positive: 360, pct_positive: 72.0, avg_playtime: 8.5 },
  post_launch: { total: 1200, positive: 1020, pct_positive: 85.0, avg_playtime: 24.3 },
  impact_delta: 13.0,
  verdict: 'improved' as const,
}

export const MOCK_REVIEW_VELOCITY = {
  monthly: [
    { month: '2025-01', total: 85, positive: 68, pct_positive: 80.0 },
    { month: '2025-02', total: 92, positive: 76, pct_positive: 82.6 },
    { month: '2025-03', total: 110, positive: 88, pct_positive: 80.0 },
  ],
  summary: {
    avg_monthly: 85.5,
    last_30_days: 110,
    last_3_months_avg: 95.7,
    peak_month: { month: '2025-03', total: 110 },
    trend: 'accelerating' as const,
  },
}

export const MOCK_TOP_REVIEWS = {
  sort: 'helpful',
  reviews: [
    {
      steam_review_id: '170501_440', voted_up: true, playtime_hours: 450,
      body_preview: 'This game is an absolute masterpiece that changed how I think about multiplayer shooters.',
      votes_helpful: 1523, votes_funny: 42,
      posted_at: '2024-01-15T12:00:00Z',
      written_during_early_access: false, received_for_free: false,
    },
    {
      steam_review_id: '170502_440', voted_up: false, playtime_hours: 2,
      body_preview: 'Constant crashes on startup. Refunded after 30 minutes of troubleshooting.',
      votes_helpful: 892, votes_funny: 5,
      posted_at: '2024-02-20T15:30:00Z',
      written_during_early_access: false, received_for_free: false,
    },
  ],
}

export const MOCK_PRICE_POSITIONING = {
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

export const MOCK_RELEASE_TIMING = {
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

export const MOCK_PLATFORM_GAPS = {
  genre: 'Action',
  total_games: 500,
  platforms: {
    windows: { count: 498, pct: 99.6, avg_steam_pct: 71.2 },
    mac: { count: 175, pct: 35.0, avg_steam_pct: 73.5 },
    linux: { count: 110, pct: 22.0, avg_steam_pct: 75.1 },
  },
  underserved: 'linux',
}

export const MOCK_TAG_TREND = {
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

export const MOCK_DEVELOPER_PORTFOLIO = {
  developer: 'Valve', developer_slug: 'valve',
  summary: {
    total_games: 3, total_reviews: 10500000, avg_steam_pct: 88.5,
    first_release: '2004-11-16', latest_release: '2023-09-27',
    avg_price: 9.99, free_games: 2, well_received: 3, poorly_received: 0,
    sentiment_trajectory: 'stable' as const,
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

// Edge-case variants
export const MOCK_EA_IMPACT_NO_EA = {
  has_ea_reviews: false,
  early_access: null,
  post_launch: { total: 100, positive: 80, pct_positive: 80.0, avg_playtime: 15.0 },
  impact_delta: null,
  verdict: 'no_ea' as const,
}

export const MOCK_PLAYTIME_SENTIMENT_NO_CHURN = {
  buckets: [
    { bucket: '0h', total: 50, positive: 40, negative: 10, pct_positive: 80.0 },
    { bucket: '<1h', total: 120, positive: 100, negative: 20, pct_positive: 83.3 },
  ],
  churn_point: null,
  median_playtime_hours: 5,
  value_score: null,
}
