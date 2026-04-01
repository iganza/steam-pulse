// TypeScript types matching steampulse/analyzer.py schema exactly

export interface AudienceProfile {
  ideal_player: string;
  casual_friendliness: string;
  archetypes: string[];
  not_for: string[];
}

export interface DevPriority {
  action: string;
  why_it_matters: string;
  frequency: string;
  effort: string;
}

export interface CompetitorRef {
  game: string;
  comparison_sentiment: string;
  note: string;
}

/** Full report — returned by /api/games/{appid}/report and /api/status when complete */
export interface GameReport {
  game_name: string;
  appid: number;
  total_reviews_analyzed: number;
  overall_sentiment: string;
  sentiment_score: number; // 0–100
  sentiment_trend: string;
  sentiment_trend_note: string;
  one_liner: string;
  audience_profile: AudienceProfile;
  design_strengths: string[];
  gameplay_friction: string[];
  player_wishlist: string[];
  churn_triggers: string[];
  dev_priorities: DevPriority[];
  competitive_context: CompetitorRef[];
  genre_context: string;
  hidden_gem_score: number; // 0–100
  last_analyzed?: string; // ISO timestamp
}

/** Free preview — returned by POST /api/preview */
export interface PreviewResponse {
  game_name: string;
  appid: number;
  overall_sentiment: string;
  sentiment_score: number;
  one_liner: string;
  audience_profile?: AudienceProfile;
  job_id?: string; // present when report is being generated async
  error?: string;
  code?: string;
}

/** Async job status — returned by GET /api/status/{job_id} */
export interface JobStatus {
  status: "RUNNING" | "SUCCEEDED" | "FAILED" | "TIMED_OUT";
  report?: GameReport;
  error?: string;
}

export interface DeckTestResult {
  display_type: number;
  loc_token: string;
}

/** Game row from DB — used on listing pages */
export interface Game {
  appid: number;
  name: string;
  slug: string;
  short_desc?: string;
  developer?: string;
  header_image?: string;
  review_count?: number;
  review_count_english?: number;
  positive_pct?: number;
  hidden_gem_score?: number;
  sentiment_score?: number;
  price_usd?: number;
  is_free?: boolean;
  genres?: string[];
  tags?: string[];
  release_date?: string;
  deck_compatibility?: number | null;
  deck_test_results?: DeckTestResult[];
}

export interface TimelineEntry {
  week: string;
  total: number;
  positive: number;
  pct_positive: number;
}

export interface PlaytimeBucket {
  bucket: string;
  reviews: number;
  pct_positive: number;
}

export interface ReviewStats {
  timeline: TimelineEntry[];
  playtime_buckets: PlaytimeBucket[];
  review_velocity: {
    reviews_per_day: number;
    reviews_last_30_days: number;
  };
}

export interface Benchmarks {
  sentiment_rank: number | null;
  popularity_rank: number | null;
  cohort_size: number;
}

export interface Genre {
  id: number;
  name: string;
  slug: string;
  game_count?: number;
  analyzed_count?: number;
}

export interface Tag {
  id: number;
  name: string;
  slug: string;
  game_count?: number;
  analyzed_count?: number;
}

// ---------------------------------------------------------------------------
// Analytics Dashboard — trend types
// ---------------------------------------------------------------------------

export type Granularity = "week" | "month" | "quarter" | "year";

export interface TrendPeriod {
  period: string;
}

export interface ReleaseVolumePeriod extends TrendPeriod {
  releases: number;
  avg_sentiment: number | null;
  avg_reviews: number;
  free_count: number;
}

export interface SentimentDistPeriod extends TrendPeriod {
  total: number;
  positive_count: number;
  mixed_count: number;
  negative_count: number;
  positive_pct: number;
  avg_sentiment: number | null;
  avg_metacritic: number | null;
}

export interface GenreSharePeriod extends TrendPeriod {
  total: number;
  shares: Record<string, number>;
}

export interface VelocityDistPeriod extends TrendPeriod {
  total: number;
  velocity_under_1: number;
  velocity_1_10: number;
  velocity_10_50: number;
  velocity_50_plus: number;
}

export interface PriceTrendPeriod extends TrendPeriod {
  total: number;
  avg_paid_price: number | null;
  avg_price_incl_free: number | null;
  free_count: number;
  free_pct: number;
}

export interface EATrendPeriod extends TrendPeriod {
  total_releases: number;
  ea_count: number;
  ea_pct: number;
  ea_avg_sentiment: number | null;
  non_ea_avg_sentiment: number | null;
}

export interface PlatformTrendPeriod extends TrendPeriod {
  total: number;
  mac_pct: number;
  linux_pct: number;
  deck_verified_pct: number;
  deck_playable_pct: number;
  deck_unsupported_pct: number;
}

export interface EngagementDepthPeriod extends TrendPeriod {
  total_reviews: number;
  playtime_under_2h_pct: number;
  playtime_2_10h_pct: number;
  playtime_10_50h_pct: number;
  playtime_50_200h_pct: number;
  playtime_200h_plus_pct: number;
}

export interface CategoryTrendPeriod extends TrendPeriod {
  total: number;
  adoption: Record<string, number>;
}
