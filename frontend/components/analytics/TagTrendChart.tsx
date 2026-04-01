"use client";

import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { TagTrend } from "@/lib/types";

const tooltipStyle = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
};

interface TagTrendChartProps {
  data: TagTrend;
}

export function TagTrendChart({ data }: TagTrendChartProps) {
  if (data.yearly.length < 2) return null;

  const earliestYear = data.yearly[0].year;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Tag Trend: {data.tag}</CardTitle>
        <p className="text-xs text-muted-foreground">
          Growth and sentiment over time
        </p>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart
            data={data.yearly}
            margin={{ top: 4, right: 0, left: -10, bottom: 0 }}
          >
            <XAxis
              dataKey="year"
              tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              yAxisId="left"
              tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              domain={[0, 100]}
              tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip contentStyle={tooltipStyle} />
            <Bar
              yAxisId="left"
              dataKey="game_count"
              name="Games"
              fill="var(--teal)"
              radius={[4, 4, 0, 0]}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="avg_sentiment"
              name="Avg Sentiment %"
              stroke="#22c55e"
              strokeWidth={2}
              dot={{ r: 3, fill: "#22c55e" }}
            />
          </ComposedChart>
        </ResponsiveContainer>

        <div className="mt-4 flex flex-wrap gap-3 text-xs">
          <div
            className="rounded-lg px-3 py-2"
            style={{ background: "var(--card)", border: "1px solid var(--border)" }}
          >
            <span className="text-muted-foreground">Growth: </span>
            <span className="font-medium">
              {data.growth_rate != null ? `${Math.round(data.growth_rate * 100)}%` : "\u2014"} since {earliestYear}
            </span>
          </div>
          <div
            className="rounded-lg px-3 py-2"
            style={{ background: "var(--card)", border: "1px solid var(--border)" }}
          >
            <span className="text-muted-foreground">Peak: </span>
            <span className="font-medium">{data.peak_year ?? "\u2014"}</span>
          </div>
          <div
            className="rounded-lg px-3 py-2"
            style={{ background: "var(--card)", border: "1px solid var(--border)" }}
          >
            <span className="text-muted-foreground">Total: </span>
            <span className="font-medium">{data.total_games.toLocaleString()} games</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
