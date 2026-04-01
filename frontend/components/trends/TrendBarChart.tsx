"use client";

import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Line, CartesianGrid,
  ComposedChart,
} from "recharts";
import type { Granularity, TrendPeriod } from "@/lib/types";

function formatXLabel(period: string, _granularity: Granularity): string {
  // Already formatted by the API: "2024-01", "2024", "2024-Q1", "2024-W03"
  return period;
}

export function TrendBarChart({
  data,
  dataKey,
  xKey = "period",
  color = "var(--teal)",
  granularity,
  secondaryLine,
  height = 300,
}: {
  data: TrendPeriod[];
  dataKey: string;
  xKey?: string;
  color?: string;
  granularity: Granularity;
  secondaryLine?: { dataKey: string; color: string };
  height?: number;
}) {
  if (data.length < 2) {
    return (
      <div className="flex items-center justify-center text-muted-foreground text-sm" style={{ height }}>
        Not enough data for this view
      </div>
    );
  }

  if (secondaryLine) {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey={xKey} tick={{ fontSize: 11 }} tickFormatter={(v) => formatXLabel(v, granularity)} />
          <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
          <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
          <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
          <Bar yAxisId="left" dataKey={dataKey} fill={color} radius={[2, 2, 0, 0]} />
          <Line yAxisId="right" type="monotone" dataKey={secondaryLine.dataKey} stroke={secondaryLine.color} strokeWidth={2} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey={xKey} tick={{ fontSize: 11 }} tickFormatter={(v) => formatXLabel(v, granularity)} />
        <YAxis tick={{ fontSize: 11 }} />
        <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
        <Bar dataKey={dataKey} fill={color} radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
