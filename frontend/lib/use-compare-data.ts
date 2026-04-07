"use client";

import { useEffect, useState } from "react";
import { getBenchmarks, getGameReport, getGames } from "./api";
import type { CompareGameData, CompareGameMeta, CompareRadarAxes } from "./compare-types";
import type { ContentDepth, GameReport } from "./types";

/** Module-level cache for full Game metadata (name, slug, header_image) —
 * populated by GamePicker when a game is selected so we don't need extra lookups. */
const gameMetaCache = new Map<number, CompareGameMeta>();

export function cacheGameMeta(meta: CompareGameMeta): void {
  gameMetaCache.set(meta.appid, meta);
}

const DEPTH_MAP: Record<string, number> = {
  low: 0.25,
  short: 0.25,
  poor: 0.2,
  medium: 0.6,
  fair: 0.5,
  good: 0.7,
  long: 0.75,
  high: 0.9,
  endless: 1.0,
  excellent: 0.95,
};

const COMMUNITY_MAP: Record<string, number> = {
  thriving: 0.95,
  healthy: 0.9,
  active: 0.75,
  mixed: 0.5,
  shrinking: 0.4,
  declining: 0.25,
  critical: 0.15,
  dead: 0.1,
  toxic: 0.1,
  not_applicable: 0.5,
};

function computeContentDepth(cd: ContentDepth | null | undefined): number {
  if (!cd) return 0.5;
  const vals = [
    DEPTH_MAP[cd.perceived_length] ?? 0.5,
    DEPTH_MAP[cd.replayability] ?? 0.5,
    DEPTH_MAP[cd.value_perception] ?? 0.5,
  ];
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function computeRadarAxes(meta: CompareGameMeta, report: GameReport | null): CompareRadarAxes {
  const sentiment = (meta.positive_pct ?? 0) / 100;
  const reviewCount = Math.max(1, meta.review_count ?? 1);
  const reviewVolume = Math.min(1, Math.log10(reviewCount) / 6);
  const hiddenGem = report?.hidden_gem_score ?? 0;
  const contentDepth = computeContentDepth(report?.content_depth);
  const communityHealth = COMMUNITY_MAP[report?.community_health?.overall ?? "not_applicable"] ?? 0.5;

  const spa = report?.store_page_alignment;
  const delivered = spa?.promises_delivered.length ?? 0;
  const broken = spa?.promises_broken.length ?? 0;
  const promiseAlignment =
    delivered + broken > 0 ? delivered / (delivered + broken) : 0.5;

  return {
    sentiment,
    reviewVolume,
    hiddenGem,
    contentDepth,
    communityHealth,
    promiseAlignment,
  };
}

async function resolveMeta(
  appid: number,
  reportName: string | undefined,
  reportGame: {
    price_usd?: number | null;
    is_free?: boolean;
    release_date?: string;
    positive_pct?: number | null;
    review_score_desc?: string | null;
    review_count?: number | null;
  } | undefined,
  signal: AbortSignal,
): Promise<CompareGameMeta> {
  const cached = gameMetaCache.get(appid);
  if (cached) {
    // Merge fresh steam facts from the report call
    return {
      ...cached,
      positive_pct: reportGame?.positive_pct ?? cached.positive_pct,
      review_score_desc: reportGame?.review_score_desc ?? cached.review_score_desc,
      review_count: reportGame?.review_count ?? cached.review_count,
      price_usd: reportGame?.price_usd ?? cached.price_usd,
      is_free: reportGame?.is_free ?? cached.is_free,
      release_date: reportGame?.release_date ?? cached.release_date,
    };
  }
  // Fallback: search by name
  let name = reportName ?? `App ${appid}`;
  let slug = String(appid);
  let header: string | null = null;
  if (reportName) {
    try {
      const res = await getGames({ q: reportName, limit: 5 }, signal);
      const match = res.games.find((g) => g.appid === appid);
      if (match) {
        name = match.name;
        slug = match.slug;
        header = match.header_image ?? null;
      }
    } catch {
      // swallow
    }
  }
  if (signal.aborted) throw new DOMException("aborted", "AbortError");
  const meta: CompareGameMeta = {
    appid,
    name,
    slug,
    header_image: header,
    positive_pct: reportGame?.positive_pct ?? null,
    review_score_desc: reportGame?.review_score_desc ?? null,
    review_count: reportGame?.review_count ?? null,
    price_usd: reportGame?.price_usd ?? null,
    is_free: reportGame?.is_free ?? null,
    release_date: reportGame?.release_date ?? null,
  };
  gameMetaCache.set(appid, meta);
  return meta;
}

function placeholderData(appid: number): CompareGameData {
  const cached = gameMetaCache.get(appid);
  const meta: CompareGameMeta = cached ?? {
    appid,
    name: `App ${appid}`,
    slug: String(appid),
    header_image: null,
    positive_pct: null,
    review_score_desc: null,
    review_count: null,
    price_usd: null,
    is_free: null,
    release_date: null,
  };
  return {
    appid,
    meta,
    report: null,
    benchmarks: null,
    radarAxes: computeRadarAxes(meta, null),
  };
}

async function loadOne(appid: number, signal: AbortSignal): Promise<CompareGameData> {
  try {
    const [reportRes, benchmarks] = await Promise.all([
      getGameReport(appid, signal),
      getBenchmarks(appid, signal).catch(() => null),
    ]);
    const report = reportRes.report ?? null;
    const meta = await resolveMeta(appid, report?.game_name, reportRes.game, signal);
    return {
      appid,
      meta,
      report,
      benchmarks,
      radarAxes: computeRadarAxes(meta, report),
    };
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    console.warn(`compare: failed to load appid ${appid}`, err);
    // Return a placeholder so data[i] still maps to appids[i] — the grid
    // will render "—" cells for the missing values and the column remains.
    return placeholderData(appid);
  }
}

export function useCompareData(appids: number[]): {
  data: CompareGameData[];
  loading: boolean;
  error: string | null;
} {
  const [data, setData] = useState<CompareGameData[]>([]);
  const [loading, setLoading] = useState<boolean>(appids.length > 0);
  const [error, setError] = useState<string | null>(null);

  // Stable key so the effect re-runs only when the appid list actually changes.
  const key = appids.join(",");

  useEffect(() => {
    if (appids.length === 0) {
      setData([]);
      setLoading(false);
      setError(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setData([]);

    (async () => {
      try {
        const results = await Promise.all(
          appids.map((appid) => loadOne(appid, controller.signal)),
        );
        if (controller.signal.aborted) return;
        // Order preserved: results[i] corresponds to appids[i]. Failed loads
        // are placeholder stubs rather than being dropped, so columns stay stable.
        const anyLoaded = results.some((r) => r.report !== null || r.meta.positive_pct != null);
        if (!anyLoaded) {
          setError("Could not load any of the selected games.");
          setData([]);
        } else {
          setData(results);
        }
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setError((err as Error).message ?? "Failed to load compare data");
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();

    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { data, loading, error };
}
