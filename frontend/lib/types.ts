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

/** Full report — returned by /api/games/{appid}/report and /api/status when complete.
 *
 * NOTE: sentiment magnitude (positive_pct / review_score_desc) is owned by Steam
 * and lives on the `Game` object, NOT here. The report is narrative-only —
 * branded as AI ("SteamPulse Analysis") in the UI.
 */
export interface GameReport {
  game_name: string;
  appid: number;
  total_reviews_analyzed: number;
  sentiment_trend: string;
  sentiment_trend_note: string;
  sentiment_trend_reliable?: boolean;
  sentiment_trend_sample_size?: number;
  one_liner: string;
  audience_profile: AudienceProfile;
  design_strengths: string[];
  gameplay_friction: string[];
  player_wishlist: string[];
  churn_triggers: string[];
  dev_priorities: DevPriority[];
  competitive_context: CompetitorRef[];
  genre_context: string;
  hidden_gem_score: number; // 0.0–1.0 (backend scale); UI scales x100 at the badge boundary
  technical_issues?: string[];
  refund_signals?: RefundSignals | null;
  community_health?: CommunityHealth | null;
  monetization_sentiment?: MonetizationSentiment | null;
  content_depth?: ContentDepth | null;
  store_page_alignment?: StorePageAlignment | null;
  last_analyzed?: string; // ISO timestamp
  review_date_range_start?: string | null;
  review_date_range_end?: string | null;
}

export interface RefundSignals {
  refund_language_frequency: "none" | "rare" | "moderate" | "frequent";
  primary_refund_drivers: string[];
  risk_level: "low" | "medium" | "high";
}

export interface CommunityHealth {
  overall: "thriving" | "active" | "declining" | "dead" | "not_applicable";
  signals: string[];
  multiplayer_population: "healthy" | "shrinking" | "critical" | "not_applicable";
}

export interface MonetizationSentiment {
  overall: "fair" | "mixed" | "predatory" | "not_applicable";
  signals: string[];
  dlc_sentiment: "positive" | "mixed" | "negative" | "not_applicable";
}

export interface ContentDepth {
  perceived_length: "short" | "medium" | "long" | "endless";
  replayability: "low" | "medium" | "high";
  value_perception: "poor" | "fair" | "good" | "excellent";
  signals: string[];
  confidence: "low" | "medium" | "high";
  sample_size: number;
}

export interface StorePageAlignment {
  promises_delivered: string[];
  promises_broken: string[];
  hidden_strengths: string[];
  audience_match: "aligned" | "partial_mismatch" | "significant_mismatch";
  audience_match_note: string;
}

export interface DeckTestResult {
  display_type: number;
  loc_token: string;
}

/** Game row from DB — used on listing pages.
 *
 * Sentiment fields come straight from Steam (positive_pct, review_score_desc).
 * The legacy AI `sentiment_score` was dropped in the data-source-clarity refactor;
 * UI must source sentiment exclusively from positive_pct here. */
export interface Game {
  appid: number;
  name: string;
  slug: string;
  short_desc?: string;
  developer?: string;
  developer_slug?: string;
  publisher?: string;
  publisher_slug?: string;
  header_image?: string;
  review_count?: number;
  review_count_english?: number;
  positive_pct?: number;
  review_score_desc?: string | null;
  // English-only post-release split (migration 0048). Derived locally from the
  // reviews table (English-only by construction). NOT NULL DEFAULT on the DB
  // side, so these are always numbers / string — not optional at the source.
  // Kept optional in the TS type only because pre-0048 cached mocks may omit them.
  review_count_post_release?: number;
  positive_count_post_release?: number;
  positive_pct_post_release?: number;
  review_score_desc_post_release?: string;
  has_early_access_reviews?: boolean;
  coming_soon?: boolean;
  hidden_gem_score?: number;
  price_usd?: number;
  is_free?: boolean;
  is_early_access?: boolean;
  genres?: string[];
  tags?: string[];
  release_date?: string;
  deck_compatibility?: number | null;
  deck_test_results?: DeckTestResult[];
  // Per-source freshness — surfaced in the Steam Facts zone on the detail page
  meta_crawled_at?: string | null;
  review_crawled_at?: string | null;
  reviews_completed_at?: string | null;
  tags_crawled_at?: string | null;
  last_analyzed?: string | null;
  // Boxleiter v1 revenue estimate — surfaced by the report endpoint on the
  // `game` block (handler.py omits keys when unset). Ranges and Pro gating
  // are rendered frontend-side by <MarketReach />.
  estimated_owners?: number | null;
  estimated_revenue_usd?: number | null;
  revenue_estimate_method?: string | null;
  // Machine-readable reason code when no numeric estimate is available —
  // one of: "insufficient_reviews" | "free_to_play" | "missing_price" |
  // "excluded_type". Populated independently of the numeric fields.
  revenue_estimate_reason?: string | null;
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
  category?: string;
}

export interface TagGroup {
  category: string;
  tags: Tag[];
  total_count: number;
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
  avg_steam_pct: number | null;
  avg_reviews: number;
  free_count: number;
}

export interface SentimentDistPeriod extends TrendPeriod {
  total: number;
  positive_count: number;
  mixed_count: number;
  negative_count: number;
  positive_pct: number;
  avg_steam_pct: number | null;
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
  ea_avg_steam_pct: number | null;
  non_ea_avg_steam_pct: number | null;
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
  header_image: string | null;
  positive_pct: number | null;
  review_count: number | null;
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
  verdict: "improved" | "declined" | "stable" | "no_ea" | "no_post";
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
  peak_month: { month: string; total: number } | null;
  trend: "accelerating" | "stable" | "decelerating";
}

// Feature 6: Top Reviews
export type TopReviewsSort = "helpful" | "funny";

export interface TopReviewsResponse {
  sort: TopReviewsSort;
  reviews: TopReview[];
}

export interface TopReview {
  steam_review_id: string;
  voted_up: boolean;
  playtime_hours: number | null;
  body_preview: string;
  votes_helpful: number;
  votes_funny: number;
  posted_at: string | null;
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
  avg_steam_pct: number | null;
  median_price: number;
}

export interface PriceSummary {
  avg_price: number | null;
  median_price: number | null;
  free_count: number;
  paid_count: number;
  sweet_spot: string | null;
}

// Feature 8: Release Timing
export interface ReleaseTiming {
  genre: string;
  monthly: ReleaseMonth[];
  best_month: MonthHighlight | null;
  worst_month: MonthHighlight | null;
  quietest_month: MonthHighlight | null;
  busiest_month: MonthHighlight | null;
}

export interface ReleaseMonth {
  month: number;
  month_name: string;
  releases: number;
  avg_steam_pct: number | null;
  avg_reviews: number;
}

export interface MonthHighlight {
  month: number;
  month_name: string;
  releases?: number;
  avg_steam_pct?: number;
}

// Feature 9: Platform Gaps
export interface PlatformGaps {
  genre: string;
  total_games: number;
  platforms: {
    windows?: PlatformStats;
    mac?: PlatformStats;
    linux?: PlatformStats;
  };
  underserved: "windows" | "mac" | "linux" | null;
}

export interface PlatformStats {
  count: number;
  pct: number;
  avg_steam_pct: number | null;
}

// Feature 10: Tag Trend
export interface TagTrend {
  tag: string;
  tag_slug: string;
  yearly: TagYear[];
  growth_rate: number | null;
  peak_year: number | null;
  total_games: number;
}

export interface TagYear {
  year: number;
  game_count: number;
  avg_steam_pct: number | null;
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
  avg_steam_pct: number;
  first_release: string | null;
  latest_release: string | null;
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
  header_image: string | null;
  release_date: string | null;
  price_usd: number | null;
  is_free: boolean;
  review_count: number | null;
  positive_pct: number | null;
  review_score_desc: string | null;
  metacritic_score: number | null;
  achievements_total: number | null;
}

// Feature 11b: Publisher Portfolio — mirrors DeveloperPortfolio
export interface PublisherPortfolio {
  publisher: string;
  publisher_slug: string;
  summary: PublisherSummary;
  games: PublisherGame[];
}

export type PublisherSummary = DeveloperSummary;
export type PublisherGame = DeveloperGame;

// ---------------------------------------------------------------------------
// Builder lens — metric catalog + generic trend query
// ---------------------------------------------------------------------------

export type MetricUnit = "count" | "pct" | "currency" | "score";
export type MetricCategory =
  | "volume"
  | "sentiment"
  | "pricing"
  | "velocity"
  | "early_access"
  | "platform";
export type BuilderChartType = "bar" | "line" | "stacked_area" | "composed";

export interface MetricDefinition {
  id: string;
  label: string;
  description: string;
  category: MetricCategory;
  unit: MetricUnit;
  source: string;
  column: string;
  default_chart_hint: BuilderChartType;
}

export interface TrendQueryMetricMeta {
  id: string;
  label: string;
  unit: MetricUnit;
  category: MetricCategory;
  default_chart_hint: BuilderChartType;
}

export interface TrendQueryPeriod {
  period: string;
  [metricId: string]: number | string | null;
}

export interface TrendQueryResult {
  granularity: Granularity;
  periods: TrendQueryPeriod[];
  metrics: TrendQueryMetricMeta[];
}

// --- Reports / Catalog page types ---

export interface CatalogReportEntry {
  appid: number;
  name: string;
  slug: string | null;
  developer: string | null;
  developer_slug: string | null;
  header_image: string | null;
  release_date: string | null;
  price_usd: number | null;
  is_free: boolean;
  review_count: number | null;
  positive_pct: number | null;
  review_score_desc: string | null;
  hidden_gem_score: number | null;
  estimated_revenue_usd: number | null;
  last_analyzed: string;
  reviews_analyzed: number | null;
  top_tags: string[];
  tag_slugs: string[];
  genres: string[];
  genre_slugs: string[];
}

export interface AnalysisCandidateEntry {
  appid: number;
  game_name: string;
  slug: string | null;
  developer: string | null;
  header_image: string | null;
  review_count: number | null;
  positive_pct: number | null;
  review_score_desc: string | null;
  release_date: string | null;
  estimated_revenue_usd: number | null;
  request_count: number;
}

export interface CatalogReportsResponse {
  items: CatalogReportEntry[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
  sort: string;
  filters: { genre: string | null; tag: string | null };
}

export interface ComingSoonResponse {
  items: AnalysisCandidateEntry[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
  sort: string;
}

export interface AnalysisRequestResult {
  status: "requested" | "already_requested";
  request_count: number;
}
