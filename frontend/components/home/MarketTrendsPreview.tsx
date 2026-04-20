"use client";

import { useEffect, useId, useState } from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { formatPeriodLabel } from "@/components/trends/periodLabel";
import { GranularityToggle } from "@/components/trends/GranularityToggle";
import {
  getAnalyticsTrendSentiment,
  getAnalyticsTrendReleaseVolume,
} from "@/lib/api";
import type {
  Granularity,
  SentimentDistPeriod,
  ReleaseVolumePeriod,
} from "@/lib/types";

const INLINE_HEIGHT = 180;
const FETCH_LIMIT = 200;
const STEAM_ERA_START_YEAR = 2003;

// Strip periods before Steam existed (early 2003). Period strings start with the
// 4-digit year for every granularity ("2003", "2003-01", "2003-Q1", "2003-W01"),
// so a prefix comparison is enough.
function filterSteamEra<T extends { period: string }>(periods: T[]): T[] {
  return periods.filter((p) => {
    const year = parseInt(p.period.slice(0, 4), 10);
    return Number.isFinite(year) && year >= STEAM_ERA_START_YEAR;
  });
}

const RELEASE_LABEL: Record<Granularity, string> = {
  week: "Weekly releases on Steam",
  month: "Monthly releases on Steam",
  quarter: "Quarterly releases on Steam",
  year: "Yearly releases on Steam",
};

function Skeleton({ height }: { height: number }) {
  return (
    <div
      className="bg-secondary rounded animate-pulse"
      style={{ height }}
    />
  );
}

function EmptyState({ height, message }: { height: number; message: string }) {
  return (
    <div
      className="flex items-center justify-center text-xs font-mono text-muted-foreground text-center px-4"
      style={{ height }}
    >
      {message}
    </div>
  );
}

export function MarketTrendsPreview() {
  const gradientId = useId();

  const [granularity, setGranularity] = useState<Granularity>("year");
  const [sentimentData, setSentimentData] = useState<SentimentDistPeriod[]>([]);
  const [releaseData, setReleaseData] = useState<ReleaseVolumePeriod[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);

    Promise.allSettled([
      getAnalyticsTrendSentiment({ granularity, limit: FETCH_LIMIT }, ctrl.signal),
      getAnalyticsTrendReleaseVolume({ granularity, limit: FETCH_LIMIT }, ctrl.signal),
    ]).then((results) => {
      if (ctrl.signal.aborted) return;
      const [sentRes, relRes] = results;
      const sentOk = sentRes.status === "fulfilled";
      const relOk = relRes.status === "fulfilled";
      setSentimentData(sentOk ? filterSteamEra(sentRes.value.periods ?? []) : []);
      setReleaseData(relOk ? filterSteamEra(relRes.value.periods ?? []) : []);
      setFailed(!sentOk && !relOk);
      setLoading(false);
    });

    return () => ctrl.abort();
  }, [granularity]);

  if (failed) return null;

  const hasSentiment = sentimentData.length >= 2;
  const hasReleases = releaseData.length >= 2;

  return (
    <section>
      <div className="flex items-center justify-between mb-6">
        <h2 className="font-serif text-xl font-semibold">Market Trends</h2>
        <GranularityToggle
          value={granularity}
          onChange={setGranularity}
          disabled={loading}
        />
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        {/* Sentiment distribution trend */}
        <div
          className="rounded-xl p-5"
          style={{
            background: "var(--card)",
            border: "1px solid var(--border)",
          }}
        >
          <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-3">
            Positively rated releases
          </p>
          {loading ? (
            <Skeleton height={INLINE_HEIGHT} />
          ) : !hasSentiment ? (
            <EmptyState
              height={INLINE_HEIGHT}
              message="Not enough sentiment data for this view."
            />
          ) : (
            <ResponsiveContainer width="100%" height={INLINE_HEIGHT}>
              <AreaChart
                data={sentimentData}
                margin={{ top: 4, right: 0, left: -20, bottom: 0 }}
              >
                <defs>
                  <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--positive)" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="var(--positive)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="period"
                  tickFormatter={(p) => formatPeriodLabel(p, granularity)}
                  tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: "var(--muted-foreground)" }}
                  axisLine={false}
                  tickLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  domain={[0, 100]}
                  ticks={[50, 100]}
                  tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: "var(--muted-foreground)" }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  formatter={(value) => [`${Number(value).toFixed(1)}%`, "Positive"]}
                  labelFormatter={(label) => formatPeriodLabel(String(label), granularity)}
                  contentStyle={{
                    background: "var(--card)",
                    border: "1px solid var(--border)",
                    borderRadius: "8px",
                    fontSize: "11px",
                    fontFamily: "var(--font-mono)",
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="positive_pct"
                  stroke="var(--positive)"
                  strokeWidth={1.5}
                  fill={`url(#${gradientId})`}
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Release volume trend */}
        <div
          className="rounded-xl p-5"
          style={{
            background: "var(--card)",
            border: "1px solid var(--border)",
          }}
        >
          <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-3">
            {RELEASE_LABEL[granularity]}
          </p>
          {loading ? (
            <Skeleton height={INLINE_HEIGHT} />
          ) : !hasReleases ? (
            <EmptyState
              height={INLINE_HEIGHT}
              message="Not enough release data for this view."
            />
          ) : (
            <ResponsiveContainer width="100%" height={INLINE_HEIGHT}>
              <BarChart
                data={releaseData}
                margin={{ top: 4, right: 0, left: -20, bottom: 0 }}
              >
                <XAxis
                  dataKey="period"
                  tickFormatter={(p) => formatPeriodLabel(p, granularity)}
                  tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: "var(--muted-foreground)" }}
                  axisLine={false}
                  tickLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: "var(--muted-foreground)" }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  formatter={(value) => [Number(value).toLocaleString(), "Releases"]}
                  labelFormatter={(label) => formatPeriodLabel(String(label), granularity)}
                  contentStyle={{
                    background: "var(--card)",
                    border: "1px solid var(--border)",
                    borderRadius: "8px",
                    fontSize: "11px",
                    fontFamily: "var(--font-mono)",
                  }}
                />
                <Bar
                  dataKey="releases"
                  fill="var(--teal)"
                  radius={[3, 3, 0, 0]}
                  opacity={0.7}
                />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between gap-4 flex-wrap">
        <p className="text-xs text-muted-foreground">
          Sentiment: share of games released in each period with Steam review score ≥70% (among games with ≥10 English reviews).
        </p>
        <Link
          href="/reports"
          className="flex items-center gap-1 text-sm font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
        >
          Browse reports <ChevronRight className="w-3 h-3" />
        </Link>
      </div>
    </section>
  );
}
