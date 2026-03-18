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
