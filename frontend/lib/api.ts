import type {
  GameReport, PreviewResponse, JobStatus, Game, Genre, Tag, TagGroup, ReviewStats, Benchmarks, DeckTestResult,
  Granularity, ReleaseVolumePeriod, SentimentDistPeriod, GenreSharePeriod, VelocityDistPeriod,
  PriceTrendPeriod, EATrendPeriod, PlatformTrendPeriod, EngagementDepthPeriod, CategoryTrendPeriod,
  AudienceOverlap, PlaytimeSentiment, EarlyAccessImpact, ReviewVelocity, TopReviewsResponse,
  PricePositioning, ReleaseTiming, PlatformGaps, TagTrend, DeveloperPortfolio, PublisherPortfolio,
  MetricDefinition, TrendQueryResult,
} from "./types";

// Server components use API_URL (absolute, set in .env.local for dev, CDN URL for prod).
// Browser calls use "" (same-origin — Next.js rewrites proxy /api/* to FastAPI in dev,
// CloudFront handles it in staging/prod).
function getApiBase(): string {
  const base =
    typeof window === "undefined"
      ? process.env.API_URL!
      : (process.env.NEXT_PUBLIC_API_URL ?? "");
  return base.replace(/\/$/, "");
}

class ApiError extends Error {
  constructor(
    public status: number,
    public body: Record<string, unknown>,
  ) {
    super(body.error as string ?? `HTTP ${status}`);
  }
}

async function apiFetch<T>(
  path: string,
  init?: RequestInit & { next?: { revalidate?: number; tags?: string[] } },
): Promise<T> {
  // Server-side: allow 25s for Lambda cold starts chained across SSR + API.
  // Browser-side: keep 8s to avoid hanging UI.
  const timeout = typeof window === "undefined" ? 25000 : 8000;
  // Merge an optional caller-supplied signal with the built-in timeout so
  // callers (e.g., useCompareData) can actually cancel in-flight requests.
  const timeoutSignal = AbortSignal.timeout(timeout);
  const callerSignal = init?.signal;
  const signal =
    callerSignal && "any" in AbortSignal
      ? AbortSignal.any([timeoutSignal, callerSignal])
      : (callerSignal ?? timeoutSignal);
  const { signal: _s, ...rest } = init ?? {};
  void _s;
  const res = await fetch(`${getApiBase()}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...rest,
    signal,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body);
  }
  return res.json();
}

/** POST /api/preview — free fields, unconditional */
export async function getPreview(appid: number): Promise<PreviewResponse> {
  return apiFetch<PreviewResponse>("/api/preview", {
    method: "POST",
    body: JSON.stringify({ appid }),
    next: { revalidate: 3600, tags: [`preview-${appid}`] },
  });
}

/** GET /api/games/{appid}/report — full report JSON */
export async function getGameReport(appid: number, signal?: AbortSignal): Promise<{
  status: string;
  report?: GameReport;
  review_count?: number;
  game?: {
    short_desc?: string;
    developer?: string;
    developer_slug?: string;
    publisher?: string;
    publisher_slug?: string;
    release_date?: string;
    price_usd?: number | null;
    is_free?: boolean;
    is_early_access?: boolean;
    genres?: string[];
    tags?: string[];
    deck_compatibility?: number | null;
    deck_test_results?: DeckTestResult[];
    // Steam-sourced sentiment + freshness (data-source-clarity refactor)
    positive_pct?: number | null;
    review_score_desc?: string | null;
    review_count?: number | null;
    meta_crawled_at?: string | null;
    review_crawled_at?: string | null;
    reviews_completed_at?: string | null;
    tags_crawled_at?: string | null;
    last_analyzed?: string | null;
    // Boxleiter v1 revenue estimate — present only when the backend has values.
    estimated_owners?: number | null;
    estimated_revenue_usd?: number | null;
    revenue_estimate_method?: string | null;
    revenue_estimate_reason?: string | null;
  };
}> {
  return apiFetch(`/api/games/${appid}/report`, {
    signal,
    next: { revalidate: 3600, tags: [`report-${appid}`] },
  });
}

/** GET /api/status/{jobId} — polls Step Functions execution */
export async function pollStatus(jobId: string): Promise<JobStatus> {
  return apiFetch<JobStatus>(`/api/status/${jobId}`);
}

/** Poll until SUCCEEDED or FAILED, with timeout */
export async function waitForReport(
  jobId: string,
  timeoutMs = 120_000,
): Promise<GameReport> {
  const deadline = Date.now() + timeoutMs;
  const delay = (ms: number) =>
    new Promise<void>((r) => setTimeout(r, ms));
  let interval = 2000;

  while (Date.now() < deadline) {
    const status = await pollStatus(jobId);
    if (status.status === "SUCCEEDED" && status.report) return status.report;
    if (status.status === "FAILED" || status.status === "TIMED_OUT") {
      throw new Error(`Analysis ${status.status.toLowerCase()}`);
    }
    await delay(interval);
    interval = Math.min(interval * 1.5, 8000);
  }
  throw new Error("Analysis timed out");
}

/** Response shape from GET /api/games */
export interface GamesResponse {
  total: number;
  games: Game[];
}

/** GET /api/games — listing with optional filters */
export async function getGames(
  params?: {
  q?: string;
  genre?: string;
  tag?: string;
  developer?: string;
  publisher?: string;
  year_from?: number;
  year_to?: number;
  min_reviews?: number;
  has_analysis?: boolean;
  sentiment?: string;
  price_tier?: string;
  deck?: string;
  sort?: string;
  limit?: number;
  offset?: number;
},
  signal?: AbortSignal,
): Promise<GamesResponse> {
  const qs = new URLSearchParams();
  if (params?.q) qs.set("q", params.q);
  if (params?.genre) qs.set("genre", params.genre);
  if (params?.tag) qs.set("tag", params.tag);
  if (params?.developer) qs.set("developer", params.developer);
  if (params?.publisher) qs.set("publisher", params.publisher);
  if (params?.year_from) qs.set("year_from", String(params.year_from));
  if (params?.year_to) qs.set("year_to", String(params.year_to));
  if (params?.min_reviews) qs.set("min_reviews", String(params.min_reviews));
  if (params?.has_analysis !== undefined) qs.set("has_analysis", String(params.has_analysis));
  if (params?.sentiment) qs.set("sentiment", params.sentiment);
  if (params?.price_tier) qs.set("price_tier", params.price_tier);
  if (params?.deck) qs.set("deck", params.deck);
  if (params?.sort) qs.set("sort", params.sort);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<GamesResponse>(`/api/games${query}`, {
    signal,
    next: { revalidate: 3600 },
  });
}

/** GET /api/genres */
export async function getGenres(): Promise<Genre[]> {
  return apiFetch<Genre[]>("/api/genres", { next: { revalidate: 86400 } });
}

/** GET /api/tags/top */
export async function getTopTags(limit = 24): Promise<Tag[]> {
  return apiFetch<Tag[]>(`/api/tags/top?limit=${limit}`, {
    next: { revalidate: 86400 },
  });
}

/** GET /api/tags/grouped */
export async function getTagsGrouped(
  limitPerCategory = 20,
): Promise<TagGroup[]> {
  return apiFetch<TagGroup[]>(
    `/api/tags/grouped?limit_per_category=${limitPerCategory}`,
    {
      next: { revalidate: 86400 },
    },
  );
}

/** GET /api/games/{appid}/review-stats */
export async function getReviewStats(appid: number): Promise<ReviewStats> {
  return apiFetch<ReviewStats>(`/api/games/${appid}/review-stats`);
}

/** GET /api/games/{appid}/benchmarks */
export async function getBenchmarks(appid: number, signal?: AbortSignal): Promise<Benchmarks> {
  return apiFetch<Benchmarks>(`/api/games/${appid}/benchmarks`, { signal });
}

// ---------------------------------------------------------------------------
// Per-entity analytics (game report, genre, tag, developer pages)
// ---------------------------------------------------------------------------

export async function getAudienceOverlap(appid: number, limit = 20): Promise<AudienceOverlap> {
  const clampedLimit = Math.max(1, Math.min(50, limit));
  return apiFetch<AudienceOverlap>(`/api/games/${appid}/audience-overlap?limit=${clampedLimit}`);
}

export async function getPlaytimeSentiment(appid: number): Promise<PlaytimeSentiment> {
  return apiFetch<PlaytimeSentiment>(`/api/games/${appid}/playtime-sentiment`);
}

export async function getEarlyAccessImpact(appid: number): Promise<EarlyAccessImpact> {
  return apiFetch<EarlyAccessImpact>(`/api/games/${appid}/early-access-impact`);
}

export async function getReviewVelocity(appid: number): Promise<ReviewVelocity> {
  return apiFetch<ReviewVelocity>(`/api/games/${appid}/review-velocity`);
}

export async function getTopReviews(
  appid: number, sort: "helpful" | "funny" = "helpful", limit = 10
): Promise<TopReviewsResponse> {
  const clampedLimit = Math.max(1, Math.min(50, limit));
  return apiFetch<TopReviewsResponse>(
    `/api/games/${appid}/top-reviews?sort=${sort}&limit=${clampedLimit}`
  );
}

export async function getPricePositioning(genre: string): Promise<PricePositioning> {
  return apiFetch<PricePositioning>(`/api/analytics/price-positioning?genre=${encodeURIComponent(genre)}`);
}

export async function getReleaseTiming(genre: string): Promise<ReleaseTiming> {
  return apiFetch<ReleaseTiming>(`/api/analytics/release-timing?genre=${encodeURIComponent(genre)}`);
}

export async function getPlatformGaps(genre: string): Promise<PlatformGaps> {
  return apiFetch<PlatformGaps>(`/api/analytics/platform-gaps?genre=${encodeURIComponent(genre)}`);
}

export async function getTagTrend(slug: string): Promise<TagTrend> {
  return apiFetch<TagTrend>(`/api/tags/${slug}/trend`);
}

export async function getDeveloperAnalytics(slug: string): Promise<DeveloperPortfolio> {
  return apiFetch<DeveloperPortfolio>(`/api/developers/${slug}/analytics`);
}

export async function getPublisherAnalytics(slug: string): Promise<PublisherPortfolio> {
  return apiFetch<PublisherPortfolio>(`/api/publishers/${slug}/analytics`);
}

// ---------------------------------------------------------------------------
// Analytics Dashboard — trend API functions
// ---------------------------------------------------------------------------

function trendParams(params: Record<string, string | number | undefined>): string {
  const qs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join("&");
  return qs ? `?${qs}` : "";
}

export async function getAnalyticsTrendReleaseVolume(params: {
  granularity?: Granularity; genre?: string; tag?: string; type?: string; limit?: number;
}): Promise<{ granularity: string; filter: Record<string, string>; periods: ReleaseVolumePeriod[]; summary: { total_releases: number; avg_per_period: number; trend: string } }> {
  return apiFetch(`/api/analytics/trends/release-volume${trendParams(params)}`);
}

export async function getAnalyticsTrendSentiment(params: {
  granularity?: Granularity; genre?: string; type?: string; limit?: number;
}): Promise<{ granularity: string; periods: SentimentDistPeriod[] }> {
  return apiFetch(`/api/analytics/trends/sentiment${trendParams(params)}`);
}

export async function getAnalyticsTrendGenreShare(params: {
  granularity?: Granularity; top_n?: number; type?: string; limit?: number;
}): Promise<{ granularity: string; genres: string[]; periods: GenreSharePeriod[] }> {
  return apiFetch(`/api/analytics/trends/genre-share${trendParams(params)}`);
}

export async function getAnalyticsTrendVelocity(params: {
  granularity?: Granularity; genre?: string; type?: string; limit?: number;
}): Promise<{ granularity: string; periods: VelocityDistPeriod[] }> {
  return apiFetch(`/api/analytics/trends/velocity${trendParams(params)}`);
}

export async function getAnalyticsTrendPricing(params: {
  granularity?: Granularity; genre?: string; type?: string; limit?: number;
}): Promise<{ granularity: string; periods: PriceTrendPeriod[] }> {
  return apiFetch(`/api/analytics/trends/pricing${trendParams(params)}`);
}

export async function getAnalyticsTrendEarlyAccess(params: {
  granularity?: Granularity; type?: string; limit?: number;
}): Promise<{ granularity: string; periods: EATrendPeriod[] }> {
  return apiFetch(`/api/analytics/trends/early-access${trendParams(params)}`);
}

export async function getAnalyticsTrendPlatforms(params: {
  granularity?: Granularity; genre?: string; type?: string; limit?: number;
}): Promise<{ granularity: string; periods: PlatformTrendPeriod[] }> {
  return apiFetch(`/api/analytics/trends/platforms${trendParams(params)}`);
}

export async function getAnalyticsTrendEngagement(params: {
  granularity?: Granularity; genre?: string; limit?: number;
}): Promise<{ granularity: string; data_available: boolean; periods: EngagementDepthPeriod[] }> {
  return apiFetch(`/api/analytics/trends/engagement${trendParams(params)}`);
}

export async function getAnalyticsTrendCategories(params: {
  granularity?: Granularity; top_n?: number; type?: string; limit?: number;
}): Promise<{ granularity: string; categories: string[]; periods: CategoryTrendPeriod[] }> {
  return apiFetch(`/api/analytics/trends/categories${trendParams(params)}`);
}

// ---------------------------------------------------------------------------
// Builder lens — metric catalog + generic trend query
// ---------------------------------------------------------------------------

export async function getAnalyticsMetricsCatalog(
  signal?: AbortSignal,
): Promise<{ metrics: MetricDefinition[] }> {
  return apiFetch("/api/analytics/metrics", { signal });
}

export async function getAnalyticsTrendQuery(
  params: {
    metrics: string[];
    granularity?: Granularity;
    genre?: string;
    tag?: string;
    limit?: number;
  },
  signal?: AbortSignal,
): Promise<TrendQueryResult> {
  const qs = new URLSearchParams();
  qs.set("metrics", params.metrics.join(","));
  if (params.granularity) qs.set("granularity", params.granularity);
  if (params.genre) qs.set("genre", params.genre);
  if (params.tag) qs.set("tag", params.tag);
  if (params.limit) qs.set("limit", String(params.limit));
  return apiFetch(`/api/analytics/trend-query?${qs.toString()}`, { signal });
}

// ---------------------------------------------------------------------------
// New Releases — three-lens feed (Released / Coming Soon / Just Added)
// ---------------------------------------------------------------------------

export type NewReleasesWindow = "today" | "week" | "month" | "quarter";

export interface NewReleaseEntry {
  appid: number;
  name: string;
  slug: string | null;
  type: string | null;
  developer: string | null;
  developer_slug: string | null;
  publisher: string | null;
  publisher_slug: string | null;
  header_image: string | null;
  release_date: string | null;
  coming_soon: boolean;
  price_usd: number | null;
  is_free: boolean;
  review_count: number | null;
  review_count_english: number | null;
  positive_pct: number | null;
  review_score_desc: string | null;
  discovered_at: string;
  meta_crawled_at: string | null;
  metadata_pending: boolean;
  days_since_release: number | null;
  has_analysis: boolean;
  top_tags: string[];
  top_tag_slugs: string[];
  genres: string[];
  genre_slugs: string[];
}

export interface NewReleasesFilters {
  genre: string | null;
  tag: string | null;
}

export interface NewReleasesWindowResponse {
  items: NewReleaseEntry[];
  total: number;
  window: NewReleasesWindow;
  page: number;
  page_size: number;
  filters: NewReleasesFilters;
  counts: { today: number; week: number; month: number; quarter: number };
}

export interface NewReleasesUpcomingResponse {
  items: NewReleaseEntry[];
  total: number;
  page: number;
  page_size: number;
  filters: NewReleasesFilters;
  buckets: { this_week: number; this_month: number; this_quarter: number; tba: number };
}

interface NewReleasesFetchOpts {
  page?: number;
  pageSize?: number;
  genre?: string | null;
  tag?: string | null;
}

function buildNrQs(params: Record<string, string | number | null | undefined>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v != null && v !== "") qs.set(k, String(v));
  }
  return qs.toString();
}

export async function getNewReleasesReleased(
  window: NewReleasesWindow = "week",
  opts: NewReleasesFetchOpts = {},
): Promise<NewReleasesWindowResponse> {
  const qs = buildNrQs({
    window,
    page: opts.page ?? 1,
    page_size: opts.pageSize ?? 24,
    genre: opts.genre,
    tag: opts.tag,
  });
  return apiFetch(`/api/new-releases/released?${qs}`, { next: { revalidate: 300 } });
}

export async function getNewReleasesUpcoming(
  opts: NewReleasesFetchOpts = {},
): Promise<NewReleasesUpcomingResponse> {
  const qs = buildNrQs({
    page: opts.page ?? 1,
    page_size: opts.pageSize ?? 24,
    genre: opts.genre,
    tag: opts.tag,
  });
  return apiFetch(`/api/new-releases/upcoming?${qs}`, { next: { revalidate: 300 } });
}

export async function getNewReleasesAdded(
  window: NewReleasesWindow = "week",
  opts: NewReleasesFetchOpts = {},
): Promise<NewReleasesWindowResponse> {
  const qs = buildNrQs({
    window,
    page: opts.page ?? 1,
    page_size: opts.pageSize ?? 24,
    genre: opts.genre,
    tag: opts.tag,
  });
  return apiFetch(`/api/new-releases/added?${qs}`, { next: { revalidate: 300 } });
}

export { ApiError };
