import type { GameReport, PreviewResponse, JobStatus, Game, Genre, Tag } from "./types";

// Server components use API_URL (absolute, set in .env.local for dev, CDN URL for prod).
// Browser calls use "" (same-origin — Next.js rewrites proxy /api/* to FastAPI in dev,
// CloudFront handles it in staging/prod).
const API_BASE =
  typeof window === "undefined"
    ? (process.env.API_URL ?? "")
    : (process.env.NEXT_PUBLIC_API_URL ?? "");

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
  const res = await fetch(`${API_BASE}${path}`, {
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
  threshold?: number;
  game?: {
    short_desc?: string;
    developer?: string;
    release_date?: string;
    price_usd?: number | null;
    is_free?: boolean;
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

export { ApiError };
