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

/** POST /api/preview — free fields, rate-limited 1/IP */
export async function getPreview(appid: number): Promise<PreviewResponse> {
  return apiFetch<PreviewResponse>("/api/preview", {
    method: "POST",
    body: JSON.stringify({ appid }),
    next: { revalidate: 3600, tags: [`preview-${appid}`] },
  });
}

/** POST /api/validate-key — returns full report on valid Lemon Squeezy key */
export async function validateKey(
  licenseKey: string,
  appid: number,
): Promise<GameReport> {
  return apiFetch<GameReport>("/api/validate-key", {
    method: "POST",
    body: JSON.stringify({ license_key: licenseKey, appid }),
  });
}

/** GET /api/status/{jobId} — polls Step Functions execution */
export async function pollStatus(jobId: string): Promise<JobStatus> {
  return apiFetch<JobStatus>(`/api/status/${jobId}`);
}

// TODO: waitForReport is not yet called anywhere in the UI.
// Before wiring it up, fix the status string mismatch:
// - Backend returns "running" / "complete" / "failed"
// - This function checks for "SUCCEEDED" / "FAILED" / "TIMED_OUT" (never matches)
// Fix: change the checks below to match backend strings, or update the backend to match.
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

/** GET /api/games — listing with optional filters (used by home/genre/tag pages) */
export async function getGames(params?: {
  genre?: string;
  tag?: string;
  developer?: string;
  sort?: "review_count" | "hidden_gem_score" | "positive_pct";
  limit?: number;
  offset?: number;
}): Promise<Game[]> {
  const qs = new URLSearchParams();
  if (params?.genre) qs.set("genre", params.genre);
  if (params?.tag) qs.set("tag", params.tag);
  if (params?.developer) qs.set("developer", params.developer);
  if (params?.sort) qs.set("sort", params.sort);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<Game[]>(`/api/games${query}`, {
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
