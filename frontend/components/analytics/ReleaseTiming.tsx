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
import type { ReleaseTiming as ReleaseTimingData } from "@/lib/types";

const tooltipStyle = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
};

interface ReleaseTimingProps {
  data: ReleaseTimingData;
}

export function ReleaseTiming({ data }: ReleaseTimingProps) {
  if (data.monthly.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Release Timing</CardTitle>
        <p className="text-xs text-muted-foreground">
          Monthly release patterns for {data.genre}
        </p>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart
            data={data.monthly}
            margin={{ top: 4, right: 0, left: -10, bottom: 0 }}
          >
            <XAxis
              dataKey="month_name"
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
              dataKey="releases"
              name="Releases"
              fill="#6b7280"
              radius={[4, 4, 0, 0]}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="avg_steam_pct"
              name="Avg Steam %"
              stroke="#22c55e"
              strokeWidth={2}
              dot={{ r: 3, fill: "#22c55e" }}
            />
          </ComposedChart>
        </ResponsiveContainer>

        <div className="mt-4 flex flex-wrap gap-3 text-xs">
          {data.best_month && (
            <div
              className="rounded-lg px-3 py-2"
              style={{ background: "var(--card)", border: "1px solid var(--border)" }}
            >
              <span style={{ color: "#22c55e" }} className="font-medium">
                Best: {data.best_month.month_name}
              </span>
              <span className="text-muted-foreground">
                {" "}({data.best_month.avg_steam_pct ?? "\u2014"}% avg)
              </span>
            </div>
          )}
          {data.busiest_month && (
            <div
              className="rounded-lg px-3 py-2"
              style={{ background: "var(--card)", border: "1px solid var(--border)" }}
            >
              <span className="font-medium">Busiest: {data.busiest_month.month_name}</span>
              <span className="text-muted-foreground">
                {" "}({data.busiest_month.releases} releases)
              </span>
            </div>
          )}
          {data.quietest_month && (
            <div
              className="rounded-lg px-3 py-2"
              style={{ background: "var(--card)", border: "1px solid var(--border)" }}
            >
              <span className="font-medium">Quietest: {data.quietest_month.month_name}</span>
              <span className="text-muted-foreground">
                {" "}({data.quietest_month.releases} releases)
              </span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
