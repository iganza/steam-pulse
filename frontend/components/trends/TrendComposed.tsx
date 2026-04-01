"use client";

import {
  ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import type { Granularity, TrendPeriod } from "@/lib/types";
import { formatPeriodLabel } from "./periodLabel";

export function TrendComposed({
  data,
  bars,
  lines,
  granularity,
  height = 300,
}: {
  data: TrendPeriod[];
  bars: { dataKey: string; label: string; color: string }[];
  lines: { dataKey: string; label: string; color: string }[];
  granularity: Granularity;
  height?: number;
}) {
  if (data.length < 2) {
    return (
      <div className="flex items-center justify-center text-muted-foreground text-sm" style={{ height }}>
        Not enough data for this view
      </div>
    );
  }

  // Only use a dual axis when there are both bars and lines — mixing bars and
  // lines on the same axis is fine when there are no bars (lines-only charts).
  // Rendering a right axis for a lines-only chart produces an unused axis.
  const hasDualAxis = bars.length > 0 && lines.length > 0;
  const lineAxisId = hasDualAxis ? "right" : "left";

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="period" tick={{ fontSize: 11 }} tickFormatter={(v) => formatPeriodLabel(v, granularity)} />
        <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
        {hasDualAxis && <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />}
        <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {bars.map((b) => (
          <Bar key={b.dataKey} yAxisId="left" dataKey={b.dataKey} name={b.label} fill={b.color} radius={[2, 2, 0, 0]} />
        ))}
        {lines.map((l) => (
          <Line key={l.dataKey} yAxisId={lineAxisId} type="monotone" dataKey={l.dataKey} name={l.label} stroke={l.color} strokeWidth={2} dot={false} />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
