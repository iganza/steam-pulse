"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { ReviewVelocity } from "@/lib/types";

const tooltipStyle = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
};

interface ReviewVelocityChartProps {
  data: ReviewVelocity;
}

function formatMonth(monthStr: string): string {
  const [year, month] = monthStr.split("-");
  const d = new Date(Number(year), Number(month) - 1);
  return d.toLocaleDateString("en-US", { month: "short" }) + " \u2018" + year.slice(2);
}

function trendBadge(trend: "accelerating" | "stable" | "decelerating") {
  const styles: Record<string, { bg: string; color: string; label: string }> = {
    accelerating: { bg: "rgba(34,197,94,0.15)", color: "#22c55e", label: "Accelerating" },
    stable: { bg: "rgba(107,114,128,0.15)", color: "#6b7280", label: "Stable" },
    decelerating: { bg: "rgba(239,68,68,0.15)", color: "#ef4444", label: "Decelerating" },
  };
  const s = styles[trend];
  return (
    <span
      className="text-xs font-medium px-2 py-0.5 rounded-full"
      style={{ background: s.bg, color: s.color }}
    >
      {s.label}
    </span>
  );
}

export function ReviewVelocityChart({ data }: ReviewVelocityChartProps) {
  if (data.monthly.length < 2) return null;

  const { summary } = data;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Review Velocity</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={data.monthly}>
            <defs>
              <linearGradient id="velocityGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis
              dataKey="month"
              tickFormatter={formatMonth}
              tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              axisLine={false}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              contentStyle={tooltipStyle}
              labelFormatter={(label) => formatMonth(String(label))}
            />
            <ReferenceLine
              y={summary.avg_monthly}
              stroke="var(--muted-foreground)"
              strokeDasharray="5 5"
              label={{ value: "Avg", fill: "var(--muted-foreground)", fontSize: 11, position: "right" }}
            />
            <Area
              type="monotone"
              dataKey="total"
              name="Reviews"
              stroke="#3b82f6"
              strokeWidth={2}
              fill="url(#velocityGrad)"
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>

        <div className="mt-4 flex flex-wrap items-center gap-4 text-sm">
          {trendBadge(summary.trend)}
          <span className="text-muted-foreground">
            Last 30 days: <span className="font-mono font-medium text-foreground">{summary.last_30_days}</span>
          </span>
          <span className="text-muted-foreground">
            Monthly avg: <span className="font-mono font-medium text-foreground">{Math.round(summary.avg_monthly)}</span>
          </span>
          {summary.peak_month && (
            <span className="text-muted-foreground">
              Peak: <span className="font-mono font-medium text-foreground">
                {formatMonth(summary.peak_month.month)} ({summary.peak_month.total})
              </span>
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
