import type { ReactNode } from "react";
import type { Benchmarks, GameReport } from "./types";

/** Minimal Game metadata returned embedded in getGameReport.
 * Mirrors the `game` field shape from api.ts `getGameReport()`. */
export interface CompareGameMeta {
  appid: number;
  name: string;
  slug: string;
  header_image?: string | null;
  positive_pct?: number | null;
  review_score_desc?: string | null;
  review_count?: number | null;
  price_usd?: number | null;
  is_free?: boolean | null;
  release_date?: string | null;
}

/** Everything the Compare lens needs for one game. Assembled from parallel API calls. */
export interface CompareGameData {
  appid: number;
  meta: CompareGameMeta;
  report: GameReport | null;
  benchmarks: Benchmarks | null;
  radarAxes: CompareRadarAxes;
}

export interface CompareRadarAxes {
  sentiment: number;
  reviewVolume: number;
  hiddenGem: number;
  contentDepth: number;
  communityHealth: number;
  promiseAlignment: number;
}

export type MetricGroup = "steam" | "intelligence" | "risk" | "audience";
export type MetricDirection = "higher" | "lower" | "neutral";

export interface MetricRow {
  id: string;
  label: string;
  group: MetricGroup;
  direction: MetricDirection;
  free: boolean;
  /** Render the cell for one game. */
  render: (data: CompareGameData) => ReactNode;
  /** Sortable numeric value for leader detection. null to skip. */
  numeric: (data: CompareGameData) => number | null;
  /** Optional info tooltip (title attribute). */
  info?: string;
}
