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

// ---------------------------------------------------------------------------
// Per-entity analytics (game report, genre, tag, developer pages)
// ---------------------------------------------------------------------------

// Feature 1: Audience Overlap
export interface AudienceOverlap {
  total_reviewers: number;
  overlaps: AudienceOverlapEntry[];
}

export interface AudienceOverlapEntry {
  appid: number;
  name: string;
  slug: string;
  header_image: string;
  positive_pct: number;
  review_count: number;
  overlap_count: number;
  overlap_pct: number;
  shared_sentiment_pct: number;
}

// Feature 2: Playtime Sentiment
export interface PlaytimeSentiment {
  buckets: PlaytimeSentimentBucket[];
  churn_point: ChurnPoint | null;
  median_playtime_hours: number;
  value_score: number | null;
}

export interface PlaytimeSentimentBucket {
  bucket: string;
  total: number;
  positive: number;
  negative: number;
  pct_positive: number;
}

export interface ChurnPoint {
  bucket: string;
  drop_from: number;
  drop_to: number;
  delta: number;
}

// Feature 3: Early Access Impact
export interface EarlyAccessImpact {
  has_ea_reviews: boolean;
  early_access: ReviewSegment | null;
  post_launch: ReviewSegment | null;
  impact_delta: number | null;
  verdict: "improved" | "declined" | "stable" | "no_ea";
}

export interface ReviewSegment {
  total: number;
  positive: number;
  pct_positive: number;
  avg_playtime: number;
}

// Feature 5: Review Velocity
export interface ReviewVelocity {
  monthly: VelocityMonth[];
  summary: VelocitySummary;
}

export interface VelocityMonth {
  month: string;
  total: number;
  positive: number;
  pct_positive: number;
}

export interface VelocitySummary {
  avg_monthly: number;
  last_30_days: number;
  last_3_months_avg: number;
  peak_month: { month: string; total: number };
  trend: "accelerating" | "stable" | "decelerating";
}

// Feature 6: Top Reviews
export interface TopReviewsResponse {
  sort: string;
  reviews: TopReview[];
}

export interface TopReview {
  steam_review_id: string;
  voted_up: boolean;
  playtime_hours: number;
  body_preview: string;
  votes_helpful: number;
  votes_funny: number;
  posted_at: string;
  written_during_early_access: boolean;
  received_for_free: boolean;
}

// Feature 7: Price Positioning
export interface PricePositioning {
  genre: string;
  genre_slug: string;
  distribution: PriceRange[];
  summary: PriceSummary;
}

export interface PriceRange {
  price_range: string;
  game_count: number;
  avg_sentiment: number;
  median_price: number;
}

export interface PriceSummary {
  avg_price: number;
  median_price: number;
  free_count: number;
  paid_count: number;
  sweet_spot: string;
}

// Feature 8: Release Timing
export interface ReleaseTiming {
  genre: string;
  monthly: ReleaseMonth[];
  best_month: MonthHighlight;
  worst_month: MonthHighlight;
  quietest_month: MonthHighlight;
  busiest_month: MonthHighlight;
}

export interface ReleaseMonth {
  month: number;
  month_name: string;
  releases: number;
  avg_sentiment: number;
  avg_reviews: number;
}

export interface MonthHighlight {
  month: number;
  month_name: string;
  releases?: number;
  avg_sentiment?: number;
}

// Feature 9: Platform Gaps
export interface PlatformGaps {
  genre: string;
  total_games: number;
  platforms: {
    windows: PlatformStats;
    mac: PlatformStats;
    linux: PlatformStats;
  };
  underserved: string;
}

export interface PlatformStats {
  count: number;
  pct: number;
  avg_sentiment: number;
}

// Feature 10: Tag Trend
export interface TagTrend {
  tag: string;
  tag_slug: string;
  yearly: TagYear[];
  growth_rate: number;
  peak_year: number;
  total_games: number;
}

export interface TagYear {
  year: number;
  game_count: number;
  avg_sentiment: number;
}

// Feature 11: Developer Portfolio
export interface DeveloperPortfolio {
  developer: string;
  developer_slug: string;
  summary: DeveloperSummary;
  games: DeveloperGame[];
}

export interface DeveloperSummary {
  total_games: number;
  total_reviews: number;
  avg_sentiment: number;
  first_release: string;
  latest_release: string;
  avg_price: number | null;
  free_games: number;
  well_received: number;
  poorly_received: number;
  sentiment_trajectory: "improving" | "stable" | "declining" | "single_title" | "no_games";
}

export interface DeveloperGame {
  appid: number;
  name: string;
  slug: string;
  header_image: string;
  release_date: string;
  price_usd: number | null;
  is_free: boolean;
  review_count: number;
  positive_pct: number;
  review_score_desc: string;
  metacritic_score: number | null;
  achievements_total: number | null;
}
