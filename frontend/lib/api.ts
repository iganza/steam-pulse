import type {
  GameReport, PreviewResponse, JobStatus, Game, Genre, Tag, ReviewStats, Benchmarks, DeckTestResult,
  Granularity, ReleaseVolumePeriod, SentimentDistPeriod, GenreSharePeriod, VelocityDistPeriod,
  PriceTrendPeriod, EATrendPeriod, PlatformTrendPeriod, EngagementDepthPeriod, CategoryTrendPeriod,
  AudienceOverlap, PlaytimeSentiment, EarlyAccessImpact, ReviewVelocity, TopReviewsResponse,
  PricePositioning, ReleaseTiming, PlatformGaps, TagTrend, DeveloperPortfolio,
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
  const res = await fetch(`${getApiBase()}${path}`, {
    headers: { "Content-Type": "application/json" },
    signal: AbortSignal.timeout(8000),
    ...init,
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
export async function getGameReport(appid: number): Promise<{
  status: string;
  report?: GameReport;
  review_count?: number;
  game?: {
    short_desc?: string;
    developer?: string;
    release_date?: string;
    price_usd?: number | null;
    is_free?: boolean;
    genres?: string[];
    tags?: string[];
    deck_compatibility?: number | null;
    deck_test_results?: DeckTestResult[];
  };
}> {
  return apiFetch(`/api/games/${appid}/report`, {
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
export async function getGames(params?: {
  q?: string;
  genre?: string;
  tag?: string;
  developer?: string;
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
}): Promise<GamesResponse> {
  const qs = new URLSearchParams();
  if (params?.q) qs.set("q", params.q);
  if (params?.genre) qs.set("genre", params.genre);
  if (params?.tag) qs.set("tag", params.tag);
  if (params?.developer) qs.set("developer", params.developer);
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

/** GET /api/games/{appid}/review-stats */
export async function getReviewStats(appid: number): Promise<ReviewStats> {
  return apiFetch<ReviewStats>(`/api/games/${appid}/review-stats`);
}

/** GET /api/games/{appid}/benchmarks */
export async function getBenchmarks(appid: number): Promise<Benchmarks> {
  return apiFetch<Benchmarks>(`/api/games/${appid}/benchmarks`);
}

// ---------------------------------------------------------------------------
// Per-entity analytics (game report, genre, tag, developer pages)
// ---------------------------------------------------------------------------

export async function getAudienceOverlap(appid: number, limit = 20): Promise<AudienceOverlap> {
  return apiFetch<AudienceOverlap>(`/api/games/${appid}/audience-overlap?limit=${limit}`);
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
  return apiFetch<TopReviewsResponse>(
    `/api/games/${appid}/top-reviews?sort=${sort}&limit=${limit}`
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

export { ApiError };
