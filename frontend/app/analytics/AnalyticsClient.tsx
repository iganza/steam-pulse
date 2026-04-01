"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePro } from "@/lib/pro";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { GranularityToggle } from "@/components/trends/GranularityToggle";
import { TrendBarChart } from "@/components/trends/TrendBarChart";
import { TrendStackedArea } from "@/components/trends/TrendStackedArea";
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
  Genre,
  Tag,
} from "@/lib/types";

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

const GENRE_SHARE_TOP_N_OPTIONS = [5, 10, 15];
const GAME_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "game", label: "Games" },
  { value: "dlc", label: "DLC" },
  { value: "all", label: "All" },
];

export function AnalyticsClient() {
  const isPro = usePro();
  const [granularity, setGranularity] = useState<Granularity>("month");
  const [genre, setGenre] = useState<string>("");
  const [tag, setTag] = useState<string>("");
  const [gameType, setGameType] = useState<string>("game");
  const [genreShareTopN, setGenreShareTopN] = useState<number>(5);
  const [sentimentNormalized, setSentimentNormalized] = useState<boolean>(true);
  const [genres, setGenres] = useState<Genre[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [data, setData] = useState<TrendData>(INITIAL);
  const [loading, setLoading] = useState(true);

  // Load genre + tag lists for filter dropdowns
  useEffect(() => {
    fetch("/api/genres")
      .then((r) => r.json())
      .then((d) => setGenres(Array.isArray(d) ? d : []))
      .catch(() => {});
    fetch("/api/tags/top?limit=20")
      .then((r) => r.json())
      .then((d) => setTags(Array.isArray(d) ? d : []))
      .catch(() => {});
  }, []);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    const g = isPro ? granularity : "month";
    const genreSlug = isPro && genre ? genre : undefined;
    const tagSlug = isPro && tag ? tag : undefined;
    const type = isPro ? gameType : "game";
    const topN = isPro ? genreShareTopN : 5;

    const results = await Promise.allSettled([
      getAnalyticsTrendReleaseVolume({ granularity: g, genre: genreSlug, tag: tagSlug, type }),
      getAnalyticsTrendSentiment({ granularity: g, genre: genreSlug, type }),
      getAnalyticsTrendGenreShare({ granularity: isPro ? granularity : "year", top_n: topN, type }),
      getAnalyticsTrendVelocity({ granularity: g, genre: genreSlug, type }),
      getAnalyticsTrendPricing({ granularity: isPro ? granularity : "year", genre: genreSlug, type }),
      getAnalyticsTrendEarlyAccess({ granularity: isPro ? granularity : "year", type }),
      getAnalyticsTrendPlatforms({ granularity: isPro ? granularity : "year", genre: genreSlug, type }),
      getAnalyticsTrendEngagement({ granularity: isPro ? granularity : "year", genre: genreSlug }),
      getAnalyticsTrendCategories({ granularity: isPro ? granularity : "year", top_n: isPro ? 8 : 4, type }),
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
  }, [isPro, granularity, genre, tag, gameType, genreShareTopN]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const g = isPro ? granularity : "month";

  return (
    <div className="space-y-6">
      {/* Control bar */}
      <div className="relative">
        <div className={isPro ? "" : "blur-sm pointer-events-none select-none"}>
          <div className="flex items-center gap-4 flex-wrap">
            <GranularityToggle value={granularity} onChange={setGranularity} disabled={!isPro} />
            {/* Genre filter */}
            <select
              value={genre}
              onChange={(e) => setGenre(e.target.value)}
              className="px-3 py-1.5 rounded-lg bg-card border border-border text-sm text-foreground"
            >
              <option value="">All Genres</option>
              {genres.map((g) => (
                <option key={g.slug} value={g.slug}>{g.name}</option>
              ))}
            </select>
            {/* Tag filter (Pro) */}
            <select
              value={tag}
              onChange={(e) => setTag(e.target.value)}
              className="px-3 py-1.5 rounded-lg bg-card border border-border text-sm text-foreground"
            >
              <option value="">All Tags</option>
              {tags.map((t) => (
                <option key={t.slug} value={t.slug}>{t.name}</option>
              ))}
            </select>
            {/* Type filter (Pro) */}
            <select
              value={gameType}
              onChange={(e) => setGameType(e.target.value)}
              className="px-3 py-1.5 rounded-lg bg-card border border-border text-sm text-foreground"
            >
              {GAME_TYPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            {/* Genre share top-N (Pro) */}
            <div className="flex items-center gap-1">
              <span className="text-xs text-muted-foreground font-mono">Genres:</span>
              <div className="inline-flex rounded-lg border border-border overflow-hidden">
                {GENRE_SHARE_TOP_N_OPTIONS.map((n) => (
                  <button
                    key={n}
                    onClick={() => setGenreShareTopN(n)}
                    className={`px-2 py-1 text-xs font-mono transition-colors ${
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
              data={data.releaseVolume?.periods ?? []}
              dataKey="releases"
              granularity={g}
              secondaryLine={isPro ? { dataKey: "avg_sentiment", color: "#f59e0b" } : undefined}
            />
          </CardContent>
        </Card>

        {/* 2. Sentiment Distribution */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Sentiment Distribution</CardTitle>
            {isPro && (
              <div className="flex items-center gap-2 mt-1">
                <button
                  onClick={() => setSentimentNormalized(true)}
                  className={`text-xs font-mono px-2 py-0.5 rounded transition-colors ${sentimentNormalized ? "bg-teal-500/20 text-teal-400" : "text-muted-foreground hover:text-foreground"}`}
                >
                  % Share
                </button>
                <button
                  onClick={() => setSentimentNormalized(false)}
                  className={`text-xs font-mono px-2 py-0.5 rounded transition-colors ${!sentimentNormalized ? "bg-teal-500/20 text-teal-400" : "text-muted-foreground hover:text-foreground"}`}
                >
                  Raw
                </button>
              </div>
            )}
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
              data={data.genreShare?.periods?.map((p) => {
                const row: Record<string, unknown> = { period: p.period };
                for (const [genre, share] of Object.entries(p.shares)) {
                  row[genre] = share;
                }
                return row;
              }) as unknown[] as import("@/lib/types").TrendPeriod[] ?? []}
              series={(data.genreShare?.genres ?? []).map((genre, i) => ({
                key: genre,
                label: genre,
                color: GENRE_COLORS[i % GENRE_COLORS.length],
              }))}
              granularity={isPro ? granularity : "year"}
            />
          </CardContent>
        </Card>

        {/* 4. Review Velocity */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Review Velocity</CardTitle>
          </CardHeader>
          <CardContent>
            <TrendStackedArea
              data={data.velocity?.periods ?? []}
              series={[
                { key: "velocity_under_1", label: "<1/day", color: "#6b7280" },
                { key: "velocity_1_10", label: "1-10/day", color: "#3b82f6" },
                { key: "velocity_10_50", label: "10-50/day", color: "#14b8a6" },
                { key: "velocity_50_plus", label: "50+/day", color: "#22c55e" },
              ]}
              granularity={g}
              normalized={false}
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
              bars={isPro ? [{ dataKey: "free_pct", label: "Free %", color: "#6366f1" }] : []}
              lines={[{ dataKey: "avg_paid_price", label: "Avg Paid Price", color: "#14b8a6" }]}
              granularity={isPro ? granularity : "year"}
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
              bars={[{ dataKey: "ea_count", label: "EA Games", color: "#8b5cf6" }]}
              lines={[
                { dataKey: "ea_pct", label: "EA %", color: "#f59e0b" },
                ...(isPro
                  ? [
                      { dataKey: "ea_avg_sentiment", label: "EA Sentiment", color: "#22c55e" },
                      { dataKey: "non_ea_avg_sentiment", label: "Non-EA Sentiment", color: "#ef4444" },
                    ]
                  : []),
              ]}
              granularity={isPro ? granularity : "year"}
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
                ...(isPro
                  ? [
                      { dataKey: "deck_verified_pct", label: "Deck Verified %", color: "#22c55e" },
                      { dataKey: "deck_playable_pct", label: "Deck Playable %", color: "#14b8a6" },
                    ]
                  : []),
              ]}
              granularity={isPro ? granularity : "year"}
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
              data={data.categories?.periods?.map((p) => {
                const row: Record<string, unknown> = { period: p.period, total: p.total };
                for (const [cat, pct] of Object.entries(p.adoption)) {
                  row[cat] = Math.round(pct * 100);
                }
                return row;
              }) as unknown[] as import("@/lib/types").TrendPeriod[] ?? []}
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
