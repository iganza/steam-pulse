"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { GranularityToggle } from "@/components/trends/GranularityToggle";
import { TrendBarChart } from "@/components/trends/TrendBarChart";
import { TrendStackedArea } from "@/components/trends/TrendStackedArea";
import { TrendStackedBarChart } from "@/components/trends/TrendStackedBarChart";
import { TrendComposed } from "@/components/trends/TrendComposed";
import {
  getAnalyticsTrendReleaseVolume,
  getAnalyticsTrendSentiment,
  getAnalyticsTrendGenreShare,
  getAnalyticsTrendVelocity,
  getAnalyticsTrendPricing,
  getAnalyticsTrendEarlyAccess,
  getAnalyticsTrendPlatforms,
  getAnalyticsTrendEngagement,
  getAnalyticsTrendCategories,
} from "@/lib/api";
import type {
  Granularity,
  ReleaseVolumePeriod,
  SentimentDistPeriod,
  GenreSharePeriod,
  VelocityDistPeriod,
  PriceTrendPeriod,
  EATrendPeriod,
  PlatformTrendPeriod,
  EngagementDepthPeriod,
  CategoryTrendPeriod,
} from "@/lib/types";
import type { LensProps, ToolkitFilters } from "@/lib/toolkit-state";

interface TrendData {
  releaseVolume: { periods: ReleaseVolumePeriod[]; summary?: { total_releases: number; avg_per_period: number; trend: string } } | null;
  sentiment: { periods: SentimentDistPeriod[] } | null;
  genreShare: { genres: string[]; periods: GenreSharePeriod[] } | null;
  velocity: { periods: VelocityDistPeriod[] } | null;
  pricing: { periods: PriceTrendPeriod[] } | null;
  earlyAccess: { periods: EATrendPeriod[] } | null;
  platforms: { periods: PlatformTrendPeriod[] } | null;
  engagement: { data_available: boolean; periods: EngagementDepthPeriod[] } | null;
  categories: { categories: string[]; periods: CategoryTrendPeriod[] } | null;
}

const INITIAL: TrendData = {
  releaseVolume: null, sentiment: null, genreShare: null, velocity: null,
  pricing: null, earlyAccess: null, platforms: null, engagement: null, categories: null,
};

const GENRE_COLORS = ["#14b8a6", "#6366f1", "#f59e0b", "#ef4444", "#8b5cf6", "#6b7280"];

// Genre Share only makes sense at quarter/year granularity — week/month produces
// too many near-empty slices. Map finer granularities to quarter for Pro.
function coarseGenreGranularity(g: Granularity): Granularity {
  return g === "week" || g === "month" ? "quarter" : g;
}

// Compute a trailing N-period moving average for a numeric field and attach it
// as a new key on each row.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function withMovingAverage(rows: any[], srcKey: string, dstKey: string, window = 3): any[] {
  return rows.map((row, i) => {
    const slice = rows.slice(Math.max(0, i - window + 1), i + 1);
    const avg = slice.reduce((sum: number, r: Record<string, unknown>) => sum + (Number(r[srcKey]) || 0), 0) / slice.length;
    return { ...row, [dstKey]: Math.round(avg) };
  });
}

const GENRE_SHARE_TOP_N_OPTIONS = [5, 10, 15];
const GAME_TYPE_OPTIONS: { value: "game" | "dlc" | "all"; label: string }[] = [
  { value: "game", label: "Games" },
  { value: "dlc", label: "DLC" },
  { value: "all", label: "All" },
];

// Filters Trends actually consumes today (passed through to backend).
const TRENDS_HONORED_FILTERS = new Set<keyof ToolkitFilters>(["genre", "tag"]);

// Default value for `sort` in toolkit-state — must match toolkitParsers.sort.withDefault().
// Without this, the default sort would always be reported as an "ignored" filter.
const DEFAULT_SORT = "review_count";

// Charts whose backend endpoints do NOT accept genre/tag — they remain
// catalog-wide regardless of the segment filter.
const UNFILTERED_CHARTS = ["Genre Share", "Early Access Trends", "Feature Adoption"];

// Human labels for filter keys we may report as ignored.
const FILTER_LABELS: Partial<Record<keyof ToolkitFilters, string>> = {
  q: "search",
  developer: "developer",
  sentiment: "sentiment",
  price_tier: "price tier",
  min_reviews: "min reviews",
  year_from: "year from",
  year_to: "year to",
  deck: "deck",
  has_analysis: "has analysis",
  sort: "sort",
};

function isFilterSet(filters: ToolkitFilters, key: keyof ToolkitFilters): boolean {
  const v = filters[key];
  if (v === null || v === undefined) return false;
  // `sort` has a non-empty default — only count it as set when it diverges.
  if (key === "sort") return typeof v === "string" && v.length > 0 && v !== DEFAULT_SORT;
  if (typeof v === "string") return v.length > 0;
  if (Array.isArray(v)) return v.length > 0;
  return true;
}

function summarizeSegment(filters: ToolkitFilters): string {
  const parts: string[] = [];
  if (filters.genre) parts.push(`genre=${filters.genre}`);
  if (filters.tag) parts.push(`tag=${filters.tag}`);
  return parts.length ? parts.join(" · ") : "entire catalog";
}

function ignoredFilterNames(filters: ToolkitFilters): string[] {
  const names: string[] = [];
  for (const key of Object.keys(FILTER_LABELS) as (keyof ToolkitFilters)[]) {
    if (TRENDS_HONORED_FILTERS.has(key)) continue;
    if (isFilterSet(filters, key)) {
      names.push(FILTER_LABELS[key] as string);
    }
  }
  return names;
}

export function TrendsLens({ filters, isPro }: LensProps) {
  // Lens-local display state — intentionally NOT in URL.
  const [granularity, setGranularity] = useState<Granularity>("month");
  const [sentimentNormalized, setSentimentNormalized] = useState<boolean>(true);
  const [genreShareTopN, setGenreShareTopN] = useState<number>(5);
  const [gameType, setGameType] = useState<"game" | "dlc" | "all">("game");

  const [data, setData] = useState<TrendData>(INITIAL);
  const [loading, setLoading] = useState(true);

  // Segment filters come from the global toolkit filter bar.
  const genreSlug = filters.genre || undefined;
  const tagSlug = filters.tag || undefined;
  const appidsScoped = (filters.appids?.length ?? 0) > 0;
  const ignored = ignoredFilterNames(filters);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    const g = isPro ? granularity : "month";
    const rvType = isPro ? gameType : "game";
    const topN = isPro ? genreShareTopN : 5;

    const results = await Promise.allSettled([
      getAnalyticsTrendReleaseVolume({ granularity: g, genre: genreSlug, tag: tagSlug, type: rvType }),
      getAnalyticsTrendSentiment({ granularity: g, genre: genreSlug }),
      getAnalyticsTrendGenreShare({ granularity: isPro ? coarseGenreGranularity(granularity) : "year", top_n: topN }),
      getAnalyticsTrendVelocity({ granularity: g, genre: genreSlug }),
      getAnalyticsTrendPricing({ granularity: isPro ? granularity : "quarter", genre: genreSlug }),
      getAnalyticsTrendEarlyAccess({ granularity: isPro ? granularity : "quarter" }),
      getAnalyticsTrendPlatforms({ granularity: isPro ? granularity : "quarter", genre: genreSlug }),
      getAnalyticsTrendEngagement({ granularity: isPro ? granularity : "year", genre: genreSlug }),
      getAnalyticsTrendCategories({ granularity: isPro ? granularity : "year", top_n: isPro ? 8 : 4 }),
    ]);

    const val = <T,>(r: PromiseSettledResult<T>): T | null =>
      r.status === "fulfilled" ? r.value : null;

    setData({
      releaseVolume: val(results[0]),
      sentiment: val(results[1]),
      genreShare: val(results[2]),
      velocity: val(results[3]),
      pricing: val(results[4]),
      earlyAccess: val(results[5]),
      platforms: val(results[6]),
      engagement: val(results[7]),
      categories: val(results[8]),
    });
    setLoading(false);
  }, [isPro, granularity, genreSlug, tagSlug, gameType, genreShareTopN]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const g = isPro ? granularity : "month";

  return (
    <div className="space-y-6">
      {/* Filter awareness caption */}
      <div className="space-y-1" data-testid="trends-segment-caption">
        <p className="text-xs font-mono text-muted-foreground">
          Trends for: {summarizeSegment(filters)}
          {(filters.genre || filters.tag) && (
            <span className="ml-2 text-foreground/40">
              (filters applied where supported — {UNFILTERED_CHARTS.join(", ")} remain catalog-wide)
            </span>
          )}
          {ignored.length > 0 && (
            <span className="ml-2 text-foreground/40">
              ({ignored.join(", ")} not yet supported in Trends — try Explorer)
            </span>
          )}
          {appidsScoped && (
            <span className="ml-2 text-foreground/40">
              Trends are catalog-wide — game selection ignored. Use Sentiment Drill for a single-game timeline.
            </span>
          )}
        </p>
      </div>

      {/* Lens-local display controls — granularity + per-chart display toggles.
          All consolidated into a single Pro-gated strip; cards are pure displays. */}
      <div className="relative">
        <div className={isPro ? "" : "blur-sm pointer-events-none select-none"}>
          <div className="flex items-center gap-x-6 gap-y-2 flex-wrap text-xs font-mono">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Granularity:</span>
              <GranularityToggle value={granularity} onChange={setGranularity} disabled={!isPro} />
            </div>

            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Release Volume:</span>
              <select
                value={gameType}
                onChange={(e) => setGameType(e.target.value as "game" | "dlc" | "all")}
                disabled={!isPro}
                className="px-2 py-1 rounded bg-card border border-border text-foreground"
              >
                {GAME_TYPE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Sentiment:</span>
              <button
                onClick={() => setSentimentNormalized(true)}
                disabled={!isPro}
                className={`px-2 py-0.5 rounded transition-colors ${sentimentNormalized ? "bg-teal-500/20 text-teal-400" : "text-muted-foreground hover:text-foreground"}`}
              >
                % Share
              </button>
              <button
                onClick={() => setSentimentNormalized(false)}
                disabled={!isPro}
                className={`px-2 py-0.5 rounded transition-colors ${!sentimentNormalized ? "bg-teal-500/20 text-teal-400" : "text-muted-foreground hover:text-foreground"}`}
              >
                Raw
              </button>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Genre Share top:</span>
              <div className="inline-flex rounded-lg border border-border overflow-hidden">
                {GENRE_SHARE_TOP_N_OPTIONS.map((n) => (
                  <button
                    key={n}
                    onClick={() => setGenreShareTopN(n)}
                    disabled={!isPro}
                    className={`px-2 py-0.5 transition-colors ${
                      genreShareTopN === n
                        ? "bg-teal-500/20 text-teal-400"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
        {!isPro && (
          <div className="absolute inset-0 flex items-center justify-center">
            <Link
              href="/pro"
              className="text-sm font-mono tracking-widest px-4 py-2 rounded-lg border border-teal-500/30 bg-background/80 backdrop-blur-sm"
              style={{ color: "var(--teal)" }}
            >
              Customize with Pro &rarr;
            </Link>
          </div>
        )}
      </div>

      {loading && (
        <p className="text-muted-foreground text-sm">Loading analytics...</p>
      )}

      {/* Charts grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* 1. Release Volume */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Release Volume</CardTitle>
            {data.releaseVolume?.summary && (
              <p className="text-xs text-muted-foreground">
                {data.releaseVolume.summary.total_releases.toLocaleString()} total &middot;{" "}
                {data.releaseVolume.summary.avg_per_period}/period &middot;{" "}
                {data.releaseVolume.summary.trend}
              </p>
            )}
          </CardHeader>
          <CardContent>
            <TrendBarChart
              data={withMovingAverage(data.releaseVolume?.periods ?? [], "releases", "releases_ma3")}
              dataKey="releases"
              granularity={g}
              secondaryLine={
                isPro
                  ? { dataKey: "avg_steam_pct", color: "#f59e0b" }
                  : { dataKey: "releases_ma3", color: "#6b7280", sameAxis: true }
              }
            />
          </CardContent>
        </Card>

        {/* 2. Sentiment Distribution */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Sentiment Distribution</CardTitle>
          </CardHeader>
          <CardContent>
            <TrendStackedArea
              data={data.sentiment?.periods ?? []}
              series={[
                { key: "positive_count", label: "Positive", color: "#22c55e" },
                { key: "mixed_count", label: "Mixed", color: "#f59e0b" },
                { key: "negative_count", label: "Negative", color: "#ef4444" },
              ]}
              granularity={g}
              normalized={isPro ? sentimentNormalized : true}
              secondaryLine={isPro ? { dataKey: "avg_metacritic", label: "Metacritic", color: "#6366f1" } : undefined}
            />
          </CardContent>
        </Card>

        {/* 3. Genre Share */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Genre Share</CardTitle>
          </CardHeader>
          <CardContent>
            <TrendStackedArea
              data={(data.genreShare?.periods ?? []).map((p) => {
                const row: Record<string, unknown> = { period: p.period };
                for (const [genre, share] of Object.entries(p.shares)) {
                  row[genre] = Math.round(share * 1000) / 10;
                }
                return row;
              }) as { period: string; [k: string]: unknown }[]}
              series={(data.genreShare?.genres ?? []).map((genre, i) => ({
                key: genre,
                label: genre,
                color: GENRE_COLORS[i % GENRE_COLORS.length],
              }))}
              granularity={isPro ? coarseGenreGranularity(granularity) : "year"}
              normalized={false}
            />
          </CardContent>
        </Card>

        {/* 4. Review Velocity */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Review Velocity</CardTitle>
          </CardHeader>
          <CardContent>
            <TrendStackedBarChart
              data={data.velocity?.periods ?? []}
              series={[
                { key: "velocity_under_1", label: "<1/day", color: "#6b7280" },
                { key: "velocity_1_10", label: "1-10/day", color: "#3b82f6" },
                { key: "velocity_10_50", label: "10-50/day", color: "#14b8a6" },
                { key: "velocity_50_plus", label: "50+/day", color: "#22c55e" },
              ]}
              granularity={g}
            />
          </CardContent>
        </Card>

        {/* 5. Pricing Trends */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Pricing Trends</CardTitle>
          </CardHeader>
          <CardContent>
            <TrendComposed
              data={data.pricing?.periods ?? []}
              bars={[{ dataKey: "free_pct", label: "Free %", color: "#6366f1" }]}
              lines={[{ dataKey: "avg_paid_price", label: "Avg Paid Price", color: "#14b8a6" }]}
              granularity={isPro ? granularity : "quarter"}
            />
          </CardContent>
        </Card>

        {/* 6. Early Access Trends */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Early Access Trends</CardTitle>
          </CardHeader>
          <CardContent>
            <TrendComposed
              data={data.earlyAccess?.periods ?? []}
              bars={isPro
                ? [{ dataKey: "ea_count", label: "EA Games", color: "#8b5cf6" }]
                : [{ dataKey: "ea_pct", label: "EA %", color: "#f59e0b" }]}
              lines={isPro
                ? [
                    { dataKey: "ea_pct", label: "EA %", color: "#f59e0b" },
                    { dataKey: "ea_avg_steam_pct", label: "EA Steam %", color: "#22c55e" },
                    { dataKey: "non_ea_avg_steam_pct", label: "Non-EA Steam %", color: "#ef4444" },
                  ]
                : []}
              granularity={isPro ? granularity : "quarter"}
            />
          </CardContent>
        </Card>

        {/* 7. Platform & Steam Deck */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Platform &amp; Steam Deck</CardTitle>
          </CardHeader>
          <CardContent>
            <TrendComposed
              data={data.platforms?.periods ?? []}
              bars={[]}
              lines={[
                { dataKey: "mac_pct", label: "Mac %", color: "#6b7280" },
                { dataKey: "linux_pct", label: "Linux %", color: "#f59e0b" },
                { dataKey: "deck_verified_pct", label: "Deck Verified %", color: "#22c55e" },
                ...(isPro
                  ? [
                      { dataKey: "deck_playable_pct", label: "Deck Playable %", color: "#14b8a6" },
                      { dataKey: "deck_unsupported_pct", label: "Deck Unsupported %", color: "#ef4444" },
                    ]
                  : []),
              ]}
              granularity={isPro ? granularity : "quarter"}
            />
          </CardContent>
        </Card>

        {/* 8. Engagement Depth */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Engagement Depth</CardTitle>
          </CardHeader>
          <CardContent>
            {data.engagement && !data.engagement.data_available ? (
              <div className="flex items-center justify-center text-muted-foreground text-sm h-[300px]">
                Engagement data is being computed &mdash; check back soon
              </div>
            ) : (
              <TrendStackedArea
                data={data.engagement?.periods ?? []}
                series={[
                  { key: "playtime_under_2h_pct", label: "<2h", color: "#ef4444" },
                  { key: "playtime_2_10h_pct", label: "2-10h", color: "#f59e0b" },
                  { key: "playtime_10_50h_pct", label: "10-50h", color: "#3b82f6" },
                  { key: "playtime_50_200h_pct", label: "50-200h", color: "#14b8a6" },
                  { key: "playtime_200h_plus_pct", label: "200h+", color: "#22c55e" },
                ]}
                granularity={isPro ? granularity : "year"}
                normalized={false}
              />
            )}
          </CardContent>
        </Card>

        {/* 9. Feature Adoption */}
        <Card className="md:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Feature Adoption</CardTitle>
          </CardHeader>
          <CardContent>
            <TrendComposed
              data={(data.categories?.periods ?? []).map((p) => {
                const row: Record<string, unknown> = { period: p.period, total: p.total };
                for (const [cat, pct] of Object.entries(p.adoption)) {
                  row[cat] = Math.round(pct * 100);
                }
                return row;
              }) as { period: string; [k: string]: unknown }[]}
              bars={[]}
              lines={(data.categories?.categories ?? []).map((cat, i) => ({
                dataKey: cat,
                label: cat,
                color: GENRE_COLORS[i % GENRE_COLORS.length],
              }))}
              granularity={isPro ? granularity : "year"}
              height={350}
            />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
