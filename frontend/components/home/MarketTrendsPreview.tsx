"use client";

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
import type { SentimentDistPeriod, ReleaseVolumePeriod } from "@/lib/types";

interface MarketTrendsPreviewProps {
  sentimentData: SentimentDistPeriod[];
  releaseData: ReleaseVolumePeriod[];
}

export function MarketTrendsPreview({
  sentimentData,
  releaseData,
}: MarketTrendsPreviewProps) {
  if (sentimentData.length < 2 && releaseData.length < 2) return null;

  return (
    <section>
      <div className="flex items-center justify-between mb-6">
        <h2 className="font-serif text-xl font-semibold">Market Trends</h2>
        <Link
          href="/explore"
          className="flex items-center gap-1 text-sm font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
        >
          Explore trends <ChevronRight className="w-3 h-3" />
        </Link>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        {/* Sentiment distribution trend */}
        {sentimentData.length >= 2 && (
          <div
            className="rounded-xl p-5"
            style={{
              background: "var(--card)",
              border: "1px solid var(--border)",
            }}
          >
            <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-3">
              Steam sentiment distribution
            </p>
            <ResponsiveContainer width="100%" height={180}>
              <AreaChart
                data={sentimentData}
                margin={{ top: 4, right: 0, left: -20, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="posGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--positive)" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="var(--positive)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="period"
                  tickFormatter={(p) => formatPeriodLabel(p, "month")}
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
                  labelFormatter={(label) => formatPeriodLabel(String(label), "month")}
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
                  fill="url(#posGrad)"
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Release volume trend */}
        {releaseData.length >= 2 && (
          <div
            className="rounded-xl p-5"
            style={{
              background: "var(--card)",
              border: "1px solid var(--border)",
            }}
          >
            <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-3">
              Monthly releases on Steam
            </p>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart
                data={releaseData}
                margin={{ top: 4, right: 0, left: -20, bottom: 0 }}
              >
                <XAxis
                  dataKey="period"
                  tickFormatter={(p) => formatPeriodLabel(p, "month")}
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
                  labelFormatter={(label) => formatPeriodLabel(String(label), "month")}
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
          </div>
        )}
      </div>
    </section>
  );
}
