export const MOCK_GAME_ANALYZED = {
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

export const MOCK_GAME_UNANALYZED = {
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

export const MOCK_REPORT = {
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

export const MOCK_GENRES = [
  { id: 1, name: 'Action', slug: 'action', game_count: 12400, analyzed_count: 980 },
  { id: 2, name: 'Indie', slug: 'indie', game_count: 28000, analyzed_count: 1200 },
  { id: 3, name: 'RPG', slug: 'rpg', game_count: 8200, analyzed_count: 740 },
  { id: 4, name: 'Strategy', slug: 'strategy', game_count: 6100, analyzed_count: 510 },
]

export const MOCK_TAGS = [
  { id: 1, name: 'Multiplayer', slug: 'multiplayer', game_count: 8900 },
  { id: 2, name: 'Singleplayer', slug: 'singleplayer', game_count: 42000 },
  { id: 3, name: 'Roguelike', slug: 'roguelike', game_count: 3100 },
  { id: 4, name: 'Open World', slug: 'open-world', game_count: 2200 },
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
  periods: PERIODS_MONTHLY.map((period, i) => ({
    period,
    releases: 100 + i * 10,
    avg_sentiment: 70.0 + i * 1,  // 0–100 scale (sentiment_score in DB)
    avg_reviews: 45 + i * 2,
    free_count: 20 + i,
  })),
  summary: { total_releases: 750, avg_per_period: 125, trend: 'increasing' },
}

export const MOCK_SENTIMENT_DIST = {
  periods: PERIODS_MONTHLY.map((period, i) => ({
    period,
    total: 100,
    positive_count: 60 + i,
    mixed_count: 20,
    negative_count: 20 - i,
    positive_pct: 60 + i,
    avg_sentiment: 72.0 + i,
    avg_metacritic: 72.0,
  })),
}

export const MOCK_GENRE_SHARE = {
  genres: ['Action', 'Indie', 'RPG', 'Strategy', 'Other'],
  periods: PERIODS_MONTHLY.map((period) => ({
    period,
    // Backend returns 0–1 fractions (round(count/total, 2))
    shares: { Action: 0.30, Indie: 0.25, RPG: 0.20, Strategy: 0.15, Other: 0.10 },
  })),
}

export const MOCK_VELOCITY_DIST = {
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
  periods: PERIODS_MONTHLY.map((period, i) => ({
    period,
    total_releases: 200 + i * 10,
    ea_count: 30 + i,
    ea_pct: 15 + i * 0.5,
    ea_avg_sentiment: 65.0,   // 0–100 scale (AVG of sentiment_score)
    non_ea_avg_sentiment: 72.0,
  })),
}

export const MOCK_PLATFORMS = {
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
  data_available: false,
  periods: [],
}

export const MOCK_CATEGORIES = {
  categories: ['VR Support', 'Co-op', 'Controller Support'],
  periods: PERIODS_MONTHLY.map((period, i) => ({
    period,
    total: 100 + i,
    adoption: { 'VR Support': 0.05, 'Co-op': 0.35, 'Controller Support': 0.60 },
  })),
}
