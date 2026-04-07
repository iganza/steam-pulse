"use client";

import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Line, CartesianGrid,
  ComposedChart,
} from "recharts";
import type { Granularity, TrendPeriod } from "@/lib/types";
import { formatPeriodLabel } from "./periodLabel";

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
  secondaryLine?: { dataKey: string; color: string; sameAxis?: boolean };
  height?: number;
}) {
  if (data.length < 2) {
    return (
      <div className="flex items-center justify-center text-muted-foreground text-sm" style={{ height }}>
        Not enough data for this view
      </div>
    );
  }

  const tooltipStyle = { background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 };
  const tickFmt = (v: string) => formatPeriodLabel(v, granularity);

  if (secondaryLine) {
    // sameAxis=true: MA overlay shares left axis (same unit as bars)
    // sameAxis=false (default): secondary line on right axis (different unit, e.g. avg_steam_pct)
    const lineAxisId = secondaryLine.sameAxis ? "left" : "right";
    return (
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey={xKey} tick={{ fontSize: 11 }} tickFormatter={tickFmt} />
          <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
          {!secondaryLine.sameAxis && <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />}
          <Tooltip contentStyle={tooltipStyle} />
          <Bar yAxisId="left" dataKey={dataKey} fill={color} radius={[2, 2, 0, 0]} />
          <Line yAxisId={lineAxisId} type="monotone" dataKey={secondaryLine.dataKey} stroke={secondaryLine.color} strokeWidth={2} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey={xKey} tick={{ fontSize: 11 }} tickFormatter={tickFmt} />
        <YAxis tick={{ fontSize: 11 }} />
        <Tooltip contentStyle={tooltipStyle} />
        <Bar dataKey={dataKey} fill={color} radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
